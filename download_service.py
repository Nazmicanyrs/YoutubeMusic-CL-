"""Şarkıları yt-dlp ile indirip çevrimdışı çalmayı sağlayan servis (ffmpeg gerektirmez)."""
import logging
import threading
from pathlib import Path

import yt_dlp

from song_utils import sanitize_song
from storage import DATA_DIR, data_path, load_json, save_json_atomic

logger = logging.getLogger(__name__)

DOWNLOAD_DIR = DATA_DIR / "downloads"
INDEX_FILE = "downloads.json"


class DownloadError(Exception):
    pass


class DownloadService:
    """İndirilen şarkıların dizinini (downloads.json) ve dosyalarını yönetir."""

    def __init__(self):
        self._lock = threading.RLock()
        self.index = {}
        self._load()

    def _load(self):
        raw = load_json(data_path(INDEX_FILE), {})
        if not isinstance(raw, dict):
            return
        for vid, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            song = sanitize_song(entry.get("song"))
            file_name = entry.get("file")
            if song and isinstance(file_name, str) and (DOWNLOAD_DIR / file_name).is_file():
                self.index[song["videoId"]] = {"song": song, "file": file_name}

    def _save(self):
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        save_json_atomic(data_path(INDEX_FILE), self.index)

    def path_for(self, video_id):
        """İndirilmişse yerel dosya yolunu, değilse None döndürür."""
        with self._lock:
            entry = self.index.get(video_id)
        if not entry:
            return None
        path = DOWNLOAD_DIR / entry["file"]
        return path if path.is_file() else None

    def is_downloaded(self, video_id):
        return self.path_for(video_id) is not None

    def songs(self):
        with self._lock:
            return [dict(e["song"]) for e in self.index.values() if self.is_downloaded(e["song"]["videoId"])]

    def download(self, song, ydl_base_opts=None, progress_cb=None):
        """Şarkıyı indirir (bloklar). Yerel dosya yolunu döndürür; hatada DownloadError."""
        song = sanitize_song(song)
        if not song:
            raise DownloadError("Geçersiz şarkı kaydı.")
        vid = song["videoId"]
        existing = self.path_for(vid)
        if existing:
            return existing

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

        def hook(d):
            if progress_cb and d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    progress_cb(int(d.get("downloaded_bytes", 0) * 100 / total))

        opts = dict(ydl_base_opts or {})
        opts.update({
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": str(DOWNLOAD_DIR / f"{vid}.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "progress_hooks": [hook],
        })
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(song["url"], download=True)
                final = Path(ydl.prepare_filename(info))
        except Exception as e:
            logger.exception("İndirme başarısız: %s", vid)
            raise DownloadError(str(e)) from e
        if not final.is_file():
            matches = sorted(DOWNLOAD_DIR.glob(f"{vid}.*"))
            if not matches:
                raise DownloadError("İndirilen dosya bulunamadı.")
            final = matches[0]
        with self._lock:
            self.index[vid] = {"song": song, "file": final.name}
            try:
                self._save()
            except OSError as e:
                raise DownloadError(f"İndeks kaydedilemedi: {e}") from e
        return final

    def remove(self, video_id):
        """İndirmeyi (dosya + kayıt) siler."""
        with self._lock:
            entry = self.index.pop(video_id, None)
            if not entry:
                return False
            try:
                (DOWNLOAD_DIR / entry["file"]).unlink(missing_ok=True)
            except OSError:
                logger.warning("İndirilen dosya silinemedi: %s", entry["file"], exc_info=True)
            self._save()
            return True
