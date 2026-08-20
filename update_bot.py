import re
import json
import logging
import random
from pathlib import Path
from typing import List, Dict
from bs4 import BeautifulSoup

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    import requests
    HAS_CLOUDSCRAPER = False

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
        if HAS_CLOUDSCRAPER:
            self.scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
        else:
            self.scraper = requests.Session()
    
    def fetch(self) -> str:
        try:
            response = self.scraper.get(self.master_url, timeout=20)
            current_url = Config.DEFAULT_DOMAIN
            
            found_urls = re.findall(r'https?://(?:www\.)?[a-zA-Z0-9-]*fixbettv[0-9]*\.[a-zA-Z]+/?', response.text)
            if found_urls:
                unique_urls = list(dict.fromkeys(found_urls))
                current_url = unique_urls[-1]
            
            if not current_url.endswith('/'):
                current_url += '/'
            
            logger.info(f"Güncel domain: {current_url}")
            return current_url
        except Exception as e:
            logger.error(f"Domain hatası: {e}. Varsayılan kullanılacak.")
            return Config.DEFAULT_DOMAIN

class MatchFetcher:
    def __init__(self, current_domain: str):
        self.current_domain = current_domain
        if HAS_CLOUDSCRAPER:
            self.scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
        else:
            self.scraper = requests.Session()
            
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        
        self.sources = [
            self.current_domain,
            f"{self.current_domain}mac",
            f"{self.current_domain}canli",
            f"{self.current_domain}fikstur",
            f"{self.current_domain}matches",
            f"{self.current_domain}ajax/matches",
            f"{self.current_domain}api/matches",
            "https://data-reality.com/matches2.php"
        ]

    def _smart_extract_matches(self, html_content: str) -> List[Dict]:
        matches = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Önce script içinde JSON olarak maç var mı bak
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                json_match = re.search(r'(?:var|let|const)\s+(?:matches|maclar|fixtures|games)\s*=\s*(\[.*?\]);', script.string, re.DOTALL)
                if json_match:
                    try:
                        json_matches = json.loads(json_match.group(1))
                        if isinstance(json_matches, list):
                            for m in json_matches:
                                time_str = m.get('time', m.get('saat', m.get('hour', '')))
                                title = m.get('title', m.get('baslik', m.get('mac', m.get('match', ''))))
                                league = m.get('type', m.get('lig', m.get('league', 'Maç')))
                                channel_id = m.get('channel_id', m.get('kanal', m.get('id', '')))
                                
                                if time_str and title:
                                    matches.append({
                                        'time': str(time_str),
                                        'title': str(title),
                                        'type': str(league),
                                        'channel_id': str(channel_id)
                                    })
                            if matches:
                                logger.info("Maçlar JavaScript içinde JSON olarak bulundu!")
                                return matches
                    except:
                        pass

        # Linkleri tara
        for a_tag in soup.find_all('a', href=True):
            text = a_tag.get_text(separator=' ', strip=True)
            
            time_match = re.search(r'\b([01]?[0-9]|2[0-3])[:.]([0-5][0-9])\b', text)
            if not time_match:
                continue
                
            href = a_tag['href']
            
            channel_id = ""
            id_match = re.search(r'(?:id=|kanal=|channel=|yayin=|watch=|/izle/)([-a-zA-Z0-9_]+)', href)
            
            if id_match:
                channel_id = id_match.group(1)
            else:
                parts = [p for p in href.split('/') if p and not p.startswith('#')]
                if parts:
                    channel_id = parts[-1]
            
            if not channel_id or channel_id in ['#', 'javascript:void(0)']:
                onclick = a_tag.get('onclick', '')
                click_match = re.search(r'[\'"]([a-zA-Z0-9_-]+)[\'"]', onclick)
                if click_match:
                    channel_id = click_match.group(1)
            
            if not channel_id:
                continue

            time_str = time_match.group(0)
            
            # YENİ NESİL AYRIŞTIRMA: "Takım vs Takım 18:00 | Lig Adı" formatı
            raw_text = text.replace(time_str, '', 1).strip()
            
            title = ""
            league = "Maç"
            
            if '|' in raw_text:
                left, right = raw_text.split('|', 1)
                title = left.strip(' -–|·')
                league = right.strip(' -–|·') or "Maç"
            else:
                league_match = re.search(r'(.*?)(Süper Lig|Lig|Kupa|Premier|La Liga|Serie A|Ligue 1|NBA|Euroleague|Champions|Şampiyonlar|Oyunları|Play-Off)(.*)', raw_text, re.IGNORECASE)
                if league_match:
                    league = (league_match.group(2) + league_match.group(3)).strip(' -|')
                    title = league_match.group(1).strip(' -|')
                
            if not title:
                title = raw_text

            if len(title) < 3:
                continue

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
        
        self.scraper.headers.update({'User-Agent': random.choice(self.user_agents)})
        self.scraper.headers.update({'Referer': self.current_domain})
        
        for url in self.sources:
            try:
                logger.info(f"Maçlar Aranıyor -> {url}")
                response = self.scraper.get(url, timeout=20)
                
                if "Just a moment..." in response.text or "cf-browser-verification" in response.text:
                    logger.warning(f"[ENGEL] {url} Cloudflare korumasına takıldı!")
                    continue
                
                if not html_saved:
                    with open(Config.DEBUG_HTML_PATH, 'w', encoding=Config.ENCODING) as f:
                        f.write(response.text)
                    logger.info(f"HTML kaydedildi: '{Config.DEBUG_HTML_PATH.name}'")
                    html_saved = True

                parsed_matches = self._smart_extract_matches(response.text)
                
                if parsed_matches:
                    matches = parsed_matches
                    logger.info(f"BAŞARILI! {url} üzerinden {len(matches)} maç çekildi.")
                    break
                else:
                    logger.warning(f"{url} içinde maç bulunamadı.")
            except Exception as e:
                logger.error(f"{url} ulaşılamadı: {e}")

        if not matches:
            logger.error("HİÇBİR KAYNAKTAN MAÇ VERİSİ ALINAMADI!")
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump([], f, ensure_ascii=False, indent=4)
            return False
            
        try:
            with open(Config.MATCHES_JSON_PATH, 'w', encoding=Config.ENCODING) as f:
                json.dump(matches, f, ensure_ascii=False, indent=4)
            logger.info(f"Maçlar '{Config.MATCHES_JSON_PATH.name}' dosyasına kaydedildi.")
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
            
            logger.info(f"Domain güncellendi: {new_domain}")
            return True
        except Exception as e:
            logger.error(f"index.html hatası: {e}")
            return False

    def run(self):
        new_domain = self.domain_fetcher.fetch()
        self.update_base_url(new_domain)
        match_fetcher = MatchFetcher(current_domain=new_domain)
        match_fetcher.fetch_and_save()

if __name__ == "__main__":
    logger.info("BOT BAŞLATILIYOR...")
    updater = SystemUpdater()
    updater.run()
    logger.info("Bot bitti.")
