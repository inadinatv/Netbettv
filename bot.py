#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Netbettv otomatik güncelleme botu.

Görevleri:
  1. Telegram duyuru kanalından güncel yayın domainini bulur.
  2. index.html içindeki BASE_URL değerini güncel domain ile değiştirir
     (aynı domaini config.json dosyasına da yazar; frontend önce orayı okur).
  3. Yayın sitesinin kullandığı maç veri kaynağını çeker ve matches.json'a yazar.

Yayın sitesi (fixbettvXX) maç listesini sayfa içindeki bir
``fetch('https://data-reality.com/matches2.php')`` çağrısı ile yükler. Bu uç
nokta doğrudan HTML döndürdüğü için (JS çalıştırmadan) çekilebilir. Bot önce ana
sayfadan bu kaynağı kendisi keşfeder; site kaynağını değiştirirse otomatik uyum
sağlar, bulamazsa bilinen varsayılan kaynakları dener.

Kullanım:
  python bot.py --once    # tek çalıştırma (GitHub Actions için varsayılan)
  python bot.py --loop    # sürekli döngü (yerel kullanım, UPDATE_INTERVAL ile)

Ortam değişkenleri:
  MASTER_URLS      : virgülle ayrılmış duyuru kaynağı (varsayılan: t.me/s/fixresmitg,t.me/s/fixbet)
  DEFAULT_DOMAIN   : hiçbir kaynak çalışmazsa kullanılacak domain
  UPDATE_INTERVAL  : --loop modunda bekleme süresi (saniye, varsayılan 600)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:  # pragma: no cover
    import requests  # type: ignore
    HAS_CLOUDSCRAPER = False

from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("netbettv")

ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------
class Config:
    INDEX_HTML_PATH = ROOT / "index.html"
    MATCHES_JSON_PATH = ROOT / "matches.json"
    CONFIG_JSON_PATH = ROOT / "config.json"
    ENCODING = "utf-8"

    # index.html içindeki BASE_URL satırını yakalayan desen (marker'lar sabit kalmalı)
    BASE_URL_PATTERN = re.compile(r'(//\s*BASE_URL_START\s*\n\s*const BASE_URL=")(.*?)(";)')

    DEFAULT_DOMAIN = os.environ.get("DEFAULT_DOMAIN", "https://fixbettv84.com/")
    MASTER_URLS = [
        u.strip() for u in os.environ.get(
            "MASTER_URLS",
            "https://t.me/s/fixresmitg,https://t.me/s/fixbet",
        ).split(",") if u.strip()
    ]
    UPDATE_INTERVAL = int(os.environ.get("UPDATE_INTERVAL", "600"))

    TIMEOUT = 25


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


def new_scraper():
    """Cloudflare bypass'lı (mümkünse) bir HTTP istemcisi döndürür."""
    if HAS_CLOUDSCRAPER:
        return cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
    import requests  # type: ignore

    session = requests.Session()
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
    return session


# ---------------------------------------------------------------------------
# Atomik / değişiklik-farkında dosya yazma
# ---------------------------------------------------------------------------
def atomic_write(path: Path, content: str) -> bool:
    """Dosyayı atomik yazar. İçerik değişmediyse dokunmaz (gereksiz commit olmasın)."""
    try:
        if path.exists() and path.read_text(encoding=Config.ENCODING) == content:
            logger.debug(f"Değişiklik yok: {path.name}")
            return False
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding=Config.ENCODING)
        os.replace(tmp, path)
        logger.info(f"Güncellendi: {path.name}")
        return True
    except OSError as e:
        logger.error(f"Yazma hatası ({path.name}): {e}")
        return False


def read_current_base_url() -> str:
    """index.html'de şu an yazılı olan BASE_URL değerini okur (fallback için)."""
    try:
        content = Config.INDEX_HTML_PATH.read_text(encoding=Config.ENCODING)
        match = Config.BASE_URL_PATTERN.search(content)
        if match and match.group(2).startswith("http"):
            return match.group(2)
    except OSError:
        pass
    return Config.DEFAULT_DOMAIN


