import re
import json
import logging
from pathlib import Path
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

# Logging ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class Config:
    INDEX_HTML_PATH = Path('index.html')
    MATCHES_JSON_PATH = Path('matches.json')
    ENCODING = 'utf-8'
    
    # HTML içerisindeki Base URL satırını güncellemek için Regex
    BASE_URL_PATTERN = re.compile(r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)')
    
    DEFAULT_DOMAIN = "https://fixbettv84.com/"
    MASTER_URL = "https://t.me/s/fixbet"


class DomainFetcher:
    """Telegram üzerinden güncel yayın linkini çeker."""
    def __init__(self, master_url: str = Config.MASTER_URL):
        self.master_url = master_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
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
    """Maçları çeken ve tasarımsal değişikliklerden etkilenmeyen zeki sınıf."""
    def __init__(self, current_domain: str):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        self.current_domain = current_domain
        
        # Hedef siteler. İlki bozulursa bot doğrudan 2. adrese gidip aramaya başlar.
        self.sources = [
            "https://data-reality.com/matches2.php",
            self.current_domain
        ]

    def _smart_extract_matches(self, html_content: str) -> List[Dict]:
        """Sitenin HTML tasarımı (class isimleri vs) değişse bile veriyi ayıklayabilen Zeki Analiz Sistemi"""
        soup = BeautifulSoup(html_content, 'html.parser')
        matches = []
        
        # A, DIV veya LI etiketlerini dolaşıyoruz
        possible_elements = soup.find_all(['a', 'div', 'li'])
        
        for el in possible_elements:
            href = el.get('href', '') if el.name == 'a' else ''
            
            # CSS ile gizlenmiş elementleri (display:none) okuma
            style = el.get('style', '').replace(' ', '').lower()
            if 'display:none' in style:
                continue

            full_text = el.get_text(separator=' | ', strip=True)
            if not full_text:
                continue

            # Eğer metnin içerisinde saat (ör: 21:00) veya takımlar (- / vs) yoksa, o elemanı atla
            if not re.search(r'\d{2}:\d{2}', full_text) and not ('-' in full_text or 'vs' in full_text.lower()):
                continue

            title = ""
            status = ""

            # 1. YÖNTEM: Olası class isimlerine göre veri arama
            name_div = el.find(class_=re.compile(r'name|title|team|mac-adi|takim', re.I))
            status_div = el.find(class_=re.compile(r'status|time|info|league|saat|lig', re.I))
            
            if name_div:
                title = name_div.get_text(separator=' ', strip=True)
            if status_div:
                status = status_div.get_text(separator=' ', strip=True)

            # 2. YÖNTEM (YEDEK): Class isimleri tamamen değişmişse Regex (Metin Analizi) ile ayıkla
            if not title or len(title) < 3:
                texts = list(el.stripped_strings)
                if len(texts) >= 2:
                    # İçinde saat barındıran parçayı bul
                    time_str = next((t for t in texts if re.search(r'\d{2}:\d{2}', t)), None)
                    # İçinde - veya vs olan parçayı takım ismi kabul et
                    title_candidates = [t for t in texts if '-' in t or ' vs ' in t.lower()]
                    
                    title_str = title_candidates[0] if title_candidates else texts[0]
                    
                    if title_str:
                        title = title_str
                        other_texts = [t for t in texts if t != title_str and t != time_str]
                        league_str = other_texts[0] if other_texts else "Futbol / Basketbol"
                        
                        if time_str:
                            status = f"{time_str} | {league_str}"
                        else:
                            status = league_str

            # Son kontrol: Hala mantıklı bir maç bulunamadıysa geç
            if not title or ('-' not in title and 'vs' not in title.lower()):
                continue

            # 3. YÖNTEM: Kanal Kimliği (ID) Ayıklama
            channel_id = ""
            if href:
                match_id = re.search(r'(id=|channel=|yayin=|watch=|kanal=)([^&]+)', href)
                if match_id:
                    channel_id = match_id.group(2)
                else:
                    # Örn: site.com/bein-sports-1 yapısı
                    parts = [p for p in href.split('/') if p]
                    if parts:
                        channel_id = parts[-1]

            # Son Düzenlemeler
            time_part = status.split('|')[0].strip() if '|' in status else status
            type_part = status.split('|')[1].strip() if '|' in status else 'Maç'

            # Eğer title (isim) içinde saat kalmışsa onu time_part yap ("21:00 Galatasaray - Fenerbahçe" gibi)
            match_time_in_title = re.search(r'^(\d{2}:\d{2})', title)
            if match_time_in_title:
                time_part = match_time_in_title.group(1)
                title = title.replace(time_part, '').strip(' -|')

            # Zaman gerçekten saat formatında değilse tüm string'i tara
            if not re.search(r'\d{2}:\d{2}', time_part):
                match_time_in_text = re.search(r'\d{2}:\d{2}', full_text)
                if match_time_in_text:
                    time_part = match_time_in_text.group(0)

            # Çift kopyaları engelle
            if not any(m['title'] == title and m['time'] == time_part for m in matches):
                matches.append({
                    'time': time_part,
                    'title': title,
                    'type': type_part,
                    'channel_id': channel_id
                })

        return matches

    def fetch_and_save(self) -> bool:
        matches = []
        
        for url in self.sources:
            try:
                logger.info(f"Maçlar Aranıyor -> {url}")
                response = self.session.get(url, timeout=12)
                response.raise_for_status()
                
                parsed_matches = self._smart_extract_matches(response.text)
                if parsed_matches:
                    matches = parsed_matches
                    logger.info(f"Başarılı! {url} üzerinden {len(matches)} adet maç tespit edildi.")
                    break # Bir adresten bulduysa diğerine gitmesine gerek yok
                else:
                    logger.warning(f"Uyarı: {url} adresinde maç kalıbı bulunamadı, bir sonraki adrese geçiliyor...")
            except Exception as e:
                logger.error(f"{url} ulaşılamadı: {e}")

        if not matches:
            logger.error("HİÇBİR KAYNAKTAN MAÇ VERİSİ ALINAMADI! Kaynak sitenin yayın düzeni tümden değişmiş olabilir.")
            return False
            
        try:
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump(matches, f, ensure_ascii=False, indent=4)
            logger.info(f"Tüm maç verileri '{Config.MATCHES_JSON_PATH.name}' olarak kaydedildi.")
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
        # 1. En güncel domain adresini Telegram vb.'den al
        new_domain = self.domain_fetcher.fetch()
        
        # 2. Aldığın domaini HTML'e kaydet
        self.update_base_url(new_domain)
        
        # 3. Zeki maç arama sistemini güncel domain ile çalıştırıp JSON'u yazdır
        match_fetcher = MatchFetcher(current_domain=new_domain)
        match_fetcher.fetch_and_save()


if __name__ == "__main__":
    logger.info("PLAYER TV YENİ NESİL BOT AKTİF EDİLİYOR...")
    updater = SystemUpdater()
    updater.run()
    logger.info("Bot işlemleri sonlandı.")
