"""Şarkı verisi için ortak yardımcılar: oluşturma, doğrulama, süre ayrıştırma."""
import re

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_GOOGLE_SIZE_RE = re.compile(r"=w\d+-h\d+")
MAX_TEXT_LEN = 300


def clean_text(value, fallback):
    """Satır sonu/kontrol karakterlerini temizler, uzunluğu sınırlar."""
    if not isinstance(value, str):
        return fallback
    value = " ".join(value.split())
    return value[:MAX_TEXT_LEN] or fallback


def parse_duration_ms(value):
    """'3:45', '1:02:03', saniye (int/float) veya None değerini milisaniyeye çevirir.

    Geçersiz değerlerde istisna fırlatmak yerine 0 döner.
    """
    if value is None or value == "" or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value * 1000))
    parts = str(value).strip().split(":")
    if not 1 <= len(parts) <= 3:
        return 0
    total = 0
    try:
        for part in parts:
            n = int(part)
            if n < 0:
                return 0
            total = total * 60 + n
    except ValueError:
        return 0
    return total * 1000


def upscale_thumbnail(url, size=1024):
    """YouTube Music küçük resimlerini (genelde 120x120) daha yüksek çözünürlüğe çevirir."""
    if not url:
        return None
    if "googleusercontent.com" in url or "ggpht.com" in url:
        return _GOOGLE_SIZE_RE.sub(f"=w{size}-h{size}", url, count=1)
    return url


def artists_to_text(artists):
    names = [a.get("name") for a in (artists or []) if isinstance(a, dict) and a.get("name")]
    return ", ".join(names) if names else "Bilinmeyen Sanatçı"


def make_song(video_id, title, artist, duration, thumbnail):
    return {
        "videoId": video_id,
        "title": clean_text(title, "Bilinmeyen Şarkı"),
        "artist": clean_text(artist, "Bilinmeyen Sanatçı"),
        "duration": duration if isinstance(duration, str) and len(duration) <= 10 else "",
        # URL her zaman videoId'den üretilir; dışarıdan gelen URL'ye güvenilmez.
        "url": f"https://music.youtube.com/watch?v={video_id}",
        "thumbnail": thumbnail if isinstance(thumbnail, str) and thumbnail.startswith(("https://", "http://")) else None,
    }


def sanitize_song(data):
    """Güvenilmeyen (dosya/bulut) bir şarkı kaydını doğrular. Geçersizse None döner."""
    if not isinstance(data, dict):
        return None
    vid = data.get("videoId")
    if not isinstance(vid, str) or not VIDEO_ID_RE.match(vid):
        return None
    return make_song(vid, data.get("title"), data.get("artist"), data.get("duration"), data.get("thumbnail"))