# ---------------------------------------------------------------------------
# Domain bulucu
# ---------------------------------------------------------------------------
class DomainFetcher:
    """Telegram duyuru kanallarından güncel fixbettv domainini toplar ve doğrular."""

    DOMAIN_RE = re.compile(r"https?://(?:www\.)?[a-zA-Z0-9-]*fixbettv[0-9]*\.[a-zA-Z]{2,}/?")

    def __init__(self, master_urls: List[str]):
        self.master_urls = master_urls
        self.scraper = new_scraper()

    def _collect_candidates(self) -> List[str]:
        candidates: List[str] = []
        for url in self.master_urls:
            try:
                response = self.scraper.get(url, timeout=Config.TIMEOUT)
                found = self.DOMAIN_RE.findall(response.text)
                if found:
                    unique = list(dict.fromkeys(found))  # sırayı koru, tekilleştir
                    logger.info(f"{url} -> {len(unique)} aday domain: {unique}")
                    candidates.extend(unique)
            except Exception as e:
                logger.warning(f"Duyuru kaynağı okunamadı ({url}): {e}")
        # En son duyurulan (en güncel) domain önce denensin
        return list(dict.fromkeys(candidates))[::-1]

    def _validate(self, domain: str) -> bool:
        """Domain gerçekten yayına yanıt veriyor mu diye hızlıca kontrol eder."""
        if not domain.endswith("/"):
            domain += "/"
        try:
            self.scraper.headers.update({"Referer": domain})
            response = self.scraper.get(domain, timeout=Config.TIMEOUT)
            if response.status_code < 500 and len(response.text) > 300:
                return True
            logger.warning(f"Aday domain şüpheli yanıt verdi ({domain}): {response.status_code}")
        except Exception as e:
            logger.warning(f"Aday domain yanıtsız ({domain}): {e}")
        return False

    def fetch(self) -> str:
        candidates = self._collect_candidates()
        for candidate in candidates:
            if self._validate(candidate):
                logger.info(f"Güncel domain doğrulandı: {candidate}")
                return candidate
        fallback = read_current_base_url()
        logger.error(f"Doğrulanmış domain bulunamadı. Mevcut domain korunuyor: {fallback}")
        return fallback


