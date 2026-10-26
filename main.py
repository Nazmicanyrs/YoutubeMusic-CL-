"""YouTube Music CLI Player — terminal arayüzü ve uygulama giriş noktası."""
import os
import sys

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
import math
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

if os.name == "nt":
    import msvcrt
else:
    msvcrt = None

import requests
from PIL import Image, ImageEnhance

if sys.platform == "win32":
    try:
        from win11toast import toast
    except ImportError:
        toast = None
else:
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
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
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
HTTP_HEADERS = {"User-Agent": "yt-music-cli/2.0 (+https://github.com/Nazmicanyrs/YoutubeMusic-CL-)"}
IMAGE_HEADERS = {"User-Agent": "Mozilla/5.0"}
SHARE_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,20}$")
DPASTE_URL_RE = re.compile(r"^https://dpaste\.com/([A-Za-z0-9]+)/?$")

# --------------------------------------------------------------------------- temalar
from themes import THEMES  # CLI ve GUI için ortak tema listesi

# --------------------------------------------------------------------------- ayarlar
DEFAULT_SETTINGS = {
    "notifications_enabled": True,
    "theme": "yt-music-cli",
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
    return all_themes.get(app_settings.get("theme", "yt-music-cli"), THEMES["yt-music-cli"])


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
        settings["theme"] = "yt-music-cli"
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
def clear_screen():
    if os.name == "nt":
        os.system("cls")
    else:
        sys.stdout.write("\x1b[2J\x1b[3J\x1b[H")
        sys.stdout.flush()


def ask_select(message, choices, default=None):
    term_h = shutil.get_terminal_size((80, 24)).lines
    max_h = max(5, min(10, term_h - 10))
    return inquirer.select(
        message=message,
        choices=choices,
        default=default,
        style=get_current_style(),
        pointer=get_current_theme()["pointer"],
        wrap_lines=False,
        max_height=max_h,
        cycle=True,
    ).execute()


def wait_enter(message="Devam etmek için Enter'a basın..."):
    console.input(f"\n[dim]{escape(message)}[/dim]")


def pause_message(markup, seconds=1.5):
    console.print(markup)
    time.sleep(seconds)


def copy_to_clipboard(text):
    try:
        if sys.platform == "win32":
            subprocess.run(["clip"], input=text.encode("utf-16"), check=True, timeout=5)
            return True
        elif sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True, timeout=5)
            return True
        else:
            if shutil.which("wl-copy"):
                subprocess.run(["wl-copy"], input=text.encode("utf-8"), check=True, timeout=5)
                return True
            elif shutil.which("xclip"):
                subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode("utf-8"), check=True, timeout=5)
                return True
            elif shutil.which("xsel"):
                subprocess.run(["xsel", "--clipboard", "--input"], input=text.encode("utf-8"), check=True, timeout=5)
                return True
            return False
    except Exception:
        logger.debug("Panoya kopyalanamadı", exc_info=True)
        return False


def format_time(ms):
    s = max(0, int(ms)) // 1000
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


def get_spectrum_visualizer(width, height, is_playing, primary, accent="#FFA500"):
    if not is_playing or width <= 0 or height <= 0:
        return Text("\n".join(" " * width for _ in range(height)))

    bars = " ▂▃▄▅▆▇█"
    t = time.time() * 7.5
    lines = [[] for _ in range(height)]
    styles = [[] for _ in range(height)]
    bar_count = max(1, width // 2)

    for b in range(bar_count):
        freq_factor = (b + 1) / max(1, bar_count)
        v1 = math.sin(t * 1.4 + b * 0.4)
        v2 = math.cos(t * 0.85 - b * 0.6)
        v3 = math.sin(t * 2.2 + b * 0.22)
        envelope = math.sin(math.pi * freq_factor)
        val = ((v1 * 0.4 + v2 * 0.35 + v3 * 0.25 + 1.0) / 2.0) * (0.35 + 0.65 * envelope)
        total_units = int(val * height * 8)

        top_row = -1
        for h in range(height - 1, -1, -1):
            if total_units > h * 8:
                top_row = height - 1 - h
                break

        for h in range(height):
            row_idx = height - 1 - h
            cell_val = max(0, min(8, total_units - h * 8))
            ch = " " if cell_val == 0 else bars[cell_val - 1]
            lines[row_idx].append(ch)
            is_peak = (row_idx == top_row and cell_val > 0)
            st = f"bold {accent}" if is_peak else f"bold {primary}"
            styles[row_idx].append(st)
            if len(lines[row_idx]) < width:
                lines[row_idx].append(" ")
                styles[row_idx].append("")

    res = Text()
    for row_idx in range(height):
        line_t = Text()
        for idx_ch, ch in enumerate(lines[row_idx][:width]):
            st = styles[row_idx][idx_ch] if idx_ch < len(styles[row_idx]) else ""
            line_t.append(ch, style=st)
        res.append_text(line_t)
        if row_idx < height - 1:
            res.append("\n")
    return res


def get_visualizer(width, is_playing, primary, accent="#FFA500"):
    return get_spectrum_visualizer(width, 2, is_playing, primary, accent)


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
    if not app_settings.get("notifications_enabled", True):
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

        title = "🎵 Şimdi Çalıyor"
        msg = f"{song['title']}\n{song['artist']}"

        if sys.platform == "win32" and toast is not None:
            toast(title, msg, icon=icon, app_id="yt-music-cli")
        elif sys.platform == "darwin":
            safe_title = title.replace('"', '\\"')
            safe_msg = msg.replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e", f'display notification "{safe_msg}" with title "{safe_title}"'],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform.startswith("linux"):
            cmd = ["notify-send", title, msg]
            if icon and os.path.exists(icon):
                cmd.extend(["-i", icon])
            subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    b"l": "toggle_lyrics", b"L": "toggle_lyrics",
    b"f": "like", b"F": "like",
    b"s": "shuffle", b"S": "shuffle",
    b"r": "repeat", b"R": "repeat",
    b"v": "vol_cycle", b"V": "vol_cycle",
    b"?": "help", b"h": "help", b"H": "help",
    b"p": "playlist", b"P": "playlist",
    b"\t": "toggle_lyrics",
    b"+": "vol_up", b"=": "vol_up",
    b"-": "vol_down", b"_": "vol_down",
    b"k": "scroll_up", b"K": "scroll_up",
    b"j": "scroll_down", b"J": "scroll_down",
    b"y": "scroll_up", b"Y": "scroll_up", b"a": "scroll_down", b"A": "scroll_down",
    b"m": "toggle_mini", b"M": "toggle_mini",
    b"c": "toggle_cover", b"C": "toggle_cover",
}
ARROW_KEYMAP = {b"H": "scroll_up", b"P": "scroll_down", b"K": "seek_back", b"M": "seek_fwd"}


