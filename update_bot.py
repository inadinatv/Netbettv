"""
Player TV - Canlı Yayın Merkezi Güncelleme Botu

Bu modül, Player TV web sitesinin domain ve günlük maç bilgilerini
otomatik olarak güncellemek için kullanılır.

Kullanım:
    python update_bot.py
    
Yapılandırma:
    config.yaml dosyasından özelleştirilebilir.
"""

import re
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
    ENCODING = 'utf-8'
    
    # Regex pattern'leri
    BASE_URL_PATTERN = re.compile(
        r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)'
    )
    MATCHES_PATTERN = re.compile(
        r'(<!-- GUNUN_MACLARI_BASLANGIC -->).*?(<!-- GUNUN_MACLARI_BITIS -->)',
        flags=re.DOTALL
    )
    STANDINGS_PATTERN = re.compile(
        r'(<!-- PUAN_DURUMU_BASLANGIC -->).*?(<!-- PUAN_DURUMU_BITIS -->)',
        flags=re.DOTALL
    )
    
    # Varsayılan değerler
    DEFAULT_DOMAIN = "https://fixbettv84.com/"
    MASTER_URL = "https://t.me/s/fixbet"


class DomainFetcher:
    """Domain bilgilerini çekmek için sınıf."""
    
    def __init__(self, master_url: str = Config.MASTER_URL):
        self.master_url = master_url
    
    def fetch(self) -> Optional[str]:
        """
        Güncel domain adresini çeker.
        
        Returns:
            Güncel domain URL'si veya None (hata durumunda)
        """
        try:
            # Gerçek senaryoda yönlendirmeyi takip etmek için:
            # response = requests.get(self.master_url, allow_redirects=True, timeout=10)
            # current_url = response.url
            
            # Şimdilik varsayılan domain dönülüyor
            current_url = Config.DEFAULT_DOMAIN
            
            # URL sonuna slash ekle
            if not current_url.endswith('/'):
                current_url += '/'
            
            logger.info(f"Güncel domain alındı: {current_url}")
            return current_url
            
        except requests.RequestException as e:
            logger.error(f"Domain çekilirken istek hatası: {e}")
            return None
        except Exception as e:
            logger.error(f"Domain çekilirken beklenmeyen hata: {e}")
            return None


