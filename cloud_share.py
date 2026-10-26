"""Çalma listelerini dpaste.com üzerinden paylaşma / içe aktarma (arayüzden bağımsız)."""
import json
import re

import requests

from song_utils import clean_text, sanitize_song

DPASTE_API = "https://dpaste.com/api/v2/"
HTTP_HEADERS = {"User-Agent": "yt-music-cli/2.0 (+https://github.com/Nazmicanyrs/YoutubeMusic-CL-)"}
SHARE_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,20}$")
DPASTE_URL_RE = re.compile(r"^https://dpaste\.com/([A-Za-z0-9]+)/?$")
MAX_IMPORT_SONGS = 5000
MAX_IMPORT_PLAYLISTS = 20
MAX_NAME_LEN = 100


class CloudShareError(Exception):
    """Kullanıcıya gösterilebilir paylaşım/içe aktarma hatası."""


def upload_playlist(name, songs):
    """Listeyi herkese açık olarak yükler ve paylaşım kodunu döndürür."""
    clean_songs = [s for s in (sanitize_song(x) for x in songs) if s]
    if not clean_songs:
        raise CloudShareError("Liste boş; paylaşılacak şarkı yok.")
    payload = json.dumps({name: clean_songs}, ensure_ascii=False)
    try:
        r = requests.post(
            DPASTE_API,
            data={"content": payload, "syntax": "json", "expiry_days": 365},
            headers=HTTP_HEADERS,
            timeout=15,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        raise CloudShareError(f"Liste paylaşılamadı: {e}") from e
    url = (r.headers.get("Location") or r.text).strip()
    m = DPASTE_URL_RE.match(url)
    if not m:
        raise CloudShareError(f"Beklenmeyen sunucu yanıtı: {url[:80]}")
    return m.group(1)


def normalize_code(raw):
    code = (raw or "").strip()
    if "dpaste.com/" in code:
        code = code.rstrip("/").split("/")[-1]
    code = code.removesuffix(".txt")
    if not SHARE_CODE_RE.match(code):
        raise CloudShareError("Geçersiz kod formatı. Kod yalnızca harf ve rakamlardan oluşmalı.")
    return code


def download_playlists(raw_code):
    """Koddan listeleri indirir. ([(ad, [şarkılar]), ...], atlanan_kayıt_sayısı) döndürür."""
    code = normalize_code(raw_code)
    try:
        r = requests.get(f"https://dpaste.com/{code}.txt", headers=HTTP_HEADERS, timeout=15)
        if r.status_code == 404:
            raise CloudShareError("Geçersiz kod veya süresi dolmuş liste!")
        r.raise_for_status()
        data = json.loads(r.text)
    except (requests.RequestException, ValueError) as e:
        raise CloudShareError(f"Liste indirilemedi (bağlantı veya veri hatası): {e}") from e

    if not isinstance(data, dict) or not data:
        raise CloudShareError("Bu kod geçerli bir çalma listesi içermiyor.")

    result, skipped = [], 0
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
        if songs:
            result.append((clean_text(raw_name, "Bulut Listesi")[:MAX_NAME_LEN], songs))
    if not result:
        raise CloudShareError("İçe aktarılabilecek geçerli şarkı bulunamadı.")
    return result, skipped
