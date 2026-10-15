# YouTube Music CLI Player 🎵

Python kullanılarak tamamen sıfırdan geliştirilmiş, YouTube Music'ten doğrudan terminalinizde (komut satırından) şarkı arayıp çalabileceğiniz zengin arayüzlü ve tam kontrollü bir medya oynatıcıdır.

> **NOT:** Bu proje **HİÇBİR Google API Anahtarına (API Key) İHTİYAÇ DUYMAZ!** Tamamen `ytmusicapi` (açık YouTube Müzik endpointlerini okur) ve `yt-dlp` arka planları kullanılarak tasarlanmıştır. Güvenle klonlayıp hemen çalıştırabilirsiniz.

> ⚠️ **Platform:** Uygulama şu an **yalnızca Windows** üzerinde çalışır (`msvcrt` klavye girişi ve `win11toast` bildirimleri nedeniyle).

## Özellikler

- 🎨 **Zengin Arayüz:** Modern kutulu (`rich`) ve çok renkli kullanım, hazır temalar veya **Kişisel Tema Editörü** ile kendi HEX renklerinizi tanımlama.
- 🖼️ **Gerçek Piksel Kapak Resmi:** Sixel destekli terminalde kapak, karakter bloklarına indirgenmeden görüntülenir. Kaynak kapak 1024×1024 olarak istenir ve ekrandaki alana göre ölçeklenir. Ekran güncellemeleri resmi tekrar tekrar silmez. Sixel olmayan terminallerde renkli blok görünümüne, `C` ile Retro Braille moduna geçilir.
- 📺 **Mini Player Modu:** Terminal penceresi küçüldüğünde veya `M` tuşuna basıldığında az yer kaplayan 3 satırlık kompakt kontrol şeridi.
- 🎵 **Veri Akışı (Streaming):** Şarkıyı indirmeden canlı akış üzerinden oynatır.
- 🎤 **Senkronize Şarkı Sözleri:** Karaoke tarzı, zamanlamalı söz gösterimi.
- 📂 **Çalma Listeleri:** Favoriler, özel listeler, karışık çalma, akıllı öneriler ve bulut paylaşımı.

### ⌨️ Oynatıcı Kısayolları

| Tuş | İşlev |
|---|---|
| `Boşluk (Space)` | Durdur / Devam |
| `N` | Sonraki şarkı |
| `B` | Önceki şarkı (şarkının 3. saniyesinden sonra: başa sar) |
| `M` | **Mini Player Modu** (Kompakt / Tam Ekran) |
| `C` | **Kapak Resmi Stili** (Gerçek Piksel / Blok yedeği <-> Retro Braille) |
| `←` / `→` | 5 sn geri / ileri sar |
| `↑` / `↓` (veya `Y` / `A`) | Kuyruğu kaydır |
| `+` / `-` (veya `K` / `J`) | Sesi arttır / azalt |
| `L` veya `F` | Favorilere ekle / çıkar |
| `P` | Çalma listesine ekle |
| `Q` veya `Esc` | Oynatıcıdan çık |

> **Global Kısayollar (oynatıcı açıkken, uygulama arka plandayken):** `Ctrl+Shift+Alt+Space` (Oynat/Durdur), `Ctrl+Shift+Alt+←/→` (Önceki/Sonraki), `Ctrl+Shift+Alt+↑/↓` (Ses), `Ctrl+Shift+Alt+L` (Favorile). Klavyenizdeki medya tuşları da desteklenir.

## İhtiyaçlar

- Windows 10/11
- Gerçek piksel kapak için **Windows Terminal 1.22+** (Sixel desteği). Eski konsollar ve bazı IDE terminalleri yalnızca karakter tabanlı kapak gösterebilir.
- Python **3.10+**
- [VLC Media Player (64-bit)](https://www.videolan.org/) (*Arka plan oynatıcısı için zorunludur.*)
- (Gerekirse) [Deno](https://deno.com/) — yt-dlp'nin güncel sürümleri YouTube için bir JavaScript çalışma zamanı isteyebilir. Şarkılar açılmıyorsa: `winget install DenoLand.Deno`

## Kurulum ve Çalıştırma

```bat
:: Projeyi indirin
git clone https://github.com/Nazmicanyrs/YoutubeMusic-CL-
cd YoutubeMusic-CL-

:: Python sanal ortamını oluşturun ve aktif edin
python -m venv venv
venv\Scripts\activate.bat

:: Gerekli paketleri kurun
pip install -r requirements.txt
```

### Başlatma

```bat
python main.py
```
*(Hiç komut yazmadan klasördeki `baslat.bat` dosyasına çift tıklayarak da başlatabilirsiniz. Windows Terminal varsa geniş pencerede açılır; sanal ortam varsa otomatik kullanılır.)*

### Kapak kalitesi

Oynatıcı başlığındaki **Gerçek Piksel / Sixel**, resmin gerçek piksel olarak çizildiğini gösterir. **Blok (Sixel yok)** görüyorsanız güncel Windows Terminal ile açın. `C` ile Braille modundan otomatik piksel moduna dönebilirsiniz. Küçük pencereye sığan kapak da küçük olur; daha fazla detay için pencereyi büyütün. Kaynak albüm görselindeki eksik detaylar yapay olarak üretilmez.

Sixel desteği ve yazı hücresinin piksel boyutu terminalden sorgulanır. Renk paleti 256 renktir; yüksek uzamsal çözünürlük, terminaldeki eski 32×32 blok çiziminden bağımsızdır. Terminal desteği: [Microsoft Windows Terminal 1.22 duyurusu](https://devblogs.microsoft.com/commandline/windows-terminal-preview-1-22-release/).

## Sorun Giderme

- **Şarkılar açılmıyor / "Şarkı açılamadı" hatası:** YouTube sık değiştiği için önce `pip install -U yt-dlp` çalıştırın. Hâlâ sorun varsa Deno'yu kurun (yukarıya bakın).
- **"VLC bulunamadı":** VLC'nin **64-bit** sürümünü kurun (Python 64-bit ise).
- **Hata ayrıntıları:** Uygulama klasöründeki `ytm-cl.log` dosyasına yazılır.

## Veri Dosyaları

Tüm kişisel veriler uygulama klasöründe saklanır (git'e eklenmez): `playlists.json`, `history.json`, `settings.json`.
Bir dosya bozulursa uygulama veriyi silmez; `*.corrupt-<zaman>.json` adıyla yedeğini alır ve sizi uyarır.

> ℹ️ Bulut paylaşımı listeleri herkese açık **dpaste.com** sitesine yükler; paylaşım kodunu bilen herkes listeyi görebilir.
