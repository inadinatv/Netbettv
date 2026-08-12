import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# 1. GÜNCEL DOMAİNİ BULMA
def get_current_domain():
    # NOT: Bu tür siteler genelde adres değiştirir (83 -> 84 gibi).
    # Eğer sitenin sabit bir yönlendirme linki (örneğin Twitter biosundaki link) varsa
    # buraya onu yazmalısın. Bot o linke gidip yönlendirildiği son adresi alacaktır.
    master_url = "https://t.me/s/fixbet" # Örnek telegram kanalı veya master yönlendirici link
    
    try:
        # Örnek mantık: Yönlendirmeyi takip et
        # response = requests.get(master_url, allow_redirects=True)
        # current_url = response.url
        
        # Şimdilik varsayılan olarak bir URL dönüyoruz. 
        # Gerçek senaryoda üstteki request mantığını sitenin yapısına göre uyarlamalısın.
        current_url = "https://fixbettv84.com/" 
        
        if not current_url.endswith('/'):
            current_url += '/'
        return current_url
    except Exception as e:
        print(f"Domain çekilirken hata: {e}")
        return None

# 2. GÜNÜN MAÇLARINI ÇEKME
def get_daily_matches():
    try:
        # Örnek olarak tff, mackolik veya ücretsiz bir spor apisinden veri çekilebilir.
        # Burada basitçe örnek bir veri yapısı oluşturuyoruz.
        # Web scraping (BeautifulSoup) ile bir iddaa/spor sitesinden maçlar çekilebilir.
        
        # Gerçek bir senaryo örneği (Örnek site URL'si):
        # res = requests.get("https://www.sporx.com/tv-rehberi")
        # soup = BeautifulSoup(res.text, 'html.parser')
        # maçları soup.find_all() ile çek...
        
        # Şimdilik örnek HTML döndürüyoruz:
        today = datetime.now().strftime("%d.%m.%Y")
        html_content = f"""
<section class="toolbar" style="margin-bottom: 20px; display: block;">
    <h3 style="color: var(--cyan); margin-bottom: 10px; font-size: 1rem;">📅 Günün Öne Çıkan Maçları ({today})</h3>
    <ul style="list-style: none; font-size: 0.85rem; color: var(--text); line-height: 1.8;">
        <li>⚽ 19:00 - Galatasaray vs Fenerbahçe (Bein Sports 1)</li>
        <li>⚽ 21:45 - Real Madrid vs Barcelona (S Sport)</li>
        <li>🏀 22:00 - Anadolu Efes vs Panathinaikos (Smart Spor)</li>
    </ul>
</section>
"""
        return html_content
    except Exception as e:
        print(f"Maçlar çekilirken hata: {e}")
        return None

# 3. HTML DOSYASINI GÜNCELLEME
def update_html():
    with open('index.html', 'r', encoding='utf-8') as file:
        content = file.read()

    # Domain Güncelleme
    new_domain = get_current_domain()
    if new_domain:
        # Regex ile BASE_URL satırını bul ve değiştir
        content = re.sub(
            r'(// BASE_URL_START\nconst BASE_URL=")(.*?)(";)',
            rf'\g<1>{new_domain}\g<3>',
            content
        )
        print(f"Yeni domain ayarlandı: {new_domain}")

    # Maçları Güncelleme
    new_matches = get_daily_matches()
    if new_matches:
        # Regex ile yorum satırları arasını değiştir
        content = re.sub(
            r'(<!-- GUNUN_MACLARI_BASLANGIC -->).*?(<!-- GUNUN_MACLARI_BITIS -->)',
            rf'\1\n{new_matches}\n\2',
            content,
            flags=re.DOTALL
        )
        print("Günün maçları güncellendi.")

    with open('index.html', 'w', encoding='utf-8') as file:
        file.write(content)

if __name__ == "__main__":
    update_html()
