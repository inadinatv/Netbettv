import re
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    """Uygulama yapılandırma sabitleri."""
    INDEX_HTML_PATH = Path('index.html')
    MATCHES_JSON_PATH = Path('matches.json')
    ENCODING = 'utf-8'
    
    # HTML içerisindeki Base URL satırını güncellemek için Regex
    BASE_URL_PATTERN = re.compile(
        r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)'
    )
    
    DEFAULT_DOMAIN = "https://fixbettv84.com/"
    MASTER_URL = "https://t.me/s/fixbet"


class DomainFetcher:
    """Telegram üzerinden güncel yayın linkini çeker."""
    def __init__(self, master_url: str = Config.MASTER_URL):
        self.master_url = master_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def fetch(self) -> str:
        try:
            response = self.session.get(self.master_url, timeout=10)
            response.raise_for_status()
            
            current_url = Config.DEFAULT_DOMAIN
            # Telegram kanalında paylaşılan güncel fixbettv linkini ara
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
    """Maçları çeker ve JSON dosyasına kaydeder."""
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self.matches_url = "https://data-reality.com/matches2.php"
    
    def fetch_and_save(self) -> bool:
        try:
            response = self.session.get(self.matches_url, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            matches = []
            
            # API'den HTML parçalarını yakalayıp düzgün listeye dök
            for link in soup.find_all('a', class_='channel-item'):
                if 'style' in link.attrs and 'display:none' in link['style']:
                    continue
                    
                channel_name_div = link.find('div', class_='channel-name')
                status_div = link.find('div', class_='channel-status')
                
                if channel_name_div and status_div:
                    match_title = channel_name_div.get_text(strip=True)
                    match_status = status_div.get_text(strip=True)
                    
                    href = link.get('href', '')
                    channel_id = href.split('id=')[1] if 'id=' in href else ''
                    
                    time_part = match_status.split('|')[0].strip() if '|' in match_status else match_status
                    type_part = match_status.split('|')[1].strip() if '|' in match_status else 'Maç'
                    
                    matches.append({
                        'time': time_part,
                        'title': match_title,
                        'type': type_part,
                        'channel_id': channel_id
                    })
            
            # Verileri JSON dosyasına kaydet
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump(matches, f, ensure_ascii=False, indent=4)
            
            logger.info(f"Maç bilgileri başarıyla {Config.MATCHES_JSON_PATH.name} dosyasına kaydedildi. ({len(matches)} maç)")
            return True
            
        except Exception as e:
            logger.error(f"Maçlar çekilirken hata oluştu: {e}")
            return False


class SystemUpdater:
    def __init__(self):
        self.domain_fetcher = DomainFetcher()
        self.match_fetcher = MatchFetcher()
        
    def update_base_url(self, new_domain: str):
        if not Config.INDEX_HTML_PATH.exists():
            logger.error("index.html dosyası bulunamadı!")
            return False
            
        with open(Config.INDEX_HTML_PATH, 'r', encoding=Config.ENCODING) as f:
            content = f.read()
            
        updated_content = Config.BASE_URL_PATTERN.sub(rf'\g<1>{new_domain}\g<3>', content)
        
        with open(Config.INDEX_HTML_PATH, 'w', encoding=Config.ENCODING) as f:
            f.write(updated_content)
        
        logger.info(f"index.html içindeki BASE_URL başarıyla güncellendi.")
        return True

    def run(self):
        # 1. Domain bul ve index.html'i güncelle
        new_domain = self.domain_fetcher.fetch()
        self.update_base_url(new_domain)
        
        # 2. Maçları çek ve matches.json olarak kaydet
        self.match_fetcher.fetch_and_save()

if __name__ == "__main__":
    logger.info("Player TV Güncelleme Sistemi başlatılıyor...")
    updater = SystemUpdater()
    updater.run()
    logger.info("✓ Tüm işlemler tamamlandı.")
