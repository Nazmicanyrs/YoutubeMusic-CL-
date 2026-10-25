# yt-music-cli 🎵

Python kullanılarak tamamen sıfırdan geliştirilmiş, YouTube Music'ten doğrudan terminalinizde (CLI) veya modern masaüstü arayüzünde (GUI) şarkı arayıp çalabileceğiniz zengin arayüzlü ve tam kontrollü bir medya oynatıcıdır.

> **NOT:** Bu proje **HİÇBİR Google API Anahtarına (API Key) İHTİYAÇ DUYMAZ!** Tamamen `ytmusicapi` (açık YouTube Müzik endpointlerini okur) ve `yt-dlp` arka planları kullanılarak tasarlanmıştır. Güvenle klonlayıp hemen çalıştırabilirsiniz.

> 🌐 **Çoklu Platform Desteği:** Uygulama **Windows**, **macOS** ve **Linux** işletim sistemleriyle tam uyumludur.

---

## Özellikler

- 🎨 **Gelişmiş TUI Dashboard & Zengin Arayüz:** Modern kutulu (`rich`) gösterge paneli, sistem rozetleri, anlık istatistikler ve görsel tema galerisi (Spotify, YouTube Music, Apple Music, Cyberpunk, Dracula, Nord Frost, Tokyo Night, Catppuccin, Winamp Retro, Matrix ve **Kişisel Tema Editörü**).
- 🖥️ **Masaüstü Grafik Arayüzü (GUI):** PyQt6 tabanlı, şarkı sözleri, mikrofonla sesli arama ve modern karanlık tema destekli masaüstü oynatıcı (`gui.py`).
- 🔍 **Zengin Tablolu Arama & Müzik Keşfi:** Arama geçmişi etiketleri, detaylı şarkı listesi tablosu, tek tıkla tümünü çalma, karıştırma ve akıllı radyo entegrasyonu.
- 🖼️ **Gerçek Piksel Kapak Resmi:** Sixel destekli terminallerde (Windows Terminal, iTerm2, WezTerm, Foot, Kitty vb.) kapak, karakter bloklarına indirgenmeden görüntülenir. Kaynak kapak 1024×1024 olarak istenir ve ekrandaki alana göre ölçeklenir. Sixel olmayan terminallerde renkli yarım blok görünümüne, `C` ile Retro Braille moduna geçilir.
- 🌊 **Dinamik Ses Spektrumu (Visualizer):** Çalan parçanın ritmine duyarlı çok frekanslı harmonik ekolayzer dalgaları ve tepe seviye göstergeleri.
- 📺 **Mini Player Modu:** Terminal penceresi küçüldüğünde veya `M` tuşuna basıldığında az yer kaplayan 3 satırlık kompakt kontrol şeridi.
- 🎵 **Veri Akışı (Streaming):** Şarkıyı indirmeden canlı akış üzerinden oynatır.
- 🎤 **Senkronize Şarkı Sözleri (Karaoke):** Zamanlamalı, parlayan aktif satır gösterimli karaoke söz modu.
- 📂 **Çalma Listeleri & Önizleme:** Şarkı sayısı, parça listesi önizleme tablosu, favoriler, özel listeler, karışık çalma, akıllı öneriler ve bulut paylaşımı.
- 🔔 **Yerel Sistem Bildirimleri:** Windows'ta Windows 11 bildirimleri, macOS'ta yerel Bildirim Merkezi (`osascript`), Linux'ta `notify-send`.

---

### ⌨️ Oynatıcı Kısayolları

| Tuş | İşlev |
|---|---|
| `Boşluk (Space)` | Durdur / Devam |
| `N` | Sonraki şarkı |
| `B` | Önceki şarkı (şarkının 3. saniyesinden sonra: başa sar) |
| `M` | **Mini Player Modu** (Kompakt / Tam Ekran) |
| `C` | **Kapak Resmi Stili** (Gerçek Piksel / Renkli Blok <-> Retro Braille) |
| `←` / `→` | 5 sn geri / ileri sar |
| `↑` / `↓` (veya `Y` / `A`) | Kuyruğu kaydır |
| `+` / `-` (veya `K` / `J`) | Sesi arttır / azalt |
| `L` veya `F` | Favorilere ekle / çıkar |
| `P` | Çalma listesine ekle |
| `Q` veya `Esc` | Oynatıcıdan çık |

> **Global Kısayollar (oynatıcı açıkken, uygulama arka plandayken):** `Ctrl+Shift+Alt+Space` (Oynat/Durdur), `Ctrl+Shift+Alt+←/→` (Önceki/Sonraki), `Ctrl+Shift+Alt+↑/↓` (Ses), `Ctrl+Shift+Alt+L` (Favorile). Klavyenizdeki medya tuşları da desteklenir.

---

## Kurulum Rehberleri

### 🍎 macOS (Apple Silicon M1/M2/M3/M4 & Intel)

1. **Sistem Gereksinimlerini Kurun (Homebrew ile):**
   ```bash
   # Homebrew yüklü değilse: https://brew.sh
   # VLC Media Player (ses motoru) ve ses/mikrofon bağımlılıklarını kurun:
   brew install --cask vlc
   brew install python@3.11 portaudio deno
   ```