# ---------------------------------------------------------------------------
# Maç verisi toplayıcı
# ---------------------------------------------------------------------------
class MatchFetcher:
    """Yayın sitesinin maç listesini, sitenin kullandığı veri kaynağından çıkarır.

    Site maç listesini şu şekilde yükler::

        fetch('https://data-reality.com/matches2.php')
            .then(r => r.text())
            .then(html => { document.getElementById('matches-tab').innerHTML = html })

    Bu uç nokta aşağıdaki biçimde HTML döndürür::

        <a href="channel?id=trt1" class="channel-item [hidden]">
            <div class="channel-name">Almanya vs Türkiye</div>
            <div class="channel-status">19:00 | CEV Kadınlar Avrupa Şampiyonası</div>
        </a>

    ``hidden`` sınıfı geçmiş (bitmiş) maçları işaretler; site bunları gizler.
    """

    # Site değişse de genellikle sabit kalan bilinen veri kaynakları
    DEFAULT_ENDPOINTS = [
        "https://data-reality.com/matches2.php",
        "https://data-reality.com/matches.php",
    ]

    # Ana sayfadan veri kaynağını bulan desenler
    ENDPOINT_RE = re.compile(r"fetch\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.IGNORECASE)
    LOAD_RE = re.compile(r"\.load\s*\(\s*['\"]([^'\"]+)['\"]\s*\)", re.IGNORECASE)

    # <a href="channel?id=xxx"> içindeki id
    CHANNEL_ITEM_ID_RE = re.compile(r"[?&]id=([^&#\"']+)")

    ID_RE = re.compile(r"(?:id=|kanal=|channel=|yayin=|watch=|/izle/)([-a-zA-Z0-9_]+)")
    TIME_RE = re.compile(r"\b([01]?[0-9]|2[0-3])[:.]([0-5][0-9])\b")
    JSON_IN_SCRIPT_RE = re.compile(
        r"(?:var|let|const)\s+(?:matches|maclar|fixtures|games)\s*=\s*(\[.*?\])\s*;",
        re.DOTALL,
    )
    LEAGUE_RE = re.compile(
        r"(.*?)(Süper Lig|Lig|Kupa|Premier|La Liga|Serie A|Bundesliga|Ligue 1|NBA|"
        r"Euroleague|Champions|Şampiyonlar|Dünya Kupası|Oyunları|Play-Off)(.*)",
        re.IGNORECASE,
    )

    def __init__(self, current_domain: str):
        self.current_domain = current_domain
        self.scraper = new_scraper()
        self.scraper.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        self.scraper.headers.update({"Referer": current_domain})

    # -- uç nokta keşfi ------------------------------------------------------
    def _discover_endpoints(self, html: str) -> List[str]:
        """Ana sayfadan, maç listesinin yüklendiği veri kaynaklarını bulur."""
        endpoints: List[str] = []
        for pattern in (self.ENDPOINT_RE, self.LOAD_RE):
            for m in pattern.finditer(html):
                url = m.group(1).strip()
                if url.startswith("http") and url not in endpoints:
                    endpoints.append(url)
        return endpoints

    # -- ana çıkarma yöntemi -------------------------------------------------
    def _parse_matches_html(self, html: str) -> List[Dict[str, str]]:
        """data-reality benzeri kaynağın döndürdüğü HTML'den maçları çıkarır."""
        matches: List[Dict[str, str]] = []
        soup = BeautifulSoup(html, "html.parser")

        for a_tag in soup.find_all("a", class_="channel-item"):
            href = a_tag.get("href", "")
            id_match = self.CHANNEL_ITEM_ID_RE.search(href)
            channel_id = id_match.group(1) if id_match else ""
            if not channel_id:
                continue

            name_el = a_tag.find(class_="channel-name")
            status_el = a_tag.find(class_="channel-status")
            title = name_el.get_text(" ", strip=True) if name_el else ""
            status = status_el.get_text(" ", strip=True) if status_el else ""

            # "13:00 | Premier Padel" -> time + league
            time_str, league = "", ""
            if "|" in status:
                left, _, right = status.partition("|")
                time_str = left.strip()
                league = right.strip()
            else:
                league = status

            classes = a_tag.get("class") or []
            is_hidden = "hidden" in classes

            if not time_str:
                t_match = self.TIME_RE.search(title)
                if t_match:
                    time_str = t_match.group(0)
            if not time_str:
                continue

            if not title:
                title = league or "Maç"

            matches.append(
                {
                    "time": time_str,
                    "title": title,
                    "type": league or "Maç",
                    "channel_id": channel_id,
                    "hidden": is_hidden,
                }
            )

        return matches

    # -- yedek yöntemler -----------------------------------------------------
    def _extract_from_script_json(self, html: str) -> List[Dict[str, str]]:
        matches: List[Dict[str, str]] = []
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            text = script.string or script.get_text() or ""
            json_match = self.JSON_IN_SCRIPT_RE.search(text)
            if not json_match:
                continue
            try:
                data = json.loads(json_match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(data, list):
                continue
            for m in data:
                if not isinstance(m, dict):
                    continue
                time_str = str(m.get("time", m.get("saat", m.get("hour", "")))).strip()
                title = str(m.get("title", m.get("baslik", m.get("mac", m.get("match", ""))))).strip()
                league = str(m.get("type", m.get("lig", m.get("league", "Maç")))).strip() or "Maç"
                channel_id = str(m.get("channel_id", m.get("kanal", m.get("id", "")))).strip()
                if time_str and title:
                    matches.append(
                        {"time": time_str, "title": title, "type": league,
                         "channel_id": channel_id, "hidden": False}
                    )
            if matches:
                logger.info("Maçlar script içindeki JSON'dan çıkarıldı.")
        return matches

    def _extract_from_links(self, html: str) -> List[Dict[str, str]]:
        matches: List[Dict[str, str]] = []
        soup = BeautifulSoup(html, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(separator=" ", strip=True)
            time_match = self.TIME_RE.search(text)
            if not time_match:
                continue

            href = a_tag["href"]
            channel_id = ""
            id_match = self.ID_RE.search(href)
            if id_match:
                channel_id = id_match.group(1)
            else:
                parts = [p for p in href.split("/") if p and not p.startswith("#")]
                if parts:
                    channel_id = parts[-1]

            if not channel_id or channel_id in ("#", "javascript:void(0)"):
                onclick = a_tag.get("onclick", "")
                click_match = re.search(r"[\"']([a-zA-Z0-9_-]+)[\"']", onclick)
                if click_match:
                    channel_id = click_match.group(1)

            if not channel_id:
                continue

            time_str = time_match.group(0)
            raw_text = text.replace(time_str, "", 1).strip(" -–|·")

            title, league = "", "Maç"
            if "|" in raw_text:
                left, right = raw_text.split("|", 1)
                title = left.strip(" -–|·")
                league = right.strip(" -–|·") or "Maç"
            else:
                league_match = self.LEAGUE_RE.search(raw_text)
                if league_match:
                    league = (league_match.group(2) + league_match.group(3)).strip(" -|")
                    title = league_match.group(1).strip(" -|")
            if not title:
                title = raw_text
            if len(title) < 3:
                continue

            if not any(m["title"] == title and m["time"] == time_str for m in matches):
                matches.append(
                    {"time": time_str, "title": title, "type": league,
                     "channel_id": channel_id, "hidden": False}
                )
        return matches

    @staticmethod
    def _sort_key(match: Dict[str, str]):
        time_match = re.match(r"^(\d{1,2})[:.](\d{2})$", match.get("time", ""))
        return (0, int(time_match.group(1)), int(time_match.group(2))) if time_match else (1, 0, 0)

    def _dedupe(self, matches: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen, unique = set(), []
        for m in matches:
            key = (m["title"].lower(), m["time"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(m)
        unique.sort(key=self._sort_key)
        return unique

    # -- ana akış ------------------------------------------------------------
    def fetch(self) -> List[Dict[str, str]]:
        endpoints = list(self.DEFAULT_ENDPOINTS)

        # 1) Ana sayfadan güncel veri kaynağını keşfet (site kaynağını değiştirirse uyum sağla)
        try:
            logger.info(f"Veri kaynağı aranıyor -> {self.current_domain}")
            response = self.scraper.get(self.current_domain, timeout=Config.TIMEOUT)
            discovered = self._discover_endpoints(response.text)
            if discovered:
                logger.info(f"Keşfedilen veri kaynakları: {discovered}")
                for ep in discovered:
                    if ep not in endpoints:
                        endpoints.append(ep)
        except Exception as e:
            logger.warning(f"Ana sayfa okunamadı, varsayılan kaynaklar kullanılacak: {e}")

        # 2) Kaynakları dene ve ilk başarılı olanı kullan
        for url in endpoints:
            try:
                logger.info(f"Maçlar aranıyor -> {url}")
                response = self.scraper.get(url, timeout=Config.TIMEOUT)
                parsed = self._parse_matches_html(response.text)
                if parsed:
                    logger.info(f"BAŞARILI: {url} üzerinden {len(parsed)} maç bulundu.")
                    return self._dedupe(parsed)
                logger.warning(f"{url} içinde maç bulunamadı.")
            except Exception as e:
                logger.error(f"{url} ulaşılamadı: {e}")

        # 3) Yedek: ana sayfa bağlantıları / script JSON
        try:
            response = self.scraper.get(self.current_domain, timeout=Config.TIMEOUT)
            for parsed in (
                self._extract_from_script_json(response.text),
                self._extract_from_links(response.text),
            ):
                if parsed:
                    logger.info(f"Yedek yöntemle {len(parsed)} maç bulundu.")
                    return self._dedupe(parsed)
        except Exception as e:
            logger.error(f"Yedek yöntem başarısız: {e}")

        logger.error("HİÇBİR KAYNAKTAN MAÇ VERİSİ ALINAMADI.")
        return []


# ---------------------------------------------------------------------------
# Sistem güncelleyici
# ---------------------------------------------------------------------------
class SystemUpdater:
    def __init__(self):
        self.domain_fetcher = DomainFetcher(Config.MASTER_URLS)

    def update_domain(self, new_domain: str) -> bool:
        """index.html'deki BASE_URL satırını ve config.json'ı günceller."""
        if not Config.INDEX_HTML_PATH.exists():
            logger.error("index.html dosyası bulunamadı!")
            return False
        try:
            content = Config.INDEX_HTML_PATH.read_text(encoding=Config.ENCODING)
            new_content, count = Config.BASE_URL_PATTERN.subn(
                lambda m: m.group(1) + new_domain + m.group(3), content
            )
            if count == 0:
                logger.error("index.html içinde BASE_URL bloğu bulunamadı!")
                return False
            changed = atomic_write(Config.INDEX_HTML_PATH, new_content)
            if changed:
                logger.info(f"index.html domain güncellendi: {new_domain}")

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            config_data = {"base_url": new_domain, "updated_at": now}
            atomic_write(Config.CONFIG_JSON_PATH, json.dumps(config_data, ensure_ascii=False, indent=2) + "\n")
            return True
        except OSError as e:
            logger.error(f"index.html hatası: {e}")
            return False

    def save_matches(self, matches: List[Dict[str, str]], source_domain: str) -> bool:
        now = datetime.now(timezone.utc)
        payload = {
            "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updated_at_display": now.astimezone().strftime("%d.%m.%Y %H:%M"),
            "source": source_domain,
            "count": len(matches),
            "matches": matches,
        }
        return atomic_write(
            Config.MATCHES_JSON_PATH, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    def run(self) -> None:
        new_domain = self.domain_fetcher.fetch()
        self.update_domain(new_domain)

        match_fetcher = MatchFetcher(current_domain=new_domain)
        matches = match_fetcher.fetch()
        if matches:
            self.save_matches(matches, new_domain)
            logger.info(f"Tur tamamlandı — {len(matches)} maç, domain: {new_domain}")
        else:
            # Geçici aksaklıkta son geçerli veriyi ezme; mevcut matches.json kalsın.
            logger.warning(
                "Maç verisi alınamadı; mevcut matches.json korunuyor "
                "(son geçerli liste ekranda kalır)."
            )


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Netbettv otomatik güncelleme botu")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="tek tur çalış (CI için)")
    mode.add_argument("--loop", action="store_true", help="sürekli döngüde çalış")
    args = parser.parse_args()

    updater = SystemUpdater()

    if not args.loop:
        if not args.once:
            logger.info("Tek mod (--once) çalıştırılıyor. Sürekli çalıştırma için: python bot.py --loop")
        try:
            updater.run()
        except Exception as e:
            logger.error(f"Tur hatası: {e}")
            return 1
        return 0

    logger.info(f"BOT BAŞLADI (döngü modu: her {Config.UPDATE_INTERVAL // 60} dakikada bir günceller)")
    while True:
        try:
            updater.run()
        except Exception as e:
            logger.error(f"Döngü hatası: {e}")
        logger.info(f"{Config.UPDATE_INTERVAL} saniye bekleniyor...")
        time.sleep(Config.UPDATE_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
