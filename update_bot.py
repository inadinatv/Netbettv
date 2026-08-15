import re
import json
import logging
from pathlib import Path
from typing import List, Dict

import cloudscraper
from bs4 import BeautifulSoup

# Logging ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    INDEX_HTML_PATH = Path('index.html')
    MATCHES_JSON_PATH = Path('matches.json')
    DEBUG_HTML_PATH = Path('debug_html.txt') # Siteyi nasıl gördüğümüzü kaydettiğimiz dosya
    ENCODING = 'utf-8'
    
    BASE_URL_PATTERN = re.compile(r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)')
    DEFAULT_DOMAIN = "https://fixbettv84.com/"
    MASTER_URL = "https://t.me/s/fixbet"


class DomainFetcher:
    def __init__(self, master_url: str = Config.MASTER_URL):
        self.master_url = master_url
        # Cloudflare'i aşmak için cloudscraper kullanıyoruz
        self.scraper = cloudscraper.create_scraper(browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        })
    
    def fetch(self) -> str:
        try:
            response = self.scraper.get(self.master_url, timeout=15)
            response.raise_for_status()
            current_url = Config.DEFAULT_DOMAIN
            
            # Telegram'dan güncel fixbettv linkini bul
            found_urls = re.findall(r'https?://(?:www\.)?[a-zA-Z0-9-]*fixbettv[0-9]*\.[a-zA-Z]+/?', response.text)
            if found_urls:
                unique_urls = list(dict.fromkeys(found_urls))
                current_url = unique_urls[-1]
            
            if not current_url.endswith('/'):
                current_url += '/'
            
            logger.info(f"Güncel domain Telegram'dan tespit edildi: {current_url}")
            return current_url
        except Exception as e:
            logger.error(f"Domain çekilirken hata: {e}. Varsayılan kullanılacak.")
            return Config.DEFAULT_DOMAIN


