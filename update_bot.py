import re
import json
import logging
from pathlib import Path
from typing import List, Dict
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# Logging ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    INDEX_HTML_PATH = Path('index.html')
    MATCHES_JSON_PATH = Path('matches.json')
    DEBUG_HTML_PATH = Path('debug_html.txt')
    ENCODING = 'utf-8'
    
    BASE_URL_PATTERN = re.compile(r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)')
    DEFAULT_DOMAIN = "https://fixbettv84.com/"
    MASTER_URL = "https://t.me/s/fixbet"

class DomainFetcher:
    def __init__(self, master_url: str = Config.MASTER_URL):
        self.master_url = master_url

    def fetch(self) -> str:
        try:
            with sync_playwright() as p:
                # Tarayıcıyı gizli modda aç
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                page.goto(self.master_url, wait_until="networkidle", timeout=30000)
                html = page.content()
                browser.close()
                
                current_url = Config.DEFAULT_DOMAIN
                # Telegram'dan güncel fixbettv linkini bul
                found_urls = re.findall(r'https?://(?:www\.)?[a-zA-Z0-9-]*fixbettv[0-9]*\.[a-zA-Z]+/?', html)
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

    def _smart_extract_matches(self, html_content: str) -> List[Dict]:
        matches = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 1. ÖNCELİK: Sitedeki özel maç kartlarını arıyoruz
        # Genelde bu tarz sitelerde maçlar şu class'larla olur: match-item, match-card, fixture vb.
        # Aşağıdaki seçicileri site yapısına göre genişlettik.
        selectors = [
            'a[href*="watch"]', 'a[href*="izle"]', 'a[href*="mac"]', 
            'a[href*="channel"]', 'a[href*="kanal"]', 'li', '.match-item', '.fixture'
        ]
        
        elements = []
        for selector in selectors:
            found = soup.select(selector)
            if found:
                elements.extend(found)
        
        if not elements:
            # Eğer seçiciler bulamadıysa TÜM linkleri tara
            elements = soup.find_all('a', href=True)

        for elem in elements:
            if not isinstance(elem, dict) and not hasattr(elem, 'name'):
                continue
                
            text = elem.get_text(separator=' ', strip=True)
            
            # Saat formatı var mı? (19:00, 21.45 vb.)
            time_match = re.search(r'\b([01]?[0-9]|2[0-3])[:.]([0-5][0-9])\b', text)
            if not time_match:
                continue
                
            href = elem.get('href', '')
            if not href: continue
            
            # Kanal ID'sini bulma mantığı
            channel_id = ""
            id_match = re.search(r'(?:id=|kanal=|channel=|yayin=|watch=|/izle/)([-a-zA-Z0-9_]+)', href)
            
            if id_match:
                channel_id = id_match.group(1)
            else:
                parts = [p for p in href.split('/') if p and not p.startswith('#')]
                if parts:
                    channel_id = parts[-1]
            
            # onclick içinde olabilir
            if not channel_id or channel_id in ['#', 'javascript:void(0)']:
                onclick = elem.get('onclick', '')
                click_match = re.search(r'[\'"]([a-zA-Z0-9_-]+)[\'"]', onclick)
                if click_match:
                    channel_id = click_match.group(1)
            
            if not channel_id:
                continue

            time_str = time_match.group(0)
            raw_title = text.replace(time_str, '').strip(' -|/>')
            
            league = "Maç"
            title = raw_title
            
            league_match = re.search(r'(.*?)(Süper Lig|Lig|Kupa|Premier|La Liga|Serie A|Ligue 1|NBA|Euroleague|Champions|Şampiyonlar)(.*)', raw_title, re.IGNORECASE)
            if league_match:
                league = (league_match.group(2) + league_match.group(3)).strip(' -|')
                title = league_match.group(1).strip(' -|')
                
            if not title:
                title = raw_title

            if len(title) < 5:
                continue

            # Duplicate kontrolü
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
        
        try:
            logger.info(f"Tarayıcı ile siteye bağlanılıyor: {self.current_domain}")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = context.new_page()
                
                # Siteyi yükle ve JavaScript'in bitmesini bekle
                page.goto(self.current_domain, wait_until="networkidle", timeout=45000)
                
                # Ekstra güvenlik: Sayfanın yüklenmesi için 2 saniye daha bekle
                page.wait_for_timeout(2000)
                
                # Debug için HTML'i kaydet
                html_content = page.content()
                with open(Config.DEBUG_HTML_PATH, 'w', encoding=Config.ENCODING) as f:
                    f.write(html_content)
                logger.info(f"Render edilmiş HTML '{Config.DEBUG_HTML_PATH.name}' dosyasına kaydedildi.")

                # Maçları çek
                matches = self._smart_extract_matches(html_content)
                
                if matches:
                    logger.info(f"BAŞARILI! {len(matches)} adet maç bulundu.")
                else:
                    logger.warning(f"Uyarı: Sitede saat formatına uyan maç bilgisi bulunamadı. (debug_html.txt dosyasını kontrol et)")
                
                browser.close()

        except Exception as e:
            logger.error(f"Site taranırken hata oluştu: {e}")

        if not matches:
            logger.error("HİÇBİR KAYNAKTAN MAÇ VERİSİ ALINAMADI! (debug_html.txt dosyasını kontrol edin, site tasarımı tamamen değişmiş olabilir.)")
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