2. **Depoyu Klonlayın ve Klasöre Geçin:**
   ```bash
   git clone https://github.com/Nazmicanyrs/YoutubeMusic-CL-.git
   cd YoutubeMusic-CL-
   ```

3. **Sanal Ortam (venv) Oluşturun ve Paketleri Yükleyin:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Çalıştırma:**
   ```bash
   # Terminal Arayüzü (CLI):
   ./baslat.sh
   # veya doğrudan:
   python3 main.py

   # Masaüstü Grafik Arayüzü (GUI):
   ./baslat_gui.sh
   # veya doğrudan:
   python3 gui.py
   ```
   *(Eğer izin hatası alırsanız: `chmod +x baslat.sh baslat_gui.sh` yapabilirsiniz.)*

---

### 🐧 Linux (Ubuntu / Debian / Arch / Fedora)

1. **Gerekli Sistem Paketlerini Kurun:**
   - **Ubuntu / Debian / Mint:**
     ```bash
     sudo apt update
     sudo apt install -y python3 python3-venv python3-pip vlc libvlc-dev libportaudio2 libasound2-dev libnotify-bin
     ```
   - **Arch Linux / Manjaro:**
     ```bash
     sudo pacman -S python vlc portaudio libnotify
     ```
   - **Fedora:**
     ```bash
     sudo dnf install python3 python3-pip vlc portaudio libnotify
     ```

2. **Depoyu Klonlayın ve Klasöre Geçin:**
   ```bash
   git clone https://github.com/Nazmicanyrs/YoutubeMusic-CL-.git
   cd YoutubeMusic-CL-
   ```

3. **Sanal Ortamı Kurun ve Paketleri Yükleyin:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Çalıştırma:**
   ```bash
   # İzinleri verin:
   chmod +x baslat.sh baslat_gui.sh

   # Terminal Arayüzü (CLI):
   ./baslat.sh

   # Masaüstü Grafik Arayüzü (GUI):
   ./baslat_gui.sh
   ```

---

### 🪟 Windows (Windows 10 / 11)

1. **Gereksinimler:**
   - [Python 3.10+](https://www.python.org/) (*Kurulumda "Add Python to PATH" kutusunu işaretleyin.*)
   - [VLC Media Player (64-bit)](https://www.videolan.org/)
   - Gerçek piksel kapak resmi için **Windows Terminal 1.22+**
   - *(İsteğe bağlı)* Deno: `winget install DenoLand.Deno`

2. **Kurulum ve Çalıştırma:**
   ```bat
   :: Depoyu indirin
   git clone https://github.com/Nazmicanyrs/YoutubeMusic-CL-.git
   cd YoutubeMusic-CL-

   :: Sanal ortam oluşturup aktif edin
   python -m venv venv
   venv\Scripts\activate.bat

   :: Paketleri kurun
   pip install -r requirements.txt

   :: Başlatın
   python main.py
   ```
   *(Veya `baslat.bat` / `baslat_gui.bat` dosyalarına çift tıklayarak tek tıkla başlatabilirsiniz.)*

---

## Kapak Kalitesi & Terminal Uyumluluğu

- **Gerçek Piksel (Sixel):** Sixel destekleyen terminallerde (Windows Terminal 1.22+, macOS'ta iTerm2, WezTerm, Foot, Kitty vb.) albüm kapağı gerçek piksel olarak gösterilir.
- **Renkli Blok (Half-Block):** Sixel desteklemeyen tüm standart terminallerde (macOS varsayılan Terminal, Linux GNOME Terminal vb.) albüm kapakları 24-bit TrueColor yarım blok karakterleriyle net şekilde çizilir.
- `C` tuşuna basarak istediğiniz an Retro Braille ve Blok modları arasında geçiş yapabilirsiniz.

---

## Sorun Giderme

- **"VLC bulunamadı" Hatası:**
  - **macOS:** `brew install --cask vlc` ile VLC'yi kurun. Uygulamanın `/Applications/VLC.app` dizininde olduğundan emin olun.
  - **Linux:** Dağıtımınıza göre `sudo apt install vlc libvlc-dev` veya `sudo pacman -S vlc` kurun.
  - **Windows:** videolan.org adresinden 64-bit VLC kurun.
- **Şarkılar Açılmıyor / Akış Hatası:** YouTube akış motorunu güncellemek için `pip install -U yt-dlp` çalıştırın. Deno çalışma zamanını kurun.
- **Ayrıntılı Günlükler (Logs):** Uygulama klasöründeki `ytm-cl.log` dosyasından hataların tam ayrıntısına ulaşabilirsiniz.

---

## Veri Dosyaları

Tüm kişisel veriler uygulama klasöründe saklanır (git'e eklenmez): `playlists.json`, `history.json`, `settings.json`.
Bir dosya bozulursa uygulama veriyi silmez; `*.corrupt-<zaman>.json` adıyla yedeğini alır ve sizi uyarır.

> ℹ️ Bulut paylaşımı listeleri **dpaste.com** sitesine yükler; paylaşım kodunu bilen herkes listeyi görebilir.