class MatchFetcher:
    def __init__(self, current_domain: str):
        self.current_domain = current_domain
        # Standart Requests yerine Cloudscraper ile siteye bağlanıyoruz
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        # Bazen maçlar iframe veya özel API sayfalarında tutulur. Tüm olasılıkları ekliyoruz.
        self.sources = [
            self.current_domain,
            f"{self.current_domain}ajax/matches",
            "https://data-reality.com/matches2.php"
        ]

    def _smart_extract_matches(self, html_content: str) -> List[Dict]:
        matches = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Sitedeki TÜM linkleri (a etiketlerini) tarıyoruz. Sınıf adı ne olursa olsun affetmez.
        for a_tag in soup.find_all('a', href=True):
            # Elementin içindeki tüm yazıları aralarında boşluk bırakarak al
            text = a_tag.get_text(separator=' ', strip=True)
            
            # Yazının içinde 19:00, 21.45 gibi SAAT formatı var mı?
            time_match = re.search(r'\b([01]?[0-9]|2[0-3])[:.]([0-5][0-9])\b', text)
            if not time_match:
                continue
                
            href = a_tag['href']
            
            # Linkin içinde id= veya kanal= gibi bir parametre var mı? Veya linkin sonu kanal ismi mi?
            channel_id = ""
            id_match = re.search(r'(?:id=|kanal=|channel=|yayin=|watch=|/izle/)([-a-zA-Z0-9_]+)', href)
            
            if id_match:
                channel_id = id_match.group(1)
            else:
                # Örn: href="/bein-sports-1" formatı
                parts = [p for p in href.split('/') if p and not p.startswith('#')]
                if parts:
                    channel_id = parts[-1]
            
            # Eğer onclick parametresi varsa id oradadır
            if not channel_id or channel_id in ['#', 'javascript:void(0)']:
                onclick = a_tag.get('onclick', '')
                click_match = re.search(r'[\'"]([a-zA-Z0-9_-]+)[\'"]', onclick)
                if click_match:
                    channel_id = click_match.group(1)
            
            # Kanal idsini hala bulamadıysa bu maç linki değildir, geç
            if not channel_id:
                continue

            time_str = time_match.group(0)
            
            # Başlık kısmından saati temizle
            raw_title = text.replace(time_str, '').strip(' -|/>')
            
            # Başlığı ikiye bölmeye çalış (Takımlar ve Lig)
            league = "Maç"
            title = raw_title
            
            # İçinde Lig, Kupa, Series kelimeleri geçiyorsa ayır
            league_match = re.search(r'(.*?)(Süper Lig|Lig|Kupa|Premier|La Liga|Serie A|Ligue 1|NBA|Euroleague|Champions|Şampiyonlar)(.*)', raw_title, re.IGNORECASE)
            if league_match:
                league = (league_match.group(2) + league_match.group(3)).strip(' -|')
                title = league_match.group(1).strip(' -|')
                
            if not title:
                title = raw_title

            # Eğer title çok kısaysa mantıksızdır, atla
            if len(title) < 5:
                continue

            # Aynı maçı (aynı takım ve saat) iki defa ekleme
            if not any(m['title'] == title and m['time'] == time_str for m in matches):
                matches.append({
                    'time': time_str,
                    'title': title,
                    'type': league,
                    'channel_id': channel_id
                })
        
        return matches

    def fetch_and_save(self) -> bool:
        matches = []
        html_saved = False
        
        for url in self.sources:
            try:
                logger.info(f"Maçlar Aranıyor -> {url}")
                response = self.scraper.get(url, timeout=15)
                
                # Cloudflare veya Bot engel ekranına düştük mü kontrolü
                if "Just a moment..." in response.text or "cf-browser-verification" in response.text:
                    logger.warning(f"[ENGEL] {url} adresinde Cloudflare Captcha korumasına takıldık!")
                    continue
                
                # Sadece ilk girdiğimiz sayfanın HTML'ini debug için kaydedelim
                if not html_saved:
                    with open(Config.DEBUG_HTML_PATH, 'w', encoding=Config.ENCODING) as f:
                        f.write(response.text)
                    logger.info(f"Sitenin HTML kaynak kodu incelenmek üzere '{Config.DEBUG_HTML_PATH.name}' dosyasına kaydedildi.")
                    html_saved = True

                parsed_matches = self._smart_extract_matches(response.text)
                
                if parsed_matches:
                    matches = parsed_matches
                    logger.info(f"BAŞARILI! {url} üzerinden {len(matches)} adet maç çekildi.")
                    break # Bulduysak diğer alternatif adreslere bakmaya gerek yok
                else:
                    logger.warning(f"Uyarı: {url} adresinde saat formatına uyan maç bilgisi bulunamadı.")
            except Exception as e:
                logger.error(f"{url} ulaşılamadı: {e}")

        if not matches:
            logger.error("HİÇBİR KAYNAKTAN MAÇ VERİSİ ALINAMADI! (debug_html.txt dosyasını kontrol edin, site tasarımı tamamen değişmiş olabilir.)")
            # Yine de boş dizi yazdıralım ki eski günün maçları sitede kalmasın
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump([], f, ensure_ascii=False, indent=4)
            return False
            
        try:
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump(matches, f, ensure_ascii=False, indent=4)
            logger.info(f"Tüm maç verileri '{Config.MATCHES_JSON_PATH.name}' dosyasına GÜNCELLENDİ.")
            return True
        except Exception as e:
            logger.error(f"JSON kayıt hatası: {e}")
            return False


class SystemUpdater:
    def __init__(self):
        self.domain_fetcher = DomainFetcher()
        
    def update_base_url(self, new_domain: str):
        if not Config.INDEX_HTML_PATH.exists():
            logger.error("index.html dosyası bulunamadı!")
            return False
            
        try:
            with open(Config.INDEX_HTML_PATH, 'r', encoding=Config.ENCODING) as f:
                content = f.read()
                
            updated_content = Config.BASE_URL_PATTERN.sub(rf'\g<1>{new_domain}\g<3>', content)
            
            with open(Config.INDEX_HTML_PATH, 'w', encoding=Config.ENCODING) as f:
                f.write(updated_content)
            
            logger.info(f"index.html içindeki Domain adresi güncellendi: {new_domain}")
            return True
        except Exception as e:
            logger.error(f"index.html işlenirken hata oluştu: {e}")
            return False

    def run(self):
        new_domain = self.domain_fetcher.fetch()
        self.update_base_url(new_domain)
        match_fetcher = MatchFetcher(current_domain=new_domain)
        match_fetcher.fetch_and_save()


if __name__ == "__main__":
    logger.info("PLAYER TV YENİ NESİL BOT AKTİF EDİLİYOR...")
    updater = SystemUpdater()
    updater.run()
    logger.info("Bot işlemleri sonlandı.")
