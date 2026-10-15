"""YouTube Music arama ve öneri servisi (ytmusicapi, API anahtarı gerektirmez)."""
import logging
import threading

from ytmusicapi import YTMusic

from song_utils import VIDEO_ID_RE, artists_to_text, make_song, upscale_thumbnail

logger = logging.getLogger(__name__)


class MusicAPIError(Exception):
    """Ağ/servis kaynaklı hatalar için kullanıcıya gösterilebilir istisna."""


class MusicAPI:
    def __init__(self):
        self._yt = None
        self._lock = threading.Lock()

    @property
    def yt(self):
        with self._lock:
            if self._yt is None:
                self._yt = YTMusic()
            return self._yt

    @staticmethod
    def _parse_item(item, duration_key):
        if not isinstance(item, dict):
            return None
        vid = item.get("videoId")
        title = item.get("title")
        if not isinstance(vid, str) or not VIDEO_ID_RE.match(vid) or not title:
            return None
        # search -> "thumbnails", get_watch_playlist -> "thumbnail"
        thumbs = item.get("thumbnails") or item.get("thumbnail") or []
        thumb = None
        if isinstance(thumbs, list) and thumbs and isinstance(thumbs[-1], dict):
            thumb = thumbs[-1].get("url")
        return make_song(
            vid,
            str(title),
            artists_to_text(item.get("artists")),
            str(item.get(duration_key) or ""),
            upscale_thumbnail(thumb),
        )

    def search(self, query: str, limit: int = 20):
        """Şarkı araması yapar. Ağ/servis hatasında MusicAPIError fırlatır."""
        try:
            results = self.yt.search(query, filter="songs", limit=limit) or []
        except Exception as e:
            logger.exception("Arama başarısız: %r", query)
            raise MusicAPIError(f"Arama yapılamadı ({e.__class__.__name__}). İnternet bağlantınızı kontrol edin.") from e
        parsed = [self._parse_item(item, "duration") for item in results]
        return [s for s in parsed if s][:limit]

    def get_recommendations(self, video_id: str, limit: int = 25):
        """Verilen şarkıya göre radyo/öneri listesi. Hatada MusicAPIError fırlatır."""
        try:
            res = self.yt.get_watch_playlist(videoId=video_id, limit=limit) or {}
        except Exception as e:
            logger.exception("Öneriler alınamadı: %s", video_id)
            raise MusicAPIError(f"Öneriler alınamadı ({e.__class__.__name__}).") from e
        parsed = []
        seen = {video_id}
        for item in res.get("tracks", []):
            song = self._parse_item(item, "length")
            if song and song["videoId"] not in seen:
                seen.add(song["videoId"])
                parsed.append(song)
        return parsed