class MatchFetcher:
    """Günlük maç bilgilerini çekmek için sınıf."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.matches_url = "https://data-reality.com/matches2.php"
        self.standings_url = "https://fixbettv84.com/puan.html"
    
    def fetch(self) -> Optional[str]:
        """
        Günün maç bilgilerini çeker ve HTML formatında döner.
        
        Returns:
            Maçların HTML gösterimi veya None (hata durumunda)
        """
        try:
            today = datetime.now().strftime("%d.%m.%Y")
            
            # fixbettv84.com API'sinden maç bilgilerini çek
            response = self.session.get(self.matches_url, timeout=10)
            response.raise_for_status()
            
            # API'den gelen HTML içeriğini parse et
            matches_html = self._parse_matches(response.text)
            
            if not matches_html.strip():
                # Eğer maç yoksa boş bir bölüm dön
                logger.info("Bugün için maç bilgisi bulunamadı.")
                return ""
            
            logger.info(f"Maç bilgileri başarıyla çekildi: {len(matches_html.split('<a href=')) - 1} maç")
            return matches_html
            
        except requests.RequestException as e:
            logger.error(f"Maçlar çekilirken istek hatası: {e}")
            return None
        except Exception as e:
            logger.error(f"Maçlar çekilirken beklenmeyen hata: {e}")
            return None
    
    def fetch_standings(self) -> Optional[str]:
        """
        Puan durumu bilgilerini çeker ve HTML formatında döner.
        
        Returns:
            Puan durumunun HTML gösterimi veya None (hata durumunda)
        """
        try:
            # fixbettv84.com API'sinden puan durumu bilgilerini çek
            response = self.session.get(self.standings_url, timeout=10)
            response.raise_for_status()
            
            # API'den gelen HTML içeriğini parse et
            standings_html = self._parse_standings(response.text)
            
            if not standings_html.strip():
                logger.info("Puan durumu bilgisi bulunamadı.")
                return ""
            
            logger.info("Puan durumu başarıyla çekildi.")
            return standings_html
            
        except requests.RequestException as e:
            logger.error(f"Puan durumu çekilirken istek hatası: {e}")
            return None
        except Exception as e:
            logger.error(f"Puan durumu çekilirken beklenmeyen hata: {e}")
            return None
    
    def _parse_matches(self, html_content: str, base_url: str = Config.DEFAULT_DOMAIN) -> str:
        """
        API'den gelen HTML içeriğini parse eder ve temizler.
        data-reality.com/matches2.php formatına uygun olarak parse eder.
        
        Args:
            html_content: API'den gelen ham HTML içeriği
            base_url: Temel URL adresi
            
        Returns:
            Temizlenmiş maç HTML'i (tıklanabilir linklerle)
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        matches = []
        
        # Örnek HTML formatına göre: div id="matches-tab" içindeki channel-item linklerini çek
        matches_tab = soup.find('div', id='matches-tab')
        if not matches_tab:
            # Eğer matches-tab yoksa tüm body'de ara
            matches_tab = soup
        
        for link in matches_tab.find_all('a', class_='channel-item'):
            # style="display:none;" olanları atla (gizli maçlar)
            if 'style' in link.attrs and 'display:none' in link['style']:
                continue
                
            channel_name_div = link.find('div', class_='channel-name')
            status_div = link.find('div', class_='channel-status')
            
            if channel_name_div and status_div:
                match_title = channel_name_div.get_text(strip=True)
                match_status = status_div.get_text(strip=True)
                
                # Kanal ID'sini al
                href = link.get('href', '')
                channel_id = href.split('id=')[1] if 'id=' in href else ''
                
                # Saat ve maç tipi bilgilerini ayır
                time_part = match_status.split('|')[0].strip() if '|' in match_status else match_status
                type_part = match_status.split('|')[1].strip() if '|' in match_status else 'Maç'
                
                matches.append({
                    'time': time_part,
                    'title': match_title,
                    'type': type_part,
                    'channel_id': channel_id
                })
        
        # HTML oluştur - tıklanabilir linklerle
        if not matches:
            return ""
        
        html_parts = [
            '<section class="toolbar" style="margin-bottom: 20px; display: block;">',
            f'    <h3 style="color: var(--cyan); margin-bottom: 10px; font-size: 1rem;">📅 Günün Maçları ({datetime.now().strftime("%d.%m.%Y")})</h3>',
            '    <ul style="list-style: none; font-size: 0.85rem; color: var(--text); line-height: 1.8;">'
        ]
        
        for match in matches:
            icon = "⚽" if "Hazırlık" in match['type'] or "Kupa" in match['type'] or "Lig" in match['type'] else "🏀"
            # Tıklanabilir link oluştur - channel_id ile
            if match['channel_id']:
                html_parts.append(
                    f'        <li><a href="{base_url}channel?id={match["channel_id"]}" target="_blank" rel="noopener" style="color: var(--text); text-decoration: none;">{icon} {match["time"]} | {match["title"]} ({match["type"]})</a></li>'
                )
            else:
                html_parts.append(
                    f'        <li>{icon} {match["time"]} | {match["title"]} ({match["type"]})</li>'
                )
        
        html_parts.extend([
            '    </ul>',
            '</section>'
        ])
        
        return '\n'.join(html_parts)
    
    def _parse_standings(self, html_content: str) -> str:
        """
        API'den gelen puan durumu HTML içeriğini parse eder.
        fixbettv84.com/puan.html JavaScript ile dinamik olarak tabloyu oluşturuyor,
        bu yüzden statik bir iframe ile gösteriyoruz.
        
        Args:
            html_content: API'den gelen ham HTML içeriği
            
        Returns:
            Iframe ile puan durumu HTML'i
        """
        # Puan durumu için iframe oluştur (JavaScript ile dinamik yüklendiği için)
        standings_html = '''
        <iframe frameborder="0" scrolling="no" width="100%" height="600" 
                src="https://fixbettv84.com/puan.html" 
                style="border: none; border-radius: 8px; background: transparent;">
        </iframe>
        '''
        return standings_html


