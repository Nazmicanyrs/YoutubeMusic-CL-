"""YouTube Music CLI Player — terminal arayüzü ve uygulama giriş noktası."""
import os
import sys

if os.name != "nt":
    print("Bu uygulama şu an yalnızca Windows'ta çalışır (msvcrt / win11toast bağımlılıkları).")
    sys.exit(1)

# Konsolun UTF-8 çıktıyı (özellikle ▀ yarım blok karakterleri ve Türkçe harfler) sorunsuz basmasını sağla
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import io
import json
import logging
import msvcrt
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from bisect import bisect_right
from collections import deque
from logging.handlers import RotatingFileHandler

import requests
from PIL import Image, ImageEnhance

try:
    from win11toast import toast
except ImportError:
    toast = None

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    import syncedlyrics
except ImportError:
    syncedlyrics = None

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.utils import get_style
from prompt_toolkit.completion import WordCompleter

from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from api_service import MusicAPI, MusicAPIError
from player_service import PlayerService
from playlist_service import PlaylistManager
from song_utils import clean_text, parse_duration_ms, sanitize_song, upscale_thumbnail
from storage import data_path, load_json, save_json_atomic, startup_warnings
from terminal_graphics import GraphicsSupport, PENDING_KEYS, SixelLive, detect_graphics, fit_cover

logger = logging.getLogger("ytm-cl")
console = Console()

# Servisler main() -> init_app() içinde oluşturulur (import sırasında yan etki olmasın).
api = None
player = None
playlist_manager = None

LOG_FILE = data_path("ytm-cl.log")
SETTINGS_FILE = data_path("settings.json")
HISTORY_FILE = data_path("history.json")
ICON_DIR = os.path.join(tempfile.gettempdir(), "ytm-cl-icons")

FAVORITES = "Favorilerim"
MAX_NAME_LEN = 100
MAX_IMPORT_SONGS = 5000
MAX_IMPORT_PLAYLISTS = 20
HISTORY_LIMIT = 50

DPASTE_API = "https://dpaste.com/api/v2/"
HTTP_HEADERS = {"User-Agent": "YoutubeMusic-CL/2.0 (+https://github.com/Nazmicanyrs/YoutubeMusic-CL-)"}
IMAGE_HEADERS = {"User-Agent": "Mozilla/5.0"}
SHARE_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,20}$")
DPASTE_URL_RE = re.compile(r"^https://dpaste\.com/([A-Za-z0-9]+)/?$")

# --------------------------------------------------------------------------- temalar
THEMES = {
    "Spotify": {
        "primary": "#1DB954",
        "border": "#535353",
        "pointer": "> ",
        "style_overrides": {
            "questionmark": "#1DB954 bold",
            "answer": "#1db954 bold",
            "input": "white",
            "pointer": "#1DB954 bold",
            "marker": "#1DB954",
            "instruction": "dim white",
        },
    },
    "Youtube Music": {
        "primary": "#FF0000",
        "border": "#606060",
        "pointer": "► ",
        "style_overrides": {
            "questionmark": "#FF0000 bold",
            "answer": "#FF0000 bold",
            "input": "white",
            "pointer": "#FF0000 bold",
            "marker": "#FF0000",
            "instruction": "dim white",
        },
    },
    "Apple Music": {
        "primary": "#FA243C",
        "border": "#8E8E93",
        "pointer": "● ",
        "style_overrides": {
            "questionmark": "#FA243C bold",
            "answer": "#FA243C bold",
            "input": "white",
            "pointer": "#FA243C bold",
            "marker": "#FA243C",
            "instruction": "dim white",
        },
    },
    "Winamp (Retro)": {
        "primary": "#FF9900",
        "border": "#FF9900",
        "pointer": ">>",
        "style_overrides": {
            "questionmark": "#FF9900 bold",
            "answer": "#00FF00 bold",
            "input": "#00FF00",
            "pointer": "#FF9900 bold",
            "marker": "#FF9900",
            "instruction": "dim #00FF00",
        },
    },
    "Matrix": {
        "primary": "#00FF41",
        "border": "#008F11",
        "pointer": "=>",
        "style_overrides": {
            "questionmark": "#00FF41 bold",
            "answer": "#00FF41 bold",
            "input": "#00FF41",
            "pointer": "#00FF41 bold",
            "marker": "#00FF41",
            "instruction": "dim #008F11",
        },
    },
}

# --------------------------------------------------------------------------- ayarlar
DEFAULT_SETTINGS = {
    "notifications_enabled": True,
    "theme": "Spotify",
    "normalization": True,
    "volume": 90,
    "cover_style": "block",  # otomatik gerçek piksel / blok yedeği; veya "braille"
    "custom_themes": {},
}
app_settings = dict(DEFAULT_SETTINGS)


def setup_logging():
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def get_all_themes():
    themes = dict(THEMES)
    custom = app_settings.get("custom_themes")
    if isinstance(custom, dict):
        themes.update(custom)
    return themes


def get_current_theme():
    all_themes = get_all_themes()
    return all_themes.get(app_settings.get("theme", "Spotify"), THEMES["Spotify"])


def get_current_style():
    return get_style(get_current_theme()["style_overrides"], style_override=False)


