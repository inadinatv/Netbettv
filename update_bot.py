import re
import json
import logging
from pathlib import Path
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

# Logging ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    INDEX_HTML_PATH = Path('index.html')
    MATCHES_JSON_PATH = Path('matches.json')
    ENCODING = 'utf-8'
    BASE_URL_PATTERN = re.compile(r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)')
    DEFAULT_DOMAIN = "https://fixbettv84.com/"
    MASTER_URL = "https://t.me/s/fixbet"


class DomainFetcher:
    def __init__(self, master_url: str = Config.MASTER_URL):
        self.master_url = master_url
        self.session = requests.Session()
        # Gerçek bir tarayıcı taklidi (Cloudflare aşmak için)
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Upgrade-Insecure-Requests': '1'
        })
    
    def fetch(self) -> str:
        try:
            response = self.session.get(self.master_url, timeout=10)
            response.raise_for_status()
            current_url = Config.DEFAULT_DOMAIN
            found_urls = re.findall(r'https?://(?:www\.)?[a-zA-Z0-9-]*fixbettv[0-9]*\.[a-zA-Z]+/?', response.text)
            
            if found_urls:
                unique_urls = list(dict.fromkeys(found_urls))
                current_url = unique_urls[-1]
            
            if not current_url.endswith('/'):
                current_url += '/'
            
            logger.info(f"Güncel domain tespit edildi: {current_url}")
            return current_url
        except Exception as e:
            logger.error(f"Domain çekilirken hata: {e}. Varsayılan kullanılacak.")
            return Config.DEFAULT_DOMAIN


class MatchFetcher:
    def __init__(self, current_domain: str):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none'
        })
        self.current_domain = current_domain
        self.sources = [
            "https://data-reality.com/matches2.php",
            self.current_domain
        ]

    def _smart_extract_matches(self, html_content: str) -> List[Dict]:
        matches = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 1. STANDART HTML KAZIMA (Genişletilmiş Regex ile)
        possible_elements = soup.find_all(['a', 'div', 'li'])
        for el in possible_elements:
            href = el.get('href', '') if el.name == 'a' else ''
            style = el.get('style', '').replace(' ', '').lower()
            if 'display:none' in style:
                continue

            full_text = el.get_text(separator=' | ', strip=True)
            if not full_text:
                continue

            # Saat formatı (21:00 veya 21.00) içeriyorsa maç olma ihtimali yüksektir
            time_match = re.search(r'\d{2}[:.]\d{2}', full_text)
            if not time_match:
                continue

            title = ""
            status = ""

            name_div = el.find(class_=re.compile(r'name|title|team|mac|takim', re.I))
            status_div = el.find(class_=re.compile(r'status|time|info|league|saat|lig', re.I))
            
            if name_div: title = name_div.get_text(separator=' ', strip=True)
            if status_div: status = status_div.get_text(separator=' ', strip=True)

            if not title or len(title) < 3:
                texts = [t for t in el.stripped_strings if t]
                if len(texts) >= 2:
                    time_str = next((t for t in texts if re.search(r'\d{2}[:.]\d{2}', t)), None)
                    # '-' veya 'vs' veya 'v' arama
                    title_candidates = [t for t in texts if '-' in t or ' vs ' in t.lower() or ' v ' in t.lower()]
                    title_str = title_candidates[0] if title_candidates else texts[0]
                    
                    if title_str:
                        title = title_str
                        other_texts = [t for t in texts if t != title_str and t != time_str]
                        league_str = other_texts[0] if other_texts else "Futbol / Basketbol"
                        status = f"{time_str} | {league_str}" if time_str else league_str

            # Hala takımları belirleyemediysek atla
            if not title or len(title) < 5:
                continue

            # ID Ayıklama
            channel_id = ""
            if href:
                match_id = re.search(r'(id=|channel=|yayin=|watch=|kanal=)([^&]+)', href)
                if match_id:
                    channel_id = match_id.group(2)
                else:
                    parts = [p for p in href.split('/') if p]
                    if parts:
                        channel_id = parts[-1]

            time_part = status.split('|')[0].strip() if '|' in status else status
            type_part = status.split('|')[1].strip() if '|' in status else 'Maç'

            match_time_in_title = re.search(r'^(\d{2}[:.]\d{2})', title)
            if match_time_in_title:
                time_part = match_time_in_title.group(1)
                title = title.replace(time_part, '').strip(' -|')

            if not re.search(r'\d{2}[:.]\d{2}', time_part) and time_match:
                time_part = time_match.group(0)

            # Liste kontrolü (Aynı maçı iki kez eklememek için)
            if not any(m['title'] == title and m['time'] == time_part for m in matches):
                matches.append({
                    'time': time_part,
                    'title': title,
                    'type': type_part,
                    'channel_id': channel_id
                })
        
        # 2. JSON JAVASCRIPT İÇİ ARAMA (Eğer maçları HTML yerine sayfaya kod olarak gizledilerse)
        if not matches:
            script_tags = soup.find_all('script')
            for script in script_tags:
                if script.string:
                    # 'id', 'title', 'time' gibi verilerin geçtiği JSON yapısı ara
                    if 'id=' in script.string or 'channel' in script.string:
                        # Burada karmaşık JSON ayıklamaları yapılabilir.
                        # Şimdilik standart HTML tarafı başarısız olursa Cloudflare engelini bildirelim.
                        pass
        
        return matches

    def fetch_and_save(self) -> bool:
        matches = []
        for url in self.sources:
            try:
                logger.info(f"Maçlar Aranıyor -> {url}")
                response = self.session.get(url, timeout=12)
                
                if "Just a moment..." in response.text or "Cloudflare" in response.text:
                    logger.warning(f"[DİKKAT] {url} Cloudflare koruması altında! Bot engelleniyor.")
                    continue
                    
                response.raise_for_status()
                parsed_matches = self._smart_extract_matches(response.text)
                
                if parsed_matches:
                    matches = parsed_matches
                    logger.info(f"Başarılı! {url} üzerinden {len(matches)} adet maç tespit edildi.")
                    break
                else:
                    logger.warning(f"Uyarı: {url} adresinde maç bulunamadı.")
            except Exception as e:
                logger.error(f"{url} ulaşılamadı: {e}")

        if not matches:
            logger.error("HİÇBİR KAYNAKTAN MAÇ VERİSİ ALINAMADI! (Muhtemel sebep: Cloudflare Bot Koruması veya Sitenin HTML yapısının tamamen JS'ye dönmesi)")
            return False
            
        try:
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump(matches, f, ensure_ascii=False, indent=4)
            logger.info(f"Tüm maç verileri '{Config.MATCHES_JSON_PATH.name}' dosyasına güncellendi.")
            return True
        except Exception as e:
            logger.error(f"JSON kayıt hatası: {e}")
            return False


class SystemUpdater:
    def __init__(self):
        self.domain_fetcher = DomainFetcher()
        
    def update_base_url(self, new_domain: str):
        if not Config.INDEX_HTML_PATH.exists():
            logger.error("index.html dosyası klasörde bulunamadı!")
            return False
            
        try:
            with open(Config.INDEX_HTML_PATH, 'r', encoding=Config.ENCODING) as f:
                content = f.read()
                
            updated_content = Config.BASE_URL_PATTERN.sub(rf'\g<1>{new_domain}\g<3>', content)
            
            with open(Config.INDEX_HTML_PATH, 'w', encoding=Config.ENCODING) as f:
                f.write(updated_content)
            
            logger.info(f"index.html içindeki Domain adresi ({new_domain}) ile değiştirildi.")
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