class PosixTerminalMode:
    """POSIX sistemlerde (macOS / Linux) klavye girişi için terminali cbreak/no-echo moduna alır."""

    def __init__(self):
        self.fd = None
        self.old_settings = None

    def __enter__(self):
        if os.name != "nt":
            try:
                if sys.stdin.isatty():
                    import termios
                    self.fd = sys.stdin.fileno()
                    self.old_settings = termios.tcgetattr(self.fd)
                    new_settings = termios.tcgetattr(self.fd)
                    new_settings[3] = new_settings[3] & ~termios.ECHO & ~termios.ICANON
                    termios.tcsetattr(self.fd, termios.TCSANOW, new_settings)
            except Exception:
                self.old_settings = None
        return self

    def __exit__(self, *args):
        self.restore()

    def restore(self):
        if self.fd is not None and self.old_settings is not None:
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass
            self.old_settings = None


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
        self.shuffle_mode = False
        self.repeat_mode = "none"
        self.show_lyrics = False

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
        theme = get_current_theme()
        primary = theme["primary"]
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
        elif action == "vol_cycle":
            cur_v = player.get_volume()
            new_v = 100 if cur_v >= 95 else cur_v + 10
            player.set_volume(new_v)
            self.flash(f"🔊 Ses: %{new_v}", f"bold {primary}", seconds=1.5)
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
        elif action == "shuffle":
            self.shuffle_mode = not getattr(self, "shuffle_mode", False)
            if self.shuffle_mode:
                cur_song = self.song
                remaining = [s for i, s in enumerate(self.queue) if i != self.idx]
                random.shuffle(remaining)
                self.queue = [cur_song] + remaining
                self.idx = 0
                self.scroll_offset = 0
                self.flash("🔀 Karışık Çalma: AÇIK", f"bold {primary}", seconds=2.0)
            else:
                self.flash("▶ Sıralı Çalma: AÇIK", "dim white", seconds=2.0)
        elif action == "repeat":
            modes = ["none", "all", "one"]
            cur = getattr(self, "repeat_mode", "none")
            nxt = modes[(modes.index(cur) + 1) % len(modes)]
            self.repeat_mode = nxt
            lbl = "KAPALI" if nxt == "none" else ("TÜMÜ" if nxt == "all" else "TEK ŞARKI")
            self.flash(f"🔁 Tekrar Modu: {lbl}", f"bold {primary}", seconds=2.0)
        elif action == "toggle_lyrics":
            self.show_lyrics = not getattr(self, "show_lyrics", False)
            lbl = "Şarkı Sözleri" if self.show_lyrics else "Çalma Listesi"
            self.flash(f"📑 Görünüm: {lbl}", f"bold {primary}", seconds=1.5)
        elif action == "help":
            self.flash("Kısayollar: Space:Dur/Oynat N/B:İleri/Geri S:Karıştır R:Tekrar L:Sözler V:Ses M:Mini Q:Çık", f"bold {primary}", seconds=4.0)
        elif action == "toggle_mini":
            self.mini_mode = not self.mini_mode
            label = "Kompakt (Mini)" if self.mini_mode else "Tam Ekran"
            self.flash(f"📺 Görünüm: {label}", f"bold {primary}", seconds=1.5)
        elif action == "toggle_cover":
            cur = app_settings.get("cover_style", "block")
            new_style = "braille" if cur == "block" else "block"
            app_settings["cover_style"] = new_style
            save_settings()
            self._art_cache.clear()
            label = "Gerçek Piksel (Sixel)" if new_style == "block" and self.graphics.sixel else ("Renkli Blok" if new_style == "block" else "Retro Braille")
            self.flash(f"🖼️ Kapak: {label}", f"bold {primary}", seconds=2.0)
        return None

    @staticmethod
    def read_key():
        if PENDING_KEYS:
            ch = PENDING_KEYS.popleft()
            return KEYMAP.get(ch)

        if os.name == "nt":
            if msvcrt is None or not msvcrt.kbhit():
                return None
            ch = msvcrt.getch()
            if ch in (b"\x00", b"\xe0"):  # yön/fonksiyon tuşları iki bayt gönderir
                return ARROW_KEYMAP.get(PENDING_KEYS.popleft() if PENDING_KEYS else msvcrt.getch())
            return KEYMAP.get(ch)
        else:
            # POSIX (macOS, Linux)
            import select
            try:
                if not sys.stdin.isatty():
                    return None
                fd = sys.stdin.fileno()
                r, _, _ = select.select([fd], [], [], 0)
                if not r:
                    return None
                ch = os.read(fd, 1)
                if not ch:
                    return None
                if ch == b"\x1b":
                    # Escape veya ANSI sequence kontrolü
                    r2, _, _ = select.select([fd], [], [], 0.05)
                    if r2:
                        seq = os.read(fd, 2)
                        # Yukarı ok: \x1b[A veya \x1bOA
                        # Aşağı ok:  \x1b[B veya \x1bOB
                        # Sağ ok:    \x1b[C veya \x1bOC
                        # Sol ok:    \x1b[D veya \x1bOD
                        if seq in (b"[A", b"OA"):
                            return "scroll_up"
                        elif seq in (b"[B", b"OB"):
                            return "scroll_down"
                        elif seq in (b"[C", b"OC"):
                            return "seek_fwd"
                        elif seq in (b"[D", b"OD"):
                            return "seek_back"
                        return None
                    return "quit"
                return KEYMAP.get(ch)
            except Exception:
                return None

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
            if getattr(self, "repeat_mode", "none") == "one":
                self.start_track()
                return None
            if self.idx + 1 < len(self.queue):
                self.go(1)
                return None
            if getattr(self, "repeat_mode", "none") == "all" and self.queue:
                self.idx = 0
                self.start_track()
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
        term_mode = PosixTerminalMode()
        try:
            display = (SixelLive(self.render(), console, lambda: self._pixel_cover)
                       if self.graphics.sixel else
                       Live(self.render(), console=console, refresh_per_second=10, screen=True))
            last_size = console.size
            with term_mode, display as live:
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
                        term_mode.restore()
                        try:
                            add_to_playlist_dialog(self.song)
                        finally:
                            ACTION_QUEUE.clear()
                            HOTKEYS_ACTIVE.set()
                            term_mode.__enter__()
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
            term_mode.restore()
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
            lines[1] = Text("     ⏳ Şarkı sözleri aranıyor...", style="dim yellow")
        elif status:
            lines[1] = Text(f"     💬 {status}", style="dim")
        elif lyrics:
            i = bisect_right(times, now_ms + 300) - 1
            if i < 0:
                lines[1] = Text("     🎵 ...", style="dim")
            else:
                if i > 0:
                    lines[0] = Text(f"     {lyrics[i - 1][1]}", style="dim white")
                cur = lyrics[i][1]
                start = lyrics[i][0]
                end = lyrics[i + 1][0] if i + 1 < len(lyrics) else start + 4000
                progress = max(0.0, min(1.0, (now_ms - start + 300) / max(1, end - start)))
                n = int(len(cur) * progress)
                pulse = "🎤" if (now_ms // 400) % 2 == 0 else "🎶"
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

        accent = theme.get("accent", "#FFA500")

        # Satır 1: Başlık, Sanatçı, İndikatörler
        line1 = Text(no_wrap=True, overflow="ellipsis")
        pulse = "▶" if state == "playing" else ("⏸" if state == "paused" else "⏳")
        line1.append(f"{pulse} ", style=f"bold {accent}")
        line1.append(song["title"].upper(), style=f"bold {primary}")
        line1.append(f" — {song['artist']}", style="bold white")
        line1.append(f"  [TRACK {idx + 1:02d}/{len(self.queue):02d}]", style="dim #50768C")
        if is_liked:
            line1.append("  ❤️ Favori", style="bold red")
        if loading:
            line1.append("  [⏳ LOADING]", style=f"bold {accent}")
        elif error:
            line1.append(f"  [⚠ {error[:30]}]", style="bold red")
        elif self.flash_msg and time.time() < self.flash_msg[2]:
            line1.append(f"  [{self.flash_msg[0]}]", style=self.flash_msg[1])

        # Satır 2: İlerleme Çubuğu + Zaman + Ses
        bar_len = max(10, inner_w - 38)
        ratio = min(1.0, now_ms / total) if total > 0 else 0.0
        pct = int(ratio * 100)
        filled = min(bar_len - 1, int(bar_len * ratio))
        line2 = Text(no_wrap=True, overflow="crop")
        line2.append(f"{format_time(now_ms)} ", style=f"bold {primary}")
        line2.append("━" * filled, style=primary)
        line2.append("●", style=f"bold {accent}")
        line2.append("─" * max(0, bar_len - filled - 1), style="dim #1A3B54")
        line2.append(f" {format_time(total)} ({pct}%)", style="dim #50768C")
        line2.append(f"  (VOL {vol}%)", style=f"bold {primary}")

        # Satır 3: Kontroller
        line3 = Text(
            "[SPACE] PLAY/PAUSE  [N] NEXT  [B] PREV  [←/→] ±5s  [+/-] VOL  [M] EXPAND  [Q] QUIT",
            style="dim #50768C", no_wrap=True, overflow="ellipsis", justify="center"
        )

        mini_content = Text("\n").join([line1, line2, line3])
        return Panel(
            mini_content,
            title=f"[bold {primary}]yt-music-cli MINI DECK[/]",
            title_align="left",
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
        accent = theme.get("accent", "#FFA500")
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
        header_h, footer_h = 2, 2
        bottom_h = 7 if inner_h >= 28 else (5 if inner_h >= 25 else 0)
        main_h = max(6, inner_h - header_h - bottom_h - footer_h)
        title_h = 6
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

        vol = player.get_volume()

        # ---- 1. ÜST BİLGİ ŞERİDİ (MELODY//01 HEADER)
        cur_time = time.strftime("%H:%M")
        track_num = f"TRACK {idx + 1:02d}/{len(self.queue):02d}"

        header_grid = Table.grid(expand=True)
        header_grid.add_column(justify="left", ratio=7)
        header_grid.add_column(justify="right", ratio=3)

        header_left = Text(no_wrap=True)
        header_left.append("yt-music-cli  ", style=f"bold {primary}")
        header_left.append("|  ", style="dim #1A3B54")
        header_left.append(f"{track_num}  ", style="white")
        header_left.append("|  ", style="dim #1A3B54")
        header_left.append("FLAC  |  44.1 kHz  |  STEREO  |  ", style="dim #50768C")
        if loading:
            header_left.append(" [ ⏳ LOADING ] ", style=f"bold black on {accent}")
        elif state == "paused":
            header_left.append(" [ ⏸ PAUSED ] ", style=f"bold {accent} on #1C1917")
        else:
            header_left.append(" [ ● PLAYING ] ", style=f"bold {accent} on #1F1608")

        header_right = Text(no_wrap=True, justify="right")
        header_right.append(f"{cur_time}  ", style="bold #50768C")

        header_grid.add_row(header_left, header_right)
        header_grid.add_row(Text(""), Text(""))

        # ---- 2. SOL PANEL: DETAY KARTI (TRACK METADATA)
        title_t = Text()
        title_t.append(f"{song['title'].upper()}\n", style=f"bold {primary}")
        title_t.append(f"{song['artist']}\n", style="bold white")
        album_name = song.get("album") or ("Sevgi Duvarı" if "Ahmet Kaya" in song.get("artist", "") else "YouTube Music Deck")
        title_t.append(f"{album_name}\n", style="#38BDF8")
        genre_year = "1994 / Türk Halk Müziği" if "Ahmet Kaya" in song.get("artist", "") else "Popüler Akış / HQ Audio"
        title_t.append(f"{genre_year}\n", style="dim #50768C")
        title_t.append("FLAC / 965 kbps", style="dim #50768C")
        if error:
            title_t.append(f"\n⚠ {error[:40]}", style="bold red")
        elif self.flash_msg and time.time() < self.flash_msg[2]:
            title_t.append(f"\n{self.flash_msg[0]}", style=self.flash_msg[1])

        # ---- 3. SAĞ PANEL: ÇALMA LİSTESİ (QUEUE)
        if self.show_lyrics:
            lyric_lines = self._lyrics_lines(now_ms, primary, lyrics, times, lyrics_status, lyrics_fetching)
            queue_panel = Panel(
                Text("\n\n").join(lyric_lines),
                title=f"[bold {primary}]🎤 KARAOKE LYRICS[/]",
                border_style=theme["border"],
                box=box.ROUNDED,
                padding=(1, 2),
            )
        else:
            queue_table = Table(
                box=None,
                expand=True,
                show_header=True,
                header_style="bold #50768C",
                pad_edge=False,
            )
            queue_table.add_column("-", justify="center", width=4)
            queue_table.add_column("#", justify="left", width=5)
            queue_table.add_column("TITLE", ratio=6, no_wrap=True, overflow="ellipsis")
            queue_table.add_column("DURATION", justify="right", width=9)

            self.visible_items = max(1, main_h - 4)
            max_off = max(0, len(self.queue) - self.visible_items)
            self.scroll_offset = max(0, min(max_off, self.scroll_offset))
            start_i = self.scroll_offset
            end_i = min(len(self.queue), start_i + self.visible_items)

            for i in range(start_i, end_i):
                current = i == idx
                q_song = self.queue[i]
                dur = q_song.get("duration") or format_time(parse_duration_ms(q_song.get("duration")))
                if current:
                    queue_table.add_row(
                        Text("NOW", style=f"bold black on {primary}"),
                        f"▶ {i + 1:02d}",
                        f"[bold white]{q_song['title']}[/]",
                        f"[bold {primary}]{dur}[/]",
                        style="bold on #0E2938"
                    )
                else:
                    queue_table.add_row(
                        " ",
                        f"  {i + 1:02d}",
                        f"[dim white]{q_song['title']}[/]",
                        f"[dim #50768C]{dur}[/]",
                    )

            queue_panel = Panel(
                queue_table,
                title=f"[bold {primary}]QUEUE / {len(self.queue)}[/]",
                title_align="left",
                border_style=theme["border"],
                box=box.ROUNDED,
                padding=(0, 1),
            )

        # ---- 4. ALT DECK PANEL: İLERLEME + DUAL-TONE SPEKTRUM + KONTROLLER
        if bottom_h:
            # İlerleme Çubuğu
            bar_table = Table.grid(expand=True)
            bar_table.add_column(justify="left", width=7)
            bar_table.add_column(justify="center", ratio=1)
            bar_table.add_column(justify="right", width=8)

            elapsed_text = Text(format_time(now_ms), style=f"bold {primary}")

            slider_w = max(10, inner_w - 24)
            ratio = min(1.0, now_ms / total) if total > 0 else 0.0
            filled = min(slider_w - 1, int(slider_w * ratio))
            slider_text = Text(no_wrap=True)
            slider_text.append("━" * filled, style=primary)
            slider_text.append("●", style=f"bold {accent}")
            slider_text.append("─" * max(0, slider_w - filled - 1), style="dim #1A3B54")

            total_text = Text(format_time(total), style="dim #50768C")
            bar_table.add_row(elapsed_text, slider_text, total_text)

            # Dual-Tone Ekolayzır
            spec_w = max(10, inner_w - 6)
            spec_h = max(1, bottom_h - 4) if bottom_h >= 6 else max(1, bottom_h - 3)
            spec_text = get_spectrum_visualizer(spec_w, spec_h, state == "playing", primary, accent)

            # Deck Kontrolleri (Ses Seviyesi & Modlar)
            deck_bar = Table.grid(expand=True)
            deck_bar.add_column(justify="left", ratio=5)
            deck_bar.add_column(justify="center", ratio=3)
            deck_bar.add_column(justify="center", ratio=3)

            vol_segments = min(20, max(6, inner_w // 6))
            filled_vol = int((vol / 100.0) * vol_segments)
            vol_ctrl = Text()
            vol_ctrl.append("|   VOL  ", style="dim #50768C")
            vol_ctrl.append(f"{vol}%  ", style=f"bold {primary}")
            vol_ctrl.append("█" * filled_vol, style=f"bold {primary}")
            vol_ctrl.append("░" * max(0, vol_segments - filled_vol), style="dim #1A3B54")
            vol_ctrl.append("   |", style="dim #50768C")

            repeat_mode = getattr(self, "repeat_mode", "none")
            rep_label = "ALL" if repeat_mode == "all" else ("ONE" if repeat_mode == "one" else "OFF")
            rep_style = f"bold {accent}" if repeat_mode != "none" else "dim #50768C"
            rep_ctrl = Text()
            rep_ctrl.append("REPEAT  ", style="dim #50768C")
            rep_ctrl.append(rep_label, style=rep_style)
            rep_ctrl.append("   |", style="dim #50768C")

            shuffle_mode = getattr(self, "shuffle_mode", False)
            shuf_label = "ON" if shuffle_mode else "OFF"
            shuf_style = f"bold {accent}" if shuffle_mode else "dim #50768C"
            shuf_ctrl = Text()
            shuf_ctrl.append("SHUFFLE  ", style="dim #50768C")
            shuf_ctrl.append(shuf_label, style=shuf_style)
            shuf_ctrl.append("   |", style="dim #50768C")

            deck_bar.add_row(vol_ctrl, shuf_ctrl, rep_ctrl)

            bottom_content = Group(bar_table, spec_text, deck_bar)
            bottom_panel = Panel(bottom_content, border_style=theme["border"], box=box.ROUNDED, padding=(0, 1))

        # ---- 5. ALT KISAYOL TUŞLARI (FOOTER)
        footer_table = Table.grid(expand=True)
        footer_table.add_column(justify="left", ratio=8)
        footer_table.add_column(justify="right", ratio=2)

        keys_text = Text()
        legend = [
            ("SPACE", "PLAY/PAUSE"),
            ("J/K", "MOVE"),
            ("ENTER", "PLAY"),
            ("TAB", "VIEW"),
            ("?", "HELP"),
            ("Q", "QUIT"),
        ]
        for key_b, desc in legend:
            keys_text.append(f"[{key_b}] ", style=f"bold {primary}")
            keys_text.append(f"{desc}   ", style="dim white")

        ver_text = Text("| yt-music-cli  v1.0.0", style="dim #50768C")
        footer_table.add_row(keys_text, ver_text)

        # ---- 6. TÜM YERLEŞİM BİRLEŞİMİ
        parts = [
            Layout(header_grid, name="header", size=header_h),
            Layout(name="main", size=main_h),
        ]
        if bottom_h:
            parts.append(Layout(bottom_panel, name="bottom", size=bottom_h))
        parts.append(Layout(footer_table, name="footer", size=footer_h))

        layout = Layout()
        layout.split_column(*parts)
        layout["main"].split_row(Layout(name="left", ratio=4), Layout(queue_panel, name="right", ratio=6))
        layout["left"].split_column(
            Layout(Text(" ") if self._pixel_cover else self._art_renderable(cover, art_w), name="art", size=art_rows),
            Layout(title_t, name="title"),
        )
        return Panel(
            layout,
            title=f"[bold {primary}]NOW PLAYING DECK[/]",
            title_align="left",
            border_style=theme["border"],
            box=box.ROUNDED,
            padding=(1, 2),
        )


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
    clear_screen()
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
    clear_screen()
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
        clear_screen()
        cur_theme = app_settings.get("theme", "yt-music-cli")
        all_themes = get_all_themes()
        custom_dict = app_settings.get("custom_themes", {})
        th = get_current_theme()

        # Theme Showcase Table
        table = Table(
            title=f"🎨 Tema Galerisi (Aktif: [bold {th['primary']}]{cur_theme}[/])",
            border_style=th["border"],
            box=box.ROUNDED,
            header_style=f"bold {th['primary']}",
            expand=True,
        )
        table.add_column("Durum", width=8, justify="center")
        table.add_column("Tema Adı", style="bold white", ratio=3)
        table.add_column("Ana Vurgu Rengi", ratio=3)
        table.add_column("Kenarlık Rengi", ratio=3)
        table.add_column("İmleç", width=6, justify="center")

        for name, data in all_themes.items():
            is_active = name == cur_theme
            active_mark = "[bold green]✓ AKTİF[/]" if is_active else ""
            p_col = data["primary"]
            b_col = data.get("border", "#555555")
            table.add_row(
                active_mark,
                f"[{p_col} bold]{name}[/]" if is_active else name,
                f"[{p_col}]██████[/] {p_col}",
                f"[{b_col}]██████[/] {b_col}",
                data.get("pointer", "> "),
            )
        console.print(table)
        console.print()

        choices = [
            Choice("BACK", "⬅️  Ana Menüye Dön (Geri)"),
            Choice("CREATE", "➕ Yeni Tema Oluştur (Özel Renkler & HEX)"),
        ]
        if custom_dict:
            choices.append(Choice("DELETE", "🗑️ Özel Temayı Sil"))

        for k in THEMES:
            prefix = "✓ " if k == cur_theme else "  "
            choices.append(Choice(k, f"{prefix}🎨 {k}"))

        if custom_dict:
            for k in custom_dict:
                prefix = "✓ " if k == cur_theme else "  "
                choices.append(Choice(k, f"{prefix}✨ {k} [Özel Tema]"))

        choices.append(Choice("BACK", "⬅️  Ana Menüye Dön (Geri)"))

        sel = ask_select("Etkinleştirmek istediğiniz temayı seçin:", choices)
        if not sel or sel == "BACK":
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
    clear_screen()
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
    primary = theme["primary"]
    clear_screen()

    # Arama Başlığı ve Son Aramalar
    hist = load_history()
    header_content = Table.grid(expand=True)
    header_content.add_column()
    header_content.add_row(f"[bold {primary}]🎵 Canlı Müzik Arama & Keşif[/]")
    if hist:
        chips = "   ".join(f"[dim white]•[/] [bold {primary}]{escape(h)}[/]" for h in hist[:5])
        header_content.add_row(f"[dim]Son Aramalar:[/] {chips}")

    console.print(Panel(header_content, border_style=theme["border"], box=box.ROUNDED, padding=(1, 2)))

    query = inquirer.text(
        message="Şarkı veya sanatçı arayın (Çıkmak için boş bırakın):",
        completer=WordCompleter(hist, ignore_case=True, sentence=True),
        style=get_current_style(),
    ).execute().strip()
    if not query:
        return

    save_history(query)
    try:
        with console.status(f"[bold yellow]YouTube Music taranıyor: '{escape(query)}'...[/bold yellow]"):
            results = api.search(query)
    except MusicAPIError as e:
        pause_message(f"[red]{escape(str(e))}[/red]", 3)
        return

    if not results:
        pause_message("[red]Sonuç bulunamadı.[/red]", 2)
        return

    while True:
        clear_screen()
        table = Table(
            title=f"🔎 Arama Sonuçları: '{escape(query)}' ({len(results)} Parça)",
            border_style=theme["border"],
            box=box.ROUNDED,
            header_style=f"bold {primary}",
            expand=True,
        )
        table.add_column("#", style="dim", width=4, justify="right")
        table.add_column("Şarkı Başlığı", style="bold white", ratio=4)
        table.add_column("Sanatçı", style="dim white", ratio=3)
        table.add_column("Süre", style=f"bold {primary}", width=10, justify="center")

        for idx, item in enumerate(results, 1):
            dur = item.get("duration") or "--:--"
            table.add_row(str(idx), item["title"], item["artist"], dur)
        console.print(table)
        console.print()

        choices = [
            Choice("PLAY_ALL", f"▶ Tüm Sonuçları Sırayla Çal ({len(results)} Şarkı)"),
            Choice("SHUFFLE_ALL", f"🔀 Tüm Sonuçları Karışık Çal ({len(results)} Şarkı)"),
        ]
        choices += [Choice(item, f"{idx}. {item['title']} — {item['artist']}") for idx, item in enumerate(results, 1)]
        choices.append(Choice("BACK", "<- Yeni Arama Yap / Geri Dön"))

        sel = ask_select("Dinlemek veya işlem yapmak için seçim yapın:", choices)
        if sel == "BACK":
            return
        elif sel == "PLAY_ALL":
            play_session(results[0], results)
            return
        elif sel == "SHUFFLE_ALL":
            shuffled = list(results)
            random.shuffle(shuffled)
            play_session(shuffled[0], shuffled)
            return
        else:
            clear_screen()
            action_choices = [
                Choice("PLAY_FROM_HERE", "▶ Bu Şarkıdan İtibaren Çal (Tüm Listeyle)"),
                Choice("PLAY_ONLY", "🎯 Yalnızca Bu Şarkıyı Çal"),
                Choice("ADD_TO_PL", "➕ Çalma Listesine Ekle"),
                Choice("RADIO", "💡 Bu Şarkıya Göre Akıllı Öneriler Bul (Radyo)"),
                Choice("CANCEL", "<- Sonuç Listesine Dön"),
            ]
            act = ask_select(f"'{sel['title']}' için yapılacak işlem:", action_choices)
            if act == "CANCEL":
                continue
            elif act == "PLAY_FROM_HERE":
                play_session(sel, results)
                return
            elif act == "PLAY_ONLY":
                play_session(sel, [sel])
                return
            elif act == "ADD_TO_PL":
                add_to_playlist_dialog(sel)
            elif act == "RADIO":
                recommend_from([sel])
                return


def export_playlist_cloud(pl_name, songs):
    theme = get_current_theme()
    clear_screen()
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
    clear_screen()
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
        clear_screen()
        theme = get_current_theme()
        primary = theme["primary"]
        playlists = playlist_manager.get_all()

        table = Table(
            title="📂 Çalma Listelerim (Playlists)",
            border_style=theme["border"],
            box=box.ROUNDED,
            header_style=f"bold {primary}",
            expand=True,
        )
        table.add_column("Çalma Listesi", style="bold white", ratio=4)
        table.add_column("Şarkı Sayısı", style=f"bold {primary}", width=15, justify="center")
        table.add_column("Tür / Durum", style="dim", width=20, justify="center")

        total_songs = 0
        if playlists:
            for name, s_list in playlists.items():
                count = len(s_list)
                total_songs += count
                is_fav = name == FAVORITES
                kind = "❤️ Özel Favoriler" if is_fav else "📁 Kullanıcı Listesi"
                table.add_row(f"{'⭐' if is_fav else '📁'} {name}", f"{count} Şarkı", kind)
            console.print(table)
            console.print(f"[dim]  Toplam {len(playlists)} liste, {total_songs} kayıtlı şarkı[/dim]\n")
        else:
            console.print(Panel(
                "[yellow]Henüz hiç çalma listeniz yok.[/yellow]\n[dim]Yeni bir liste oluşturabilir veya arkadaşınızın bulut listesini indirebilirsiniz.[/dim]",
                title="📂 Çalma Listeleri Boş",
                border_style="yellow",
                box=box.ROUNDED,
            ))
            console.print()

        choices = [
            Choice("NEW_PLAYLIST", "➕ Yeni Bir Çalma Listesi Oluştur"),
            Choice("IMPORT_CLOUD", "📥 Buluttan Liste İndir (Kısa Kod İle)"),
        ]
        if playlists:
            choices += [Choice(name, f"🎵 {name} ({len(songs)} Şarkı)") for name, songs in playlists.items()]
        choices.append(Choice("BACK", "<- Ana Menüye Dön"))

        sel = ask_select("Görüntülemek istediğiniz listeyi seçin:", choices)
        if sel == "BACK":
            return
        if sel == "NEW_PLAYLIST":
            new_name = ask_playlist_name()
            if new_name:
                try:
                    playlist_manager.create_playlist(new_name)
                    pause_message(f"\n[green]✓ '{new_name}' çalma listesi oluşturuldu![/green]", 1.2)
                except Exception as e:
                    pause_message(f"[red]Liste oluşturulamadı: {escape(str(e))}[/red]", 2)
            continue
        if sel == "IMPORT_CLOUD":
            import_playlist_cloud()
            continue
        playlist_actions(sel)


def playlist_actions(pl_name):
    while True:
        songs = playlist_manager.get_songs(pl_name)  # her turda güncel kopya
        if songs is None:
            return
        clear_screen()
        theme = get_current_theme()
        primary = theme["primary"]

        if songs:
            table = Table(
                title=f"📁 Liste: '{escape(pl_name)}' ({len(songs)} Şarkı)",
                border_style=theme["border"],
                box=box.ROUNDED,
                header_style=f"bold {primary}",
                expand=True,
            )
            table.add_column("#", style="dim", width=4, justify="right")
            table.add_column("Şarkı Başlığı", style="bold white", ratio=4)
            table.add_column("Sanatçı", style="dim white", ratio=3)
            table.add_column("Süre", style=f"bold {primary}", width=10, justify="center")

            preview_count = min(10, len(songs))
            for i in range(preview_count):
                s = songs[i]
                dur = s.get("duration") or "--:--"
                table.add_row(str(i + 1), s["title"], s["artist"], dur)
            if len(songs) > preview_count:
                table.add_row("...", f"[dim]+{len(songs) - preview_count} parça daha[/dim]", "", "")
            console.print(table)
            console.print()

            choices = [
                Choice("PLAY", f"▶ Listeyi Çal ({len(songs)} Şarkı Sırayla)"),
                Choice("SHUFFLE", "🔀 Listeyi Karışık Çal (Shuffle)"),
                Choice("RECOMMEND", "💡 Bu Listeye Göre Akıllı Öneriler Bul (Radyo Karışımı)"),
                Choice("SHARE_CLOUD", "🚀 Bu Listeyi Paylaş (Buluta Yükle)"),
                Choice("REMOVE_SONG", "➖ Bu Listeden Belirli Şarkıyı Çıkar"),
            ]
        else:
            console.print(Panel(
                f"[yellow]'{escape(pl_name)}' listesi şu an boş.[/yellow]\n[dim]Şarkı ararken [P] tuşuna basarak veya Arama Menüsünden buraya şarkı ekleyebilirsiniz.[/dim]",
                title=f"📁 {escape(pl_name)}",
                border_style="yellow",
                box=box.ROUNDED,
            ))
            console.print()
            choices = []

        if pl_name != FAVORITES:
            choices.append(Choice("DELETE_LIST", "🗑️ Bu Listeyi Tamamen Sil"))
        choices.append(Choice("BACK", "<- Playlistlere Dön"))

        act = ask_select(f"'{pl_name}' listesi için işlem seçin:", choices)
        try:
            if act == "BACK":
                return
            if act == "PLAY":
                play_session(songs[0], songs)
            elif act == "SHUFFLE":
                shuffled = list(songs)
                random.shuffle(shuffled)
                play_session(shuffled[0], shuffled)
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
    clear_screen()
    theme = get_current_theme()
    primary = theme["primary"]

    shortcuts_table = Table(
        title="⌨️ Oynatıcı Kısayolları (Müzik Çalarken)",
        border_style=theme["border"],
        box=box.ROUNDED,
        header_style=f"bold {primary}",
        expand=True,
    )
    shortcuts_table.add_column("Tuş", style="bold yellow", width=16, justify="center")
    shortcuts_table.add_column("İşlev Açıklaması", style="white")

    shortcuts_table.add_row("Space (Boşluk)", "Şarkıyı Durdur / Devam Ettir")
    shortcuts_table.add_row("N / B", "Sonraki Şarkı / Önceki Şarkı (3 sn sonra başa sar)")
    shortcuts_table.add_row("← / →", "5 saniye Geri / İleri Sar")
    shortcuts_table.add_row("+ / - (K / J)", "Sesi Yükselt / Azalt (%5)")
    shortcuts_table.add_row("M", "Mini Player Modu (Kompakt 3 satırlık görünüm / Tam ekran)")
    shortcuts_table.add_row("C", "Kapak Resmi Stili (Gerçek Piksel Sixel / Blok / Braille)")
    shortcuts_table.add_row("L veya F", "Şarkıyı Favorilere Ekle / Çıkar ❤️")
    shortcuts_table.add_row("P", "Şarkıyı Çalma Listesine Ekle")
    shortcuts_table.add_row("↑ / ↓ (Y / A)", "Sıradaki Parçalar Listesini Kaydır")
    shortcuts_table.add_row("Q / Esc", "Oynatıcıdan Çık ve Ana Menüye Dön")

    hotkeys_table = Table(
        title="🌐 Global Sistem Kısayolları (Uygulama Arka Plandayken)",
        border_style=theme["border"],
        box=box.ROUNDED,
        header_style=f"bold {primary}",
        expand=True,
    )
    hotkeys_table.add_column("Kısayol", style="bold cyan", width=24, justify="center")
    hotkeys_table.add_column("İşlev", style="white")
    hotkeys_table.add_row("Ctrl+Shift+Alt+Space", "Oynat / Durdur")
    hotkeys_table.add_row("Ctrl+Shift+Alt+← / →", "Önceki / Sonraki Şarkı")
    hotkeys_table.add_row("Ctrl+Shift+Alt+↑ / ↓", "Sesi Yükselt / Azalt")
    hotkeys_table.add_row("Ctrl+Shift+Alt+L", "Çalan Şarkıyı Favorile")
    hotkeys_table.add_row("Medya Tuşları", "Klavyenizdeki Oynat/Durdur/İleri/Geri tuşları")

    tips_panel = Panel(
        "• [bold white]Kapak Resmi:[/] Windows Terminal 1.22+ kullanıyorsanız albüm kapakları Sixel teknolojisiyle gerçek piksel olarak gösterilir.\n"
        "• [bold white]Bulut Paylaşımı:[/] Listelerinizi dpaste üzerinden tek tıkla paylaşabilir, arkadaşlarınızın kodlarını 'Buluttan Liste İndir' ile içe aktarabilirsiniz.\n"
        "• [bold white]Kişisel Temalar:[/] Kendi favori HEX renk kodlarınızla sınırsız özel tema yaratabilirsiniz.",
        title="💡 İpuçları & Püf Noktaları",
        border_style=primary,
        box=box.ROUNDED,
        padding=(1, 2),
    )

    console.print(shortcuts_table)
    console.print()
    console.print(hotkeys_table)
    console.print()
    console.print(tips_panel)
    wait_enter("Ana menüye dönmek için Enter'a basın...")


def render_dashboard_banner():
    theme = get_current_theme()
    primary = theme["primary"]
    accent = theme.get("accent", "#FFA500")

    playlists = playlist_manager.get_all()
    pl_count = len(playlists)
    fav_count = len(playlists.get(FAVORITES, []))
    history_count = len(load_history())

    cover_style_label = "Sixel" if app_settings.get("cover_style") == "block" else "Braille"
    norm_label = "AÇIK" if app_settings.get("normalization") else "KAPALI"
    vol = app_settings.get("volume", 90)

    header_table = Table.grid(expand=True)
    header_table.add_column(justify="left", ratio=6)
    header_table.add_column(justify="right", ratio=4)

    left_t = Text()
    left_t.append(" 🎵 yt-music-cli  ", style=f"bold {primary}")
    left_t.append("│  Hi-Fi Terminal Audio Deck  │  v2.5\n", style="dim")
    left_t.append(f" 🎨 {app_settings.get('theme')}  ", style=f"bold {primary}")
    left_t.append(f"• 🔊 %{vol}  • 🎧 Dengeleme: {norm_label}  • 🖼️ {cover_style_label}", style="dim white")

    right_t = Text(justify="right")
    right_t.append(f"📂 {pl_count} Liste  │  ❤️ {fav_count} Favori  │  🕒 {history_count} Arama\n", style="dim white")
    cur_time = time.strftime("%H:%M")
    right_t.append(f"STATUS: ONLINE  │  🕒 {cur_time} ", style=f"bold {accent}")

    header_table.add_row(left_t, right_t)
    console.print(Panel(header_table, border_style=primary, box=box.ROUNDED, padding=(0, 1)))

    for warning in startup_warnings:
        console.print(f"[yellow]⚠ {escape(warning)}[/yellow]")
    if not player.available:
        console.print(f"[bold red]⚠ {escape(player.last_error or 'VLC kullanılamıyor.')}[/bold red]")


def main_menu():
    clear_screen()
    render_dashboard_banner()

    cover_style_label = "Gerçek Piksel (Sixel)" if app_settings.get("cover_style") == "block" else "Braille (Nokta)"
    playlists = playlist_manager.get_all()
    choices = [
        Choice("SEARCH", "🎵  Şarkı veya Sanatçı Ara"),
        Choice("PLAYLISTS", f"📂  Çalma Listelerim ({len(playlists)} Liste)"),
        Choice("THEME", f"🎨  Tema Galerisi & Editörü (Aktif: {app_settings['theme']})"),
        Choice("TOGGLE_COVER", f"🖼️  Kapak Görünüm Stili: {cover_style_label}"),
        Choice("TOGGLE_NORM", f"🎧  Ses Normalizasyonu Dengeleme: {'AÇIK' if app_settings['normalization'] else 'KAPALI'}"),
        Choice("TOGGLE_NOTIFS", f"🔔  Masaüstü Bildirimleri: {'AÇIK' if app_settings['notifications_enabled'] else 'KAPALI'}"),
        Choice("HELP", "📖  Kullanım Rehberi & Kısayollar"),
        Choice("QUIT", "❌  Çıkış"),
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
