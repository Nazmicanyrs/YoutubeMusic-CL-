# YouTube Music CLI Player 🎵

Python kullanılarak tamamen sıfırdan geliştirilmiş, YouTube Music'ten doğrudan terminalinizde (komut satırından) şarkı arayıp çalabileceğiniz zengin arayüzlü ve tam kontrollü bir medya oynatıcıdır.

> **NOT:** Bu proje **HİÇBİR Google API Anahtarına (API Key) İHTİYAÇ DUYMAZ!** Tamamen `ytmusicapi` (açık YouTube Müzik endpointlerini okur) ve `yt-dlp` arka planları kullanılarak tasarlanmıştır. Güvenle klonlayıp hemen çalıştırabilirsiniz.

## Özellikler

- 🎨 **Zengin Arayüz:** Modern kutulu (`rich`) ve çok renkli kullanım.
- 🖼️ **ASCII Kapak Resmi:** Dinlediğiniz şarkının albüm kapağı gerçek zamanlı indirilip renkli ASCII sanatına dönüştürülür.
- 🎵 **Veri Akışı (Streaming):** Şarkıyı direkt indirmek veya depolamak yerine yüksek ses kalitesi ile canlı yayın üzerinden anında oynatır.
- ⌨️ **Klavye Kısayolları:**
  - `Boşluk (Space)`: Seçili şarkıyı durdur/başlat.
  - `+` / `-` veya `K`/`J`: Sesi arttır/azalt.
  - `Yön Tuşları (Aşağı/Yukarı)`: Pano/Kuyruk içi kaydırma (Scroll).
  - `N`: Sonraki Şarkı.
  - `P`: Çalma Listesine Ekle.
  - `Q` veya `B`: Geri Dön veya Kapat.
## İhtiyaçlar

- Python 3.8+
- [VLC Media Player (64-bit)](https://www.videolan.org/) (*Arka plan oynatıcısı için zorunludur.*)

## Kurulum ve Çalıştırma

Terminal veya CMD açarak projeyi klonlayın ve bağımlılıklarını kurun:

```bash
# Projeyi indirin
git clone https://github.com/KULLANICI_ADINIZ/ytm-cli.git
cd ytm-cli

# Python sanal ortamını oluşturun ve aktif edin
python -m venv venv
# Windows için:
.\venv\Scripts\activate.bat
# MacOS / Linux için:
# source venv/bin/activate

# Gerekli Paketleri Kurun
pip install -r requirements.txt
```

### Başlatma

```bash
python main.py
```
*(Yalnızca Windows Kullanıcıları için: Hiç komut yazmadan sadece klasördeki `run.bat` dosyasına tıklayarak da başlatabilirsiniz.)*