def load_settings():
    data = load_json(SETTINGS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    settings = dict(DEFAULT_SETTINGS)
    for key, default in DEFAULT_SETTINGS.items():
        value = data.get(key)
        if isinstance(default, bool):
            if isinstance(value, bool):
                settings[key] = value
        elif isinstance(default, dict):
            if isinstance(value, dict):
                settings[key] = value
        elif isinstance(value, type(default)) and not isinstance(value, bool):
            settings[key] = value
    if settings.get("cover_style") not in ("block", "braille"):
        settings["cover_style"] = "block"
    all_themes = dict(THEMES)
    if isinstance(settings.get("custom_themes"), dict):
        all_themes.update(settings["custom_themes"])
    if settings["theme"] not in all_themes:
        settings["theme"] = "Spotify"
    settings["volume"] = max(0, min(100, settings["volume"]))
    return settings


def save_settings():
    try:
        save_json_atomic(SETTINGS_FILE, app_settings)
    except OSError:
        logger.exception("Ayarlar kaydedilemedi")


def load_history():
    data = load_json(HISTORY_FILE, [])
    if not isinstance(data, list):
        return []
    return [h for h in data if isinstance(h, str)]


def save_history(query):
    hist = load_history()
    if query in hist:
        hist.remove(query)
    hist.insert(0, query)
    try:
        save_json_atomic(HISTORY_FILE, hist[:HISTORY_LIMIT])
    except OSError:
        logger.exception("Arama geçmişi kaydedilemedi")


# --------------------------------------------------------------------------- UI yardımcıları
def ask_select(message, choices, default=None):
    return inquirer.select(
        message=message,
        choices=choices,
        default=default,
        style=get_current_style(),
        pointer=get_current_theme()["pointer"],
    ).execute()


def wait_enter(message="Devam etmek için Enter'a basın..."):
    console.input(f"\n[dim]{escape(message)}[/dim]")


def pause_message(markup, seconds=1.5):
    console.print(markup)
    time.sleep(seconds)


def copy_to_clipboard(text):
    try:
        subprocess.run(["clip"], input=text.encode("utf-16"), check=True, timeout=5)
        return True
    except Exception:
        logger.debug("Panoya kopyalanamadı", exc_info=True)
        return False


def format_time(ms):
    s = max(0, int(ms)) // 1000
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def get_visualizer(width, is_playing, primary):
    blocks = " ▂▃▄▅▆"
    if not is_playing:
        return Text(" " * width)
    return Text("".join(random.choice(blocks) for _ in range(width)), style=primary)


# --------------------------------------------------------------------------- kapak resmi
_RESAMPLE = getattr(Image, "Resampling", Image)


def fetch_cover(url):
    """Kapak resmini indirir ve kare olarak kırpar. Hata durumunda istisna fırlatır."""
    if not url:
        return None
    # Eski playlist kayıtlarındaki küçük adresleri de yükselt. Büyük görsel
    # sunulamıyorsa mevcut adrese dön; kaynağın çözünürlüğünü uydurma.
    urls = list(dict.fromkeys([upscale_thumbnail(url, 1024), url]))
    for index, candidate in enumerate(urls):
        try:
            r = requests.get(candidate, headers=IMAGE_HEADERS, timeout=5)
            r.raise_for_status()
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            break
        except (requests.RequestException, OSError):
            if index == len(urls) - 1:
                raise
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    return img.crop((left, top, left + side, top + side))


def enhance_cover_image(img):
    """Terminalde küçülen resmin detaylarının kaybolmaması için hafif kontrast ve keskinlik uygular."""
    try:
        img = ImageEnhance.Sharpness(img).enhance(1.35)
        img = ImageEnhance.Contrast(img).enhance(1.15)
    except Exception:
        pass
    return img


def half_block_art(img, width):
    """Sixel desteklemeyen terminaller için renkli yarım blok yedeği.

    Her karakter hücresinde 2 dikey piksel (üst = foreground, alt = background)
    kullanılır. Karakter hücresi ~1:2 en/boy oranında olduğundan her alt piksel 1:1 tam karedir.
    Dithering (nokta gürültüsü) yoktur; gerçek albüm kapağı renkleri ve detayları pürüzsüz görünür.
    """
    img = enhance_cover_image(img)
    rows = max(1, width // 2)
    px_w, px_h = width, rows * 2
    resized = img.resize((px_w, px_h), _RESAMPLE.LANCZOS)
    px = resized.load()
    text = Text(no_wrap=True, overflow="crop")
    for cy in range(rows):
        y = cy * 2
        for cx in range(width):
            r1, g1, b1 = px[cx, y]
            r2, g2, b2 = px[cx, y + 1]
            text.append("▀", style=f"#{r1:02x}{g1:02x}{b1:02x} on #{r2:02x}{g2:02x}{b2:02x}")
        if cy < rows - 1:
            text.append("\n")
    return text


def braille_art(img, width):
    """`width` sütun x `width // 2` satırlık (terminalde kare görünen) retro braille kapak."""
    rows = max(1, width // 2)
    px_w, px_h = width * 2, rows * 4
    mono = img.resize((px_w, px_h), _RESAMPLE.LANCZOS).convert("1").load()
    colors = img.resize((width, rows), _RESAMPLE.BOX).load()  # hücre başına ortalama renk
    dot_bits = ((1, 8), (2, 16), (4, 32), (64, 128))
    text = Text(no_wrap=True, overflow="crop")
    for cy in range(rows):
        y = cy * 4
        for cx in range(width):
            x = cx * 2
            byte = 0
            for dy, (left_bit, right_bit) in enumerate(dot_bits):
                if mono[x, y + dy]:
                    byte |= left_bit
                if mono[x + 1, y + dy]:
                    byte |= right_bit
            r, g, b = colors[cx, cy]
            text.append(chr(0x2800 + byte), style=f"#{r:02x}{g:02x}{b:02x}")
        if cy < rows - 1:
            text.append("\n")
    return text


# --------------------------------------------------------------------------- şarkı sözleri
_LRC_TS = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(lrc):
    """LRC metnini [(ms, satır), ...] listesine çevirir. Satır başına çoklu zaman damgası desteklenir."""
    out = []
    for raw in lrc.splitlines():
        line = raw.strip()
        pos = 0
        stamps = []
        while True:
            m = _LRC_TS.match(line, pos)
            if not m:
                break
            stamps.append(m)
            pos = m.end()
        text = line[pos:].strip()
        if not stamps or not text:
            continue
        for m in stamps:
            frac = (m.group(3) or "0").ljust(3, "0")
            out.append((int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int(frac), text))
    out.sort(key=lambda x: x[0])
    return out


def search_synced_lyrics(term):
    try:
        return syncedlyrics.search(term, synced_only=True)
    except TypeError:
        return syncedlyrics.search(term)


# --------------------------------------------------------------------------- bildirim
def show_notification(song):
    if not app_settings.get("notifications_enabled", True) or toast is None:
        return
    try:
        icon = None
        if song.get("thumbnail"):
            os.makedirs(ICON_DIR, exist_ok=True)
            icon_path = os.path.join(ICON_DIR, f"{song['videoId']}.jpg")
            if not os.path.exists(icon_path):
                r = requests.get(song["thumbnail"], headers=IMAGE_HEADERS, timeout=5)
                r.raise_for_status()
                with open(icon_path, "wb") as f:
                    f.write(r.content)
            icon = icon_path
        toast("🎵 Şimdi Çalıyor", f"{song['title']}\n{song['artist']}", icon=icon, app_id="YoutubeMusic-CL")
    except Exception:
        logger.debug("Bildirim gösterilemedi", exc_info=True)


# --------------------------------------------------------------------------- global kısayollar
ACTION_QUEUE = deque(maxlen=32)
HOTKEYS_ACTIVE = threading.Event()  # yalnızca oynatıcı açıkken eylemleri kabul et

# Ctrl+Alt+Yön tuşları bazı Intel sürücülerinde ekranı döndürdüğü için Shift eklendi.
GLOBAL_HOTKEYS = {
    "ctrl+shift+alt+right": "next",
    "ctrl+shift+alt+left": "prev",
    "ctrl+shift+alt+space": "playpause",
    "ctrl+shift+alt+up": "vol_up",
    "ctrl+shift+alt+down": "vol_down",
    "ctrl+shift+alt+l": "like",
    "next track": "next",
    "previous track": "prev",
    "play/pause media": "playpause",
}


def _enqueue_global(action):
    if HOTKEYS_ACTIVE.is_set():
        ACTION_QUEUE.append(action)


def setup_global_hotkeys():
    if not keyboard:
        return
    for combo, action in GLOBAL_HOTKEYS.items():
        try:
            keyboard.add_hotkey(combo, _enqueue_global, args=(action,))
        except Exception:
            logger.warning("Global kısayol kaydedilemedi: %s", combo, exc_info=True)


# --------------------------------------------------------------------------- oynatıcı oturumu
KEYMAP = {
    b"q": "quit", b"Q": "quit", b"\x1b": "quit", b"\x03": "quit",
    b"n": "next", b"N": "next",
    b"b": "prev", b"B": "prev",
    b" ": "playpause",
    b"l": "like", b"L": "like", b"f": "like", b"F": "like",
    b"p": "playlist", b"P": "playlist",
    b"+": "vol_up", b"=": "vol_up", b"k": "vol_up", b"K": "vol_up",
    b"-": "vol_down", b"_": "vol_down", b"j": "vol_down", b"J": "vol_down",
    b"y": "scroll_up", b"Y": "scroll_up", b"a": "scroll_down", b"A": "scroll_down",
    b"m": "toggle_mini", b"M": "toggle_mini",
    b"c": "toggle_cover", b"C": "toggle_cover",
}
ARROW_KEYMAP = {b"H": "scroll_up", b"P": "scroll_down", b"K": "seek_back", b"M": "seek_fwd"}


class PlayerSession:
    """Tek bir dinleme oturumu. Tüm durum bu nesnede tutulur (global/fonksiyon özniteliği yok).

    Arka plan işleri (akış çözümleme, kapak, söz) bir `token` ile etiketlenir; şarkı
    değiştiğinde eski işlerin sonuçları yok sayılır.
    """

    def __init__(self, initial_song, queue):
        self.queue = list(queue) or [initial_song]  # kopya: playlist değişse de kuyruk bozulmaz
        self.idx = next((i for i, s in enumerate(self.queue) if s["videoId"] == initial_song["videoId"]), 0)
        self.lock = threading.RLock()
        self.token = 0
        self.loading = False
        self.error = None
        self.error_time = 0.0
        self.cover = None  # None: yükleniyor, False: yok/hata, Image: hazır
        self._art_cache = {}
        self.lyrics = []
        self.lyric_times = []
        self.lyrics_status = ""
        self.lyrics_fetching = False
        self.flash_msg = None
        self.visible_items = 10
        self.scroll_offset = max(0, self.idx - 4)
        self.mini_mode = False
        self.graphics = GraphicsSupport()
        self._pixel_cover = None

    @property
    def song(self):
        return self.queue[self.idx]

    def flash(self, text, style="bold white", seconds=3.0):
        self.flash_msg = (text, style, time.time() + seconds)

    # ---------------------------------------------------------- yükleme
    def start_track(self):
        with self.lock:
            self.token += 1
            token = self.token
            song = self.song
            self.loading = True
            self.error = None
            self.cover = None
            self._art_cache = {}
            self.lyrics = []
            self.lyric_times = []
            self.lyrics_status = ""
            self.lyrics_fetching = True
            self.scroll_offset = max(0, self.idx - 4)
        player.stop()  # eski şarkı yeni şarkı yüklenirken çalmaya devam etmesin
        for target in (self._load_stream, self._load_cover, self._load_lyrics):
            threading.Thread(target=target, args=(token, song), daemon=True).start()

    def _set_error(self, message):
        self.loading = False
        self.error = message
        self.error_time = time.time()

    @staticmethod
    def _short_error(e):
        msg = str(e).strip().splitlines()[0] if str(e).strip() else e.__class__.__name__
        msg = re.sub(r"^ERROR:\s*", "", msg)
        msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
        return msg[:120]

    def _load_stream(self, token, song):
        try:
            stream, headers = player.resolve(song["url"])
        except Exception as e:
            logger.exception("Akış çözümlenemedi: %s", song.get("videoId"))
            with self.lock:
                if token == self.token:
                    self._set_error(f"Şarkı açılamadı: {self._short_error(e)}")
            return
        with self.lock:
            if token != self.token:
                return  # kullanıcı bu arada başka şarkıya geçti
            if player.play_stream(stream, headers):
                self.loading = False
                threading.Thread(target=show_notification, args=(song,), daemon=True).start()
            else:
                self._set_error(f"Şarkı çalınamadı: {player.last_error or 'bilinmeyen hata'}")

    def _load_cover(self, token, song):
        try:
            img = fetch_cover(song.get("thumbnail"))
        except Exception:
            logger.info("Kapak indirilemedi: %s", song.get("thumbnail"), exc_info=True)
            img = None
        with self.lock:
            if token == self.token:
                self.cover = img if img is not None else False

    def _load_lyrics(self, token, song):
        data, status = [], ""
        if not syncedlyrics:
            status = "syncedlyrics kurulu değil."
        else:
            try:
                lrc = search_synced_lyrics(f"{song['title']} {song['artist']}")
                if not lrc:
                    status = "Söz bulunamadı."
                else:
                    data = parse_lrc(lrc)
                    if not data:
                        status = "Senkronlu söz bulunamadı."
            except Exception:
                logger.info("Söz alınamadı", exc_info=True)
                status = "Söz alınırken hata oluştu."
        with self.lock:
            if token == self.token:
                self.lyrics = data
                self.lyric_times = [t for t, _ in data]
                self.lyrics_status = status
                self.lyrics_fetching = False

    # ---------------------------------------------------------- eylemler
    def go(self, delta):
        new_idx = self.idx + delta
        if not 0 <= new_idx < len(self.queue):
            return False
        self.idx = new_idx
        self.start_track()
        return True

    def next_track(self):
        if not self.go(1):
            self.flash("Kuyruğun sonundasınız.", "yellow")

    def prev_track(self):
        # Şarkının başından 3 sn geçtiyse veya ilk şarkıdaysak: şarkıyı başa sar.
        if (player.get_time() > 3000 or self.idx == 0) and not self.loading and not self.error:
            player.seek_to(0)
            return
        if not self.go(-1):
            self.flash("Kuyruğun başındasınız.", "yellow")

    def toggle_like(self):
        try:
            added = playlist_manager.toggle_song(FAVORITES, self.song)
        except OSError:
            logger.exception("Favoriler kaydedilemedi")
            self.flash("⚠ Favoriler kaydedilemedi!", "bold yellow")
            return
        if added:
            self.flash("❤️ Favorilere Eklendi!", "bold red")
        else:
            self.flash("🤍 Favorilerden Çıkarıldı!", "bold white")

    def scroll(self, delta):
        max_off = max(0, len(self.queue) - self.visible_items)
        self.scroll_offset = max(0, min(max_off, self.scroll_offset + delta))

    def dispatch(self, action):
        if action == "quit":
            return "quit"
        if action == "playlist":
            return "playlist"
        if action == "next":
            self.next_track()
        elif action == "prev":
            self.prev_track()
        elif action == "playpause":
            if not self.loading and not self.error:
                player.toggle_pause()
        elif action == "vol_up":
            player.set_volume(player.get_volume() + 5)
        elif action == "vol_down":
            player.set_volume(player.get_volume() - 5)
        elif action == "like":
            self.toggle_like()
        elif action == "scroll_up":
            self.scroll(-1)
        elif action == "scroll_down":
            self.scroll(1)
        elif action == "seek_back":
            player.seek(-5000)
        elif action == "seek_fwd":
            player.seek(5000)
        elif action == "toggle_mini":
            self.mini_mode = not self.mini_mode
            label = "Kompakt (Mini)" if self.mini_mode else "Tam Ekran"
            self.flash(f"📺 Görünüm: {label}", "bold cyan", seconds=1.5)
        elif action == "toggle_cover":
            cur = app_settings.get("cover_style", "block")
            new_style = "braille" if cur == "block" else "block"
            app_settings["cover_style"] = new_style
            save_settings()
            self._art_cache.clear()
            label = "Gerçek Piksel (Sixel)" if new_style == "block" and self.graphics.sixel else ("Renkli Blok" if new_style == "block" else "Retro Braille")
            self.flash(f"🖼️ Kapak: {label}", "bold cyan", seconds=2.0)
        return None

    @staticmethod
    def read_key():
        if not PENDING_KEYS and not msvcrt.kbhit():
            return None
        ch = PENDING_KEYS.popleft() if PENDING_KEYS else msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):  # yön/fonksiyon tuşları iki bayt gönderir
            return ARROW_KEYMAP.get(PENDING_KEYS.popleft() if PENDING_KEYS else msvcrt.getch())
        return KEYMAP.get(ch)

    def check_auto_advance(self):
        with self.lock:
            if self.loading:
                return None
            if self.error:
                # Hatalı şarkıyı 3 sn gösterip sıradakine geç; sonuncuysa kullanıcıyı bekle.
                if time.time() - self.error_time > 3 and self.idx + 1 < len(self.queue):
                    self.go(1)
                return None
        state = player.get_state()
        if state == "ended":
            if self.idx + 1 < len(self.queue):
                self.go(1)
                return None
            return "quit"
        if state == "error":
            with self.lock:
                self._set_error("Oynatma sırasında hata oluştu (akış kesildi).")
        return None

    # ---------------------------------------------------------- döngü
    def run(self):
        self.graphics = detect_graphics(console)
        ACTION_QUEUE.clear()
        HOTKEYS_ACTIVE.set()
        self.start_track()
        try:
            display = (SixelLive(self.render(), console, lambda: self._pixel_cover)
                       if self.graphics.sixel else
                       Live(self.render(), console=console, refresh_per_second=10, screen=True))
            last_size = console.size
            with display as live:
                while True:
                    result = None
                    while ACTION_QUEUE and result is None:
                        result = self.dispatch(ACTION_QUEUE.popleft())
                    if result is None:
                        key = self.read_key()
                        if key:
                            result = self.dispatch(key)
                    if result is None:
                        result = self.check_auto_advance()

                    if result == "quit":
                        break
                    if result == "playlist":
                        HOTKEYS_ACTIVE.clear()
                        live.stop()
                        try:
                            add_to_playlist_dialog(self.song)
                        finally:
                            ACTION_QUEUE.clear()
                            HOTKEYS_ACTIVE.set()
                            live.start(refresh=True)

                    player.tick()
                    if self.graphics.sixel and console.size != last_size:
                        # Font zoom changes cell pixels as well as terminal dimensions.
                        refreshed = detect_graphics(console)
                        if refreshed.sixel:
                            self.graphics = refreshed
                        last_size = console.size
                    live.update(self.render())
                    time.sleep(0.05)  # CPU'yu boşa yakmamak için
        finally:
            HOTKEYS_ACTIVE.clear()
            ACTION_QUEUE.clear()
            with self.lock:
                self.token += 1  # bekleyen arka plan işlerini geçersiz kıl
            player.stop()
            app_settings["volume"] = player.get_volume()
            save_settings()

    # ---------------------------------------------------------- çizim
    def _art_renderable(self, cover, width):
        if cover is None:
            return Text("\n Kapak yükleniyor...", style="dim")
        if cover is False:
            return Text("\n [Kapak Yok]", style="dim")
        style = app_settings.get("cover_style", "block")
        cache_key = (width, style)
        art = self._art_cache.get(cache_key)
        if art is None:
            try:
                if style == "braille":
                    art = braille_art(cover, width)
                else:
                    art = half_block_art(cover, width)
            except Exception:
                logger.info("Kapak çizilemedi", exc_info=True)
                art = Text("[Resim Yüklenemedi]", style="red")
            self._art_cache[cache_key] = art
        return art

    def _lyrics_lines(self, now_ms, primary, lyrics, times, status, fetching):
        lines = [Text(), Text(), Text()]
        if fetching:
            lines[1] = Text("     ⏳ Sözler aranıyor...", style="dim")
        elif status:
            lines[1] = Text(f"     {status}", style="dim")
        elif lyrics:
            i = bisect_right(times, now_ms + 300) - 1
            if i < 0:
                lines[1] = Text("     ...", style="dim")
            else:
                if i > 0:
                    lines[0] = Text(f"     {lyrics[i - 1][1]}", style="dim white")
                cur = lyrics[i][1]
                start = lyrics[i][0]
                end = lyrics[i + 1][0] if i + 1 < len(lyrics) else start + 4000
                progress = max(0.0, min(1.0, (now_ms - start + 300) / max(1, end - start)))
                n = int(len(cur) * progress)
                pulse = "🎤" if (now_ms // 300) % 2 == 0 else "🎵"
                line = Text(f" {pulse} ")
                line.append(cur[:n], style=f"bold {primary}")
                line.append(cur[n:], style="bold white")
                lines[1] = line
                if i + 1 < len(lyrics):
                    lines[2] = Text(f"     {lyrics[i + 1][1]}", style="dim white")
        return lines

    def render_mini(self):
        """Kompakt (Mini Player) görünümü: az yer kaplayan, 3 satırlık modern şerit."""
        theme = get_current_theme()
        primary = theme["primary"]
        width, _ = console.size
        inner_w = max(20, width - 6)

        with self.lock:
            song = self.song
            idx = self.idx
            loading, error = self.loading, self.error

        state = "loading" if loading else player.get_state()
        now_ms = 0 if loading else player.get_time()
        total = 0 if loading else player.get_length()
        if total <= 0:
            total = parse_duration_ms(song.get("duration"))

        vol = player.get_volume()
        is_liked = playlist_manager.contains(FAVORITES, song["videoId"])

        # Satır 1: Başlık, Sanatçı, İndikatörler
        line1 = Text(no_wrap=True, overflow="ellipsis")
        pulse = "▶" if state == "playing" else ("⏸" if state == "paused" else "⏳")
        line1.append(f"{pulse} ", style=f"bold {primary}")
        line1.append(song["title"], style="bold white")
        line1.append(f" - {song['artist']}", style="dim white")
        line1.append(f"  ({idx + 1}/{len(self.queue)})", style="dim")
        if is_liked:
            line1.append("  ❤️", style="red")
        if loading:
            line1.append("  [⏳ Yükleniyor...]", style="yellow")
        elif error:
            line1.append(f"  [⚠ {error[:30]}]", style="bold red")
        elif self.flash_msg and time.time() < self.flash_msg[2]:
            line1.append(f"  [{self.flash_msg[0]}]", style=self.flash_msg[1])

        # Satır 2: İlerleme Çubuğu + Zaman + Ses
        bar_len = max(10, inner_w - 36)
        ratio = min(1.0, now_ms / total) if total > 0 else 0.0
        filled = min(bar_len - 1, int(bar_len * ratio))
        line2 = Text(no_wrap=True, overflow="crop")
        line2.append("━" * filled, style=primary)
        line2.append("●", style=f"bold {primary}")
        line2.append("━" * (bar_len - filled - 1), style="dim")
        line2.append(f"  {format_time(now_ms)}/{format_time(total)}", style="dim")
        line2.append(f"  (VOL: {vol}%)", style=f"bold {primary}")

        # Satır 3: Kontroller
        line3 = Text(
            "[Space] Durdur/Oynat  [N] İleri  [B] Geri  [←/→] ±5s  [+/-] Ses  [M] Genişlet  [Q] Çıkış",
            style="dim", no_wrap=True, overflow="ellipsis"
        )

        mini_content = Text("\n").join([line1, line2, line3])
        return Panel(
            mini_content,
            title=f"[bold {primary}]Mini Player[/]",
            border_style=theme["border"],
            box=box.ROUNDED,
            padding=(0, 1),
        )

    def render(self):
        self._pixel_cover = None
        width, height = console.size
        # Mini Player modu açıkken veya terminal penceresi küçükken kompakt arayüz göster
        if self.mini_mode or height < 24 or width < 55:
            return self.render_mini()

        theme = get_current_theme()
        primary = theme["primary"]
        inner_w = max(20, width - 6)   # kenarlık (2) + yatay padding (4)
        inner_h = max(10, height - 4)  # kenarlık (2) + dikey padding (2)

        with self.lock:
            song = self.song
            idx = self.idx
            loading, error = self.loading, self.error
            cover = self.cover
            lyrics, times = self.lyrics, self.lyric_times
            lyrics_status, lyrics_fetching = self.lyrics_status, self.lyrics_fetching

        state = "loading" if loading else player.get_state()
        now_ms = 0 if loading else player.get_time()
        total = 0 if loading else player.get_length()
        if total <= 0:
            total = parse_duration_ms(song.get("duration"))

        # ---- boyutlar (terminal boyutuna göre uyarlanır)
        header_h, progress_h, bottom_h, footer_h = 2, 2, 8, 2
        vis_h = 2 if inner_h >= 34 else 0
        main_h = max(6, inner_h - header_h - progress_h - vis_h - bottom_h - footer_h)
        title_h = 4
        art_rows = max(2, min(16, main_h - title_h))
        art_w = min(art_rows * 2, int(inner_w * 0.4) - 1)
        art_w = max(4, art_w - art_w % 2)
        art_rows = art_w // 2
        pixel_mode = self.graphics.sixel and app_settings.get("cover_style") == "block"
        if pixel_mode:
            art_w, art_rows, pixel_side = fit_cover(
                max(4, int(inner_w * 0.4) - 1), max(2, main_h - title_h), self.graphics)
            if cover is not None and cover is not False:
                # Outer panel: 1 border + 2 horizontal padding; top: border,
                # padding, then the two-line header. Reserve actual cell bounds.
                self._pixel_cover = (cover, (3, 4, art_w, art_rows), (pixel_side, pixel_side))

        # ---- başlık
        header = Text(no_wrap=True, overflow="ellipsis")
        header.append("♪ Modernized CLI Player", style=f"bold {primary}")
        header.append(f"   Şarkı {idx + 1}/{len(self.queue)}", style="dim")
        cover_mode_label = "Gerçek Piksel / Sixel" if pixel_mode else ("Blok (Sixel yok)" if app_settings.get("cover_style") == "block" else "Braille")
        header.append(f"   [Kapak: {cover_mode_label}]", style="dim")
        if loading:
            header.append("   ⏳ Yükleniyor...", style="yellow")
        elif state == "paused":
            header.append("   ⏸ Duraklatıldı", style="yellow")
        if height < 30:
            header.append("\n⚠ Daha iyi görünüm için terminal penceresini büyütün veya [M] ile Mini moda geçin.", style="dim yellow")

        # ---- başlık / sanatçı / durum
        title_t = Text()
        title_t.append(f"{song['title']}\n", style="bold white")
        title_t.append(song["artist"], style="dim white")
        if error:
            title_t.append(f"\n\n⚠ {error}", style="bold red")
        elif self.flash_msg and time.time() < self.flash_msg[2]:
            title_t.append(f"\n\n{self.flash_msg[0]}", style=self.flash_msg[1])
        elif playlist_manager.contains(FAVORITES, song["videoId"]):
            title_t.append("\n\n❤️", style="red")

        # ---- kuyruk
        self.visible_items = max(1, main_h - 3)
        max_off = max(0, len(self.queue) - self.visible_items)
        self.scroll_offset = max(0, min(max_off, self.scroll_offset))
        start_i = self.scroll_offset
        end_i = min(len(self.queue), start_i + self.visible_items)
        queue_text = Text(no_wrap=True, overflow="ellipsis")
        for i in range(start_i, end_i):
            current = i == idx
            queue_text.append(
                f"{'▶ ' if current else '  '}{i + 1}. {self.queue[i]['title']}\n",
                style=f"bold {primary}" if current else "white",
            )
        if len(self.queue) > end_i:
            queue_text.append(f"  ... (+{len(self.queue) - end_i} tane daha) ...", style="dim")
        queue_panel = Panel(queue_text, title="Listede Sırada", border_style=primary)

        # ---- ilerleme
        bar_len = max(10, inner_w - 18)
        ratio = min(1.0, now_ms / total) if total > 0 else 0.0
        filled = min(bar_len - 1, int(bar_len * ratio))
        bar = Text(no_wrap=True, overflow="crop")
        bar.append("━" * filled, style=primary)
        bar.append("●", style=f"bold {primary}")
        bar.append("━" * (bar_len - filled - 1), style="dim")
        bar.append(f"  {format_time(now_ms)} / {format_time(total)}", style="dim")

        # ---- alt bilgi: ses, sözler, sıradakiler
        vol = player.get_volume()
        bars = vol // 10
        vol_line = Text.assemble(("VOL: ", "bold"), (f"[{'|' * bars}{' ' * (10 - bars)}] {vol}%", primary))
        lyric_lines = self._lyrics_lines(now_ms, primary, lyrics, times, lyrics_status, lyrics_fetching)
        next_lines = [
            Text(f"{idx + 2 + i}. {n['title']} - {n['artist']}", style="white")
            for i, n in enumerate(self.queue[idx + 1:idx + 3])
        ]
        bottom = Text("\n", no_wrap=True, overflow="ellipsis").join(
            [vol_line, *lyric_lines, Text("Sıradakiler", style="dim"), *next_lines]
        )

        footer = Text(
            "[Q/Esc] Çıkış  [Space] Durdur/Oynat  [N] Sonraki  [B] Önceki  [←/→] ±5 sn\n"
            "[M] Mini Mod  [C] Kapak Stili  [L/F] Favori ❤️  [P] Liste  [↑/↓] Kaydır  [+/-] Ses",
            style="dim", no_wrap=True, overflow="ellipsis",
        )

        # ---- yerleşim
        parts = [
            Layout(header, name="header", size=header_h),
            Layout(name="main", size=main_h),
            Layout(bar, name="progress", size=progress_h),
        ]
        if vis_h:
            parts.append(Layout(get_visualizer(bar_len, state == "playing", primary), name="visualizer", size=vis_h))
        parts += [Layout(bottom, name="bottom", size=bottom_h), Layout(footer, name="footer", size=footer_h)]

        layout = Layout()
        layout.split_column(*parts)
        layout["main"].split_row(Layout(name="left", ratio=4), Layout(queue_panel, name="right", ratio=6))
        layout["left"].split_column(
            Layout(Text(" ") if self._pixel_cover else self._art_renderable(cover, art_w), name="art", size=art_rows),
            Layout(title_t, name="title"),
        )
        return Panel(layout, border_style=theme["border"], box=box.ROUNDED, padding=(1, 2))


def play_session(initial_song, queue):
    if not player.available:
        pause_message(f"[red]{escape(player.last_error or 'VLC kullanılamıyor.')}[/red]", 3)
        return
    PlayerSession(initial_song, queue).run()


# --------------------------------------------------------------------------- tema yönetimi ve oluşturucu
def _normalize_hex(val):
    val = val.strip()
    if not val.startswith("#"):
        val = "#" + val
    return val.upper()


def create_custom_theme_flow():
    console.clear()
    console.print(Panel(
        "Kendi renklerinizi ve imleç stilinizi belirleyerek kişisel temanızı oluşturun.",
        title="🎨 Yeni Tema Oluştur",
        border_style="cyan"
    ))
    all_themes = get_all_themes()

    # 1. Tema İsmi
    name = inquirer.text(
        message="Yeni Tema İsmi (örn: Siber Mor, Akdeniz, Geceyarısı):",
        validate=lambda t: 1 <= len(t.strip()) <= 25 and t.strip() not in all_themes,
        invalid_message="İsim 1-25 karakter olmalı ve mevcut bir tema ile aynı olmamalı.",
        style=get_current_style()
    ).execute().strip()
    if not name:
        return

    # 2. Ana Vurgu Rengi
    preset_colors = [
        Choice("#2ECC71", "🟢 Zümrüt Yeşili (#2ECC71)"),
        Choice("#00A8FF", "🔵 Neon Okyanus Mavisi (#00A8FF)"),
        Choice("#9B59B6", "🟣 Siber Mor (#9B59B6)"),
        Choice("#FF007F", "🌸 Neon Pembe / Fuşya (#FF007F)"),
        Choice("#F1C40F", "🟡 Elektrik Sarısı (#F1C40F)"),
        Choice("#FF7700", "🟠 Canlı Turuncu (#FF7700)"),
        Choice("#E74C3C", "🔴 Ateş Kırmızısı (#E74C3C)"),
        Choice("#00E5FF", "🔷 Camgöbeği / Buz Mavisi (#00E5FF)"),
        Choice("CUSTOM", "🎨 Kendim Özel HEX Kodu Yazacağım..."),
    ]
    color_sel = ask_select(f"'{name}' için Ana Vurgu Rengini belirleyin:", preset_colors)
    if color_sel == "CUSTOM":
        raw_hex = inquirer.text(
            message="HEX Renk Kodu Girin (örn: #3498DB veya 3498DB):",
            validate=lambda t: bool(re.match(r"^#?[0-9a-fA-F]{6}$", t.strip())),
            invalid_message="Geçerli bir 6 haneli HEX kodu girin (örn: #FF0055).",
            style=get_current_style()
        ).execute()
        primary_hex = _normalize_hex(raw_hex)
    else:
        primary_hex = color_sel

    # 3. Kenarlık Rengi
    border_options = [
        Choice("SAME", f"Ana Renk ile Aynı ({primary_hex})"),
        Choice("#555555", "Koyu Gri (Modern & Sade - #555555)"),
        Choice("#AAAAAA", "Açık Gümüş Gri (#AAAAAA)"),
        Choice("CUSTOM", "Farklı bir HEX Kodu Belirle..."),
    ]
    border_sel = ask_select("Pano Kenarlık Rengini seçin:", border_options)
    if border_sel == "SAME":
        border_hex = primary_hex
    elif border_sel == "CUSTOM":
        raw_b_hex = inquirer.text(
            message="Kenarlık HEX Kodu:",
            validate=lambda t: bool(re.match(r"^#?[0-9a-fA-F]{6}$", t.strip())),
            invalid_message="Geçerli bir 6 haneli HEX kodu girin.",
            style=get_current_style()
        ).execute()
        border_hex = _normalize_hex(raw_b_hex)
    else:
        border_hex = border_sel

    # 4. İmleç Simgesi
    pointer_sel = ask_select("Menülerdeki İmleç Simgesini seçin:", [
        Choice("> ", ">  (Klasik)"),
        Choice("► ", "►  (Oynatıcı Oku)"),
        Choice("● ", "●  (Minimal Daire)"),
        Choice(">>", ">> (Winamp Stili)"),
        Choice("✨ ", "✨ (Parıltı)"),
        Choice("▶ ", "▶  (Üçgen Oynat)"),
    ])

    new_theme = {
        "primary": primary_hex,
        "border": border_hex,
        "pointer": pointer_sel,
        "style_overrides": {
            "questionmark": f"{primary_hex} bold",
            "answer": f"{primary_hex} bold",
            "input": "white",
            "pointer": f"{primary_hex} bold",
            "marker": primary_hex,
            "instruction": "dim white",
        }
    }

    # 5. Önizleme
    console.clear()
    preview_panel = Panel(
        f"[bold {primary_hex}]Modernized CLI Player[/] — Bu temanın ana rengidir.\n\n"
        f"Seçilen İmleç: [bold {primary_hex}]{pointer_sel}[/] Şarkı Başlığı\n"
        f"Kenarlık Rengi: {border_hex}",
        title=f"🎨 Tema Önizleme: {name}",
        border_style=border_hex,
        box=box.ROUNDED,
        padding=(1, 2)
    )
    console.print(preview_panel)

    confirm = inquirer.confirm(
        message="Bu temayı kaydetmek ve hemen etkinleştirmek istiyor musunuz?",
        default=True,
        style=get_current_style()
    ).execute()
    if confirm:
        custom_dict = app_settings.setdefault("custom_themes", {})
        custom_dict[name] = new_theme
        app_settings["theme"] = name
        save_settings()
        pause_message(f"\n[green]✓ '{name}' teması başarıyla kaydedildi ve etkinleştirildi![/green]", 1.5)


def delete_custom_theme_flow():
    custom_dict = app_settings.get("custom_themes", {})
    if not custom_dict:
        pause_message("[yellow]Silinebilecek özel bir tema bulunmuyor.[/yellow]", 1.5)
        return
    choices = [Choice(k, f"🗑️ {k}") for k in custom_dict]
    choices.append(Choice("CANCEL", "❌ İptal"))
    sel = ask_select("Silmek istediğiniz özel temayı seçin:", choices)
    if sel != "CANCEL":
        confirm = inquirer.confirm(
            message=f"'{sel}' temasını silmek istediğinize emin misiniz?",
            default=False,
            style=get_current_style()
        ).execute()
        if confirm:
            del custom_dict[sel]
            if app_settings.get("theme") == sel:
                app_settings["theme"] = "Spotify"
            save_settings()
            pause_message(f"\n[red]🗑️ '{sel}' teması silindi.[/red]", 1.5)


def theme_menu():
    while True:
        console.clear()
        cur_theme = app_settings.get("theme", "Spotify")
        console.print(Panel(
            f"Mevcut Aktif Tema: [bold {get_current_theme()['primary']}]{cur_theme}[/]",
            title="🎨 Tema Seçimi & Yönetimi",
            border_style=get_current_theme()["border"]
        ))

        choices = []
        # Standart temalar
        for k in THEMES:
            prefix = "✓ " if k == cur_theme else "  "
            choices.append(Choice(k, f"{prefix}🎨 {k} (Standart)"))

        # Özel temalar
        custom_dict = app_settings.get("custom_themes", {})
        if custom_dict:
            for k in custom_dict:
                prefix = "✓ " if k == cur_theme else "  "
                choices.append(Choice(k, f"{prefix}✨ {k} [Özel]"))

        choices.append(Choice("CREATE", "➕ Yeni Tema Oluştur (Özel Renkler & HEX)"))
        if custom_dict:
            choices.append(Choice("DELETE", "🗑️ Özel Temayı Sil"))
        choices.append(Choice("BACK", "<- Geri Dön"))

        sel = ask_select("Tema seçin veya işlem belirleyin:", choices)
        if sel == "BACK":
            break
        elif sel == "CREATE":
            create_custom_theme_flow()
        elif sel == "DELETE":
            delete_custom_theme_flow()
        else:
            app_settings["theme"] = sel
            save_settings()
            pause_message(f"\n[green]✓ '{sel}' teması aktif edildi![/green]", 1)


# --------------------------------------------------------------------------- menüler
def ask_playlist_name():
    name = inquirer.text(
        message="Yeni Çalma Listesinin Adı:",
        validate=lambda t: 0 < len(t.strip()) <= MAX_NAME_LEN,
        invalid_message=f"İsim 1-{MAX_NAME_LEN} karakter olmalı.",
        style=get_current_style(),
    ).execute()
    return clean_text(name, "")


def add_to_playlist_dialog(song):
    console.clear()
    choices = [Choice("NEW", "➕ Yeni Bir Çalma Listesi Oluştur")]
    choices += [Choice(name, f"📁 {name}") for name in playlist_manager.get_all()]
    choices.append(Choice("CANCEL", "❌ İptal"))

    sel = ask_select(f"'{song['title']}' hangi listeye eklensin?", choices)
    if sel == "CANCEL":
        return
    pl_name = ask_playlist_name() if sel == "NEW" else sel
    if not pl_name:
        pause_message("[red]Geçersiz isim, iptal edildi.[/red]", 1)
        return
    try:
        added = playlist_manager.add_song(pl_name, song)
    except (OSError, ValueError) as e:
        logger.exception("Şarkı listeye eklenemedi")
        pause_message(f"\n[red]Kaydedilemedi: {escape(str(e))}[/red]", 2)
        return
    if added:
        pause_message(f"\n[green]✓ Şarkı '{escape(pl_name)}' listesine eklendi![/green]")
    else:
        pause_message(f"\n[yellow]Bu şarkı zaten '{escape(pl_name)}' listesinde var.[/yellow]")


def search_menu():
    theme = get_current_theme()
    console.clear()
    console.print(Panel(f"[bold {theme['primary']}]Modernized CLI Player[/] - Arama", border_style=theme["border"]))

    query = inquirer.text(
        message="Şarkı veya sanatçı arayın (Çıkmak için boş bırakın):",
        completer=WordCompleter(load_history(), ignore_case=True, sentence=True),
        style=get_current_style(),
    ).execute().strip()
    if not query:
        return

    save_history(query)
    try:
        with console.status(f"[bold yellow]Arama yapılıyor '{escape(query)}'...[/bold yellow]"):
            results = api.search(query)
    except MusicAPIError as e:
        pause_message(f"[red]{escape(str(e))}[/red]", 3)
        return

    if not results:
        pause_message("[red]Sonuç bulunamadı.[/red]", 2)
        return

    choices = [Choice("BACK", "<- Geri Dön")]
    choices += [Choice(item, f"{item['title']} - {item['artist']}") for item in results]
    sel = ask_select("Seçtiğiniz şarkıyı dinleyin:", choices)
    if sel != "BACK":
        play_session(sel, results)


def export_playlist_cloud(pl_name, songs):
    theme = get_current_theme()
    console.clear()
    console.print(Panel(
        "Liste [bold]herkese açık[/bold] dpaste.com sitesine yüklenecek. Paylaşım kodunu bilen "
        "herkes listeyi görebilir. Liste 365 gün saklanır.",
        title="⚠ Gizlilik Uyarısı", border_style="yellow",
    ))
    if not inquirer.confirm(message="Devam edilsin mi?", default=True, style=get_current_style()).execute():
        return

    clean_songs = [s for s in (sanitize_song(x) for x in songs) if s]
    payload = json.dumps({pl_name: clean_songs}, ensure_ascii=False)
    try:
        with console.status(f"[bold yellow]'{escape(pl_name)}' listesi buluta yükleniyor...[/bold yellow]"):
            r = requests.post(
                DPASTE_API,
                data={"content": payload, "syntax": "json", "expiry_days": 365},
                headers=HTTP_HEADERS,
                timeout=15,
            )
            r.raise_for_status()
        url = (r.headers.get("Location") or r.text).strip()
        m = DPASTE_URL_RE.match(url)
        if not m:
            raise ValueError(f"Beklenmeyen sunucu yanıtı: {url[:80]}")
        code = m.group(1)
    except (requests.RequestException, ValueError) as e:
        logger.exception("Liste paylaşılamadı")
        console.print(f"[red]Liste paylaşılamadı: {escape(str(e))}[/red]")
        wait_enter()
        return

    copied = copy_to_clipboard(code)
    console.print(Panel(
        f"Liste başarıyla paylaşıldı!\n\nArkadaşlarınıza şu paylaşım kodunu gönderin: "
        f"[bold {theme['primary']}]{code}[/]"
        + ("\n[dim](Kod panoya kopyalandı.)[/dim]" if copied else "")
        + "\n\nBu kod 1 yıl boyunca geçerlidir.",
        title="🚀 Bulut Paylaşımı", border_style=theme["primary"],
    ))
    wait_enter()


def import_playlist_cloud():
    console.clear()
    console.print(Panel(
        "Arkadaşınızın size gönderdiği Kısa Kodu (veya dpaste linkini) girerek listesini içeri aktarabilirsiniz.",
        title="📥 Buluttan İndir (İçe Aktar)", border_style=get_current_theme()["primary"],
    ))
    code = inquirer.text(
        message="Paylaşım Kodunu Girin (örn: 7PRHHYV94) veya Q basıp çıkın:",
        style=get_current_style(),
    ).execute().strip()
    if not code or code.upper() == "Q":
        return
    if "dpaste.com/" in code:
        code = code.rstrip("/").split("/")[-1]
    code = code.removesuffix(".txt")
    if not SHARE_CODE_RE.match(code):
        console.print("\n[red]❌ Geçersiz kod formatı. Kod yalnızca harf ve rakamlardan oluşmalı.[/red]")
        wait_enter()
        return

    try:
        with console.status(f"[bold yellow]Buluttan '{escape(code)}' aranıyor...[/bold yellow]"):
            r = requests.get(f"https://dpaste.com/{code}.txt", headers=HTTP_HEADERS, timeout=15)
        if r.status_code == 404:
            console.print("\n[red]❌ Geçersiz kod veya süresi dolmuş liste![/red]")
            wait_enter()
            return
        r.raise_for_status()
        data = json.loads(r.text)
    except (requests.RequestException, ValueError) as e:
        logger.exception("Liste indirilemedi")
        console.print(f"\n[red]❌ Liste indirilemedi (bağlantı veya veri hatası): {escape(str(e))}[/red]")
        wait_enter()
        return

    if not isinstance(data, dict) or not data:
        console.print("\n[red]❌ Bu kod geçerli bir çalma listesi içermiyor.[/red]")
        wait_enter()
        return

    imported, skipped = [], 0
    try:
        for raw_name, raw_songs in list(data.items())[:MAX_IMPORT_PLAYLISTS]:
            if not isinstance(raw_songs, list):
                skipped += 1
                continue
            songs = []
            for raw in raw_songs[:MAX_IMPORT_SONGS]:
                song = sanitize_song(raw)
                if song:
                    songs.append(song)
                else:
                    skipped += 1
            if not songs:
                continue
            name = clean_text(raw_name, "Bulut Listesi")[:MAX_NAME_LEN]
            final_name = playlist_manager.unique_name(name)
            count = playlist_manager.add_songs(final_name, songs)
            imported.append((final_name, count))
    except (OSError, ValueError) as e:
        logger.exception("İçe aktarılan liste kaydedilemedi")
        console.print(f"\n[red]❌ Liste kaydedilemedi: {escape(str(e))}[/red]")

    if imported:
        for name, count in imported:
            console.print(f"\n[bold green]✓ '{escape(name)}' adıyla {count} şarkı eklendi![/bold green]")
    else:
        console.print("\n[red]❌ İçe aktarılabilecek geçerli şarkı bulunamadı.[/red]")
    if skipped:
        console.print(f"[yellow]{skipped} geçersiz kayıt atlandı.[/yellow]")
    wait_enter()


def playlists_menu():
    while True:
        console.clear()
        playlists = playlist_manager.get_all()
        choices = [
            Choice("BACK", "<- Ana Menüye Dön"),
            Choice("IMPORT_CLOUD", "📥 Buluttan Liste İndir (Kısa Kod İle)"),
        ]
        if not playlists:
            console.print("[yellow]Henüz hiç çalma listeniz yok.[/yellow]")
            console.print("[dim]Arkadaşınızın listesini indirmek için aşağıdan seçebilirsiniz.[/dim]\n")
        else:
            choices += [Choice(name, f"📁 {name} ({len(songs)} Şarkı)") for name, songs in playlists.items()]

        sel = ask_select("Görüntülemek istediğiniz listeyi seçin:", choices)
        if sel == "BACK":
            return
        if sel == "IMPORT_CLOUD":
            import_playlist_cloud()
            continue
        playlist_actions(sel)


def playlist_actions(pl_name):
    while True:
        songs = playlist_manager.get_songs(pl_name)  # her turda güncel kopya
        if songs is None:
            return
        console.clear()
        if songs:
            choices = [
                Choice("PLAY", "▶ Listeyi Çal (Sırayla)"),
                Choice("SHUFFLE", "🔀 Listeyi Karışık Çal"),
                Choice("RECOMMEND", "💡 Bu Listeye Göre Akıllı Öneriler Bul (Radyo Karışımı)"),
                Choice("SHARE_CLOUD", "🚀 Bu Listeyi Paylaş (Buluta Yükle)"),
                Choice("REMOVE_SONG", "➖ Bu Listeden Belirli Şarkıyı Çıkar"),
            ]
        else:
            console.print(f"[yellow]{escape(pl_name)} listesi boş.[/yellow]\n")
            choices = []
        choices += [Choice("DELETE_LIST", "🗑️ Bu Listeyi Tamamen Sil"), Choice("BACK", "<- Playlistlere Dön")]

        act = ask_select(f"{pl_name} listesi için işlem seçin:", choices)
        try:
            if act == "BACK":
                return
            if act == "PLAY":
                play_session(songs[0], songs)
            elif act == "SHUFFLE":
                random.shuffle(songs)
                play_session(songs[0], songs)
            elif act == "RECOMMEND":
                recommend_from(songs)
            elif act == "SHARE_CLOUD":
                export_playlist_cloud(pl_name, songs)
            elif act == "REMOVE_SONG":
                remove_song_dialog(pl_name, songs)
            elif act == "DELETE_LIST":
                confirm = ask_select(
                    f"'{pl_name}' listesini tümüyle silmek istediğinize emin misiniz?",
                    [Choice(False, "❌ Hayır, İptal"), Choice(True, "✅ Evet, Komple Sil")],
                )
                if confirm:
                    playlist_manager.delete_playlist(pl_name)
                    pause_message(f"\n[bold red]🗑️ '{escape(pl_name)}' listesi tamamen silindi.[/bold red]")
                    return
        except OSError as e:
            logger.exception("Playlist kaydedilemedi")
            pause_message(f"[red]Değişiklik kaydedilemedi: {escape(str(e))}[/red]", 2)


def recommend_from(songs):
    seed = random.choice(songs)
    try:
        with console.status(
            f"[bold yellow]Akıllı öneriler hesaplanıyor... (Referans Şarkı: {escape(seed['title'])})[/bold yellow]"
        ):
            recs = api.get_recommendations(seed["videoId"])
    except MusicAPIError as e:
        pause_message(f"[red]{escape(str(e))}[/red]", 2)
        return
    if not recs:
        pause_message("[red]Öneri bulunamadı![/red]", 2)
        return
    choices = [Choice("BACK", "<- Geri Dön")]
    choices += [Choice(item, f"✨ {item['title']} - {item['artist']}") for item in recs]
    sel = ask_select("Akıllı Öneriler: Hangi şarkıdan başlamak istersiniz?", choices)
    if sel != "BACK":
        play_session(sel, recs)


def remove_song_dialog(pl_name, songs):
    choices = [Choice("BACK", "<- İptal")]
    choices += [Choice(s, f"➖ {s['title']} - {s['artist']}") for s in songs]
    song = ask_select("Silmek istediğiniz şarkıyı seçin:", choices)
    if song != "BACK" and playlist_manager.remove_song(pl_name, song["videoId"]):
        pause_message(f"\n[bold red]✓ '{escape(song['title'])}' listeden çıkarıldı![/bold red]")


def help_menu():
    console.clear()
    help_text = """[bold #2ecc71]1. Menüler Arası Gezinme[/]
- Menülerde gezinmek için [bold yellow]AŞAĞI/YUKARI yön tuşlarını[/] kullanın, seçmek için [bold yellow]ENTER[/]'a basın.
- Geri dönmek için seçeneklerdeki [bold red]"<- Geri Dön"[/] seçeneğini kullanın.

[bold #2ecc71]2. Oynatıcı Kısayolları (Müzik Çalarken)[/]
- [bold yellow]Space[/]: Durdur / Devam   [bold yellow]N[/]: Sonraki   [bold yellow]B[/]: Önceki (3 sn sonra: başa sar)
- [bold yellow]M[/]: [bold cyan]Mini Player Modu[/] (Kompakt / Tam Ekran geçişi)
- [bold yellow]C[/]: [bold cyan]Kapak Resmi Stili[/] (Gerçek Piksel / Blok yedeği <-> Braille)
- [bold yellow]← / →[/]: 5 sn geri / ileri   [bold yellow]↑ / ↓[/] (veya Y / A): Kuyruğu kaydır
- [bold yellow]+ / -[/] (veya K / J): Ses   [bold yellow]L / F[/]: Favorile   [bold yellow]P[/]: Listeye ekle
- [bold yellow]Q / Esc[/]: Oynatıcıdan çık

[bold #2ecc71]3. Kişisel Tema Editörü[/]
- Ana Menü > [bold cyan]"🎨 Tema Seçimi"[/] > [bold yellow]"➕ Yeni Tema Oluştur"[/] seçeneğini kullanarak kendi HEX kodlarınızı ve imleç simgenizi belirleyebilir, sınırsız özel tema yaratabilirsiniz!

[bold #2ecc71]4. Çalma Listesi Paylaşma ve İndirme (Bulut)[/]
- [bold white]Paylaşmak:[/] Çalma Listelerim > liste > [bold cyan]"🚀 Bu Listeyi Paylaş"[/]. Size [bold yellow]7PRHHYV94[/] gibi bir kod verilir (otomatik panoya kopyalanır).
- [bold white]İndirmek:[/] Çalma Listelerim > [bold cyan]"📥 Buluttan Liste İndir"[/] > kodu yazın.
- [dim]Not: Paylaşılan listeler herkese açık dpaste.com'da saklanır.[/dim]

[bold #2ecc71]5. Global Kısayollar (uygulama arka plandayken)[/]
- [bold yellow]Ctrl+Shift+Alt+Space[/]: Oynat/Durdur   [bold yellow]Ctrl+Shift+Alt+←/→[/]: Önceki/Sonraki
- [bold yellow]Ctrl+Shift+Alt+↑/↓[/]: Ses   [bold yellow]Ctrl+Shift+Alt+L[/]: Favorile
- Klavyedeki medya tuşları da desteklenir.
"""
    console.print(Panel(help_text, title="📖 Yardım ve Kullanım Rehberi", border_style=get_current_theme()["primary"]))
    wait_enter("Menüye dönmek için Enter'a basın...")


def main_menu():
    theme = get_current_theme()
    console.clear()
    console.print(Panel(f"[bold {theme['primary']}]Modernized CLI Player[/] - Ana Menü", border_style=theme["border"]))
    for warning in startup_warnings:
        console.print(f"[yellow]⚠ {escape(warning)}[/yellow]")
    if not player.available:
        console.print(f"[bold red]⚠ {escape(player.last_error or 'VLC kullanılamıyor.')}[/bold red]")

    cover_style_label = "Gerçek Piksel (Otomatik)" if app_settings.get("cover_style") == "block" else "Braille (Nokta)"
    choices = [
        Choice("SEARCH", "🎵 Şarkı veya Sanatçı Ara"),
        Choice("PLAYLISTS", "📂 Çalma Listelerim (Playlists)"),
        Choice("THEME", f"🎨 Tema Seçimi & Editörü (Mevcut: {app_settings['theme']})"),
        Choice("TOGGLE_COVER", f"🖼️ Kapak Resmi Stili: {cover_style_label}"),
        Choice("TOGGLE_NORM", f"🎧 Ses Eşitleme (Normalizasyon): {'AÇIK' if app_settings['normalization'] else 'KAPALI'}"),
        Choice("TOGGLE_NOTIFS", f"🔔 Bildirimler: {'AÇIK' if app_settings['notifications_enabled'] else 'KAPALI'}"),
        Choice("HELP", "📖 Yardım & Kullanım Rehberi"),
        Choice("QUIT", "❌ Çıkış"),
    ]
    sel = ask_select("Ne yapmak istersiniz?", choices)

    if sel == "SEARCH":
        search_menu()
    elif sel == "PLAYLISTS":
        playlists_menu()
    elif sel == "THEME":
        theme_menu()
    elif sel == "TOGGLE_COVER":
        cur = app_settings.get("cover_style", "block")
        new_style = "braille" if cur == "block" else "block"
        app_settings["cover_style"] = new_style
        save_settings()
        label = "Gerçek Piksel (Sixel destekli terminalde)" if new_style == "block" else "Retro Braille (Nokta Matris)"
        pause_message(f"\n[green]✓ Kapak görünümü '{label}' olarak ayarlandı![/green]", 1)
    elif sel == "TOGGLE_NORM":
        app_settings["normalization"] = not app_settings["normalization"]
        save_settings()
        player.set_normalization(app_settings["normalization"])
    elif sel == "TOGGLE_NOTIFS":
        app_settings["notifications_enabled"] = not app_settings["notifications_enabled"]
        save_settings()
    elif sel == "HELP":
        help_menu()
    elif sel == "QUIT":
        return False
    return True


# --------------------------------------------------------------------------- yaşam döngüsü
def init_app():
    global api, player, playlist_manager, app_settings
    setup_logging()
    app_settings = load_settings()
    playlist_manager = PlaylistManager()
    api = MusicAPI()
    player = PlayerService(normalization=app_settings["normalization"], volume=app_settings["volume"])
    setup_global_hotkeys()


def shutdown():
    if player is not None:
        player.close()
    if keyboard:
        try:
            keyboard.unhook_all()
        except Exception:
            pass
    shutil.rmtree(ICON_DIR, ignore_errors=True)


def main():
    init_app()
    try:
        while True:
            try:
                if not main_menu():
                    break
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.exception("Beklenmeyen hata")
                console.print(f"[red]Beklenmeyen hata: {escape(str(e))}[/red]")
                console.print(f"[dim]Ayrıntılar: {LOG_FILE.name}[/dim]")
                time.sleep(2.5)
    finally:
        shutdown()
        console.print("\n[dim]Görüşmek Üzere...[/dim]")


if __name__ == "__main__":
    main()