class HTMLUpdater:
    """HTML dosyasını güncellemek için sınıf."""
    
    def __init__(
        self,
        file_path: Path = Config.INDEX_HTML_PATH,
        domain_fetcher: Optional[DomainFetcher] = None,
        match_fetcher: Optional[MatchFetcher] = None
    ):
        self.file_path = file_path
        self.domain_fetcher = domain_fetcher or DomainFetcher()
        self.match_fetcher = match_fetcher or MatchFetcher()
    
    def update(self) -> bool:
        """
        HTML dosyasını günceller.
        
        Returns:
            True (başarılı) veya False (hata durumunda)
        """
        if not self.file_path.exists():
            logger.error(f"Dosya bulunamadı: {self.file_path}")
            return False
        
        try:
            content = self._read_file()
            updates_made = []
            
            # Domain güncelleme
            new_domain = self.domain_fetcher.fetch()
            if new_domain:
                content = self._update_domain(content, new_domain)
                updates_made.append(f"Domain: {new_domain}")
            
            # Maç bilgilerini güncelleme
            new_matches = self.match_fetcher.fetch()
            if new_matches:
                content = self._update_matches(content, new_matches)
                updates_made.append("Maç bilgileri")
            
            # Puan durumunu güncelleme
            new_standings = self.match_fetcher.fetch_standings()
            if new_standings:
                content = self._update_standings(content, new_standings)
                updates_made.append("Puan durumu")
            
            if updates_made:
                self._write_file(content)
                logger.info(f"Güncellemeler tamamlandı: {', '.join(updates_made)}")
                return True
            else:
                logger.warning("Hiçbir güncelleme yapılamadı.")
                return False
                
        except Exception as e:
            logger.error(f"HTML güncellenirken hata: {e}")
            return False
    
    def _read_file(self) -> str:
        """Dosyayı okur ve içeriğini döner."""
        with open(self.file_path, 'r', encoding=Config.ENCODING) as f:
            return f.read()
    
    def _write_file(self, content: str) -> None:
        """İçeriği dosyaya yazar."""
        with open(self.file_path, 'w', encoding=Config.ENCODING) as f:
            f.write(content)
        logger.debug(f"Dosya yazıldı: {self.file_path}")
    
    def _update_domain(self, content: str, new_domain: str) -> str:
        """Domain bilgisini günceller."""
        updated_content = Config.BASE_URL_PATTERN.sub(
            rf'\g<1>{new_domain}\g<3>',
            content
        )
        if updated_content != content:
            logger.info(f"Yeni domain ayarlandı: {new_domain}")
        return updated_content
    
    def _update_matches(self, content: str, new_matches: str) -> str:
        """Maç bilgilerini günceller."""
        updated_content = Config.MATCHES_PATTERN.sub(
            rf'\1\n{new_matches}\n\2',
            content
        )
        if updated_content != content:
            logger.info("Günün maçları güncellendi.")
        return updated_content
    
    def _update_standings(self, content: str, new_standings: str) -> str:
        """Puan durumunu günceller."""
        # Puan durumu için özel HTML formatı oluştur
        standings_html = f'''
<!-- PUAN_DURUMU_BASLANGIC -->
<section class="toolbar" style="margin-bottom: 20px; display: block;">
    <button id="standingsToggle" onclick="document.getElementById('standingsContent').style.display = document.getElementById('standingsContent').style.display === 'none' ? 'block' : 'none'" style="width: 100%; padding: 12px; background: rgba(76, 244, 255, 0.1); border: 1px solid rgba(76, 244, 255, 0.3); border-radius: 12px; color: var(--cyan); font-weight: 700; cursor: pointer; font-size: 0.9rem;">📊 Puan Durumu</button>
    <div id="standingsContent" style="display: none; margin-top: 15px; overflow-x: auto;">
        {new_standings}
    </div>
</section>
<!-- PUAN_DURUMU_BITIS -->
'''
        updated_content = Config.STANDINGS_PATTERN.sub(
            standings_html.strip(),
            content
        )
        if updated_content != content:
            logger.info("Puan durumu güncellendi.")
        return updated_content


def main():
    """Ana giriş noktası."""
    logger.info("Player TV Güncelleme Botu başlatılıyor...")
    
    updater = HTMLUpdater()
    success = updater.update()
    
    if success:
        logger.info("✓ Güncelleme işlemi başarıyla tamamlandı.")
    else:
        logger.error("✗ Güncelleme işlemi başarısız oldu.")
    
    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
