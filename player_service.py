"""VLC tabanlı ses oynatıcı; akış URL'leri yt-dlp ile çözülür."""
import logging
import threading

import yt_dlp

logger = logging.getLogger(__name__)

try:
    import vlc
    VLC_AVAILABLE = True
except (ImportError, FileNotFoundError, OSError):
    vlc = None
    VLC_AVAILABLE = False


class StreamError(Exception):
    pass


class YDLLogger:
    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if "No supported JavaScript runtime could be found" in msg or "challenge solver" in msg or "Signature solving failed" in msg:
            return
        logger.warning(msg)

    def error(self, msg):
        logger.error(msg)


class PlayerService:
    """Tek bir VLC media player'ı yeniden kullanır; böylece ses seviyesi vb. şarkılar arasında korunur."""

    def __init__(self, normalization=True, volume=90):
        self.ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "logger": YDLLogger(),  # ağ hataları tam ekran piksel görüntüsünün üstüne yazılmasın
            "js_runtimes": {"node": {}, "deno": {}},
        }
        self.normalization_enabled = normalization
        self.volume = self._clamp(volume)
        self.instance = None
        self.player = None
        self.last_error = None
        self._lock = threading.RLock()
        self._init_vlc()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _clamp(vol):
        try:
            return max(0, min(100, int(vol)))
        except (TypeError, ValueError):
            return 90

    @property
    def available(self):
        return self.player is not None

    def _release(self):
        with self._lock:
            if self.player is not None:
                try:
                    self.player.stop()
                    self.player.release()
                except Exception:
                    logger.debug("Player release hatası", exc_info=True)
            if self.instance is not None:
                try:
                    self.instance.release()
                except Exception:
                    logger.debug("Instance release hatası", exc_info=True)
            self.player = None
            self.instance = None

    def _init_vlc(self):
        self._release()
        if not VLC_AVAILABLE:
            self.last_error = "Sisteminizde VLC Media Player (64-bit) bulunamadı. Lütfen videolan.org'dan kurun."
            return
        args = ["--no-video", "--quiet"]
        if self.normalization_enabled:
            args.append("--audio-filter=normvol")
        try:
            instance = vlc.Instance(args)
            if instance is None:
                raise RuntimeError("vlc.Instance() None döndürdü")
            self.instance = instance
            self.player = instance.media_player_new()
            self.last_error = None
        except Exception as e:
            logger.exception("VLC başlatılamadı")
            self.instance = None
            self.player = None
            self.last_error = f"VLC başlatılamadı: {e}"

    def set_normalization(self, enabled):
        """Normalizasyon VLC instance seviyesinde olduğu için yeniden başlatma gerekir.
        Bu ayar yalnızca menüden (oynatma dururken) değiştirilir."""
        if self.normalization_enabled == enabled:
            return
        self.normalization_enabled = enabled
        self._init_vlc()

    def close(self):
        self._release()

    # --------------------------------------------------------------- playback
    def resolve(self, url: str):
        """Yavaş (ağ) işlem: (stream_url, http_headers) döndürür. Hata durumunda istisna fırlatır."""
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            raise StreamError("Akış bilgisi alınamadı.")
        stream = info.get("url")
        headers = info.get("http_headers") or {}
        if not stream:
            for fmt in info.get("requested_formats") or []:
                if fmt.get("url"):
                    stream = fmt["url"]
                    headers = fmt.get("http_headers") or headers
                    break
        if not stream:
            raise StreamError("Oynatılabilir ses akışı bulunamadı.")
        return stream, headers

    def play_stream(self, stream_url, headers=None):
        """Hızlı işlem: çözülmüş akışı çalmaya başlar. Başarı durumunu döndürür."""
        headers = headers or {}
        with self._lock:
            if not self.player:
                self.last_error = self.last_error or "VLC kullanılamıyor."
                return False
            try:
                media = self.instance.media_new(stream_url)
                ua = headers.get("User-Agent")
                if ua:
                    media.add_option(f":http-user-agent={ua}")
                ref = headers.get("Referer")
                if ref:
                    media.add_option(f":http-referrer={ref}")
                self.player.set_media(media)
                media.release()
                if self.player.play() == -1:
                    self.last_error = "VLC akışı başlatamadı."
                    return False
                self.player.audio_set_volume(self.volume)
                return True
            except Exception as e:
                logger.exception("Akış oynatılamadı")
                self.last_error = str(e)
                return False

    def play(self, url: str):
        """Geriye dönük uyumluluk: çöz + çal (bloklar)."""
        try:
            stream, headers = self.resolve(url)
        except Exception as e:
            logger.exception("Stream URL alınamadı")
            self.last_error = str(e)
            self.stop()
            return False
        return self.play_stream(stream, headers)

    def stop(self):
        with self._lock:
            if self.player:
                self.player.stop()

    def get_state(self):
        """'playing' | 'paused' | 'loading' | 'ended' | 'error' | 'stopped'"""
        if not self.player:
            return "stopped"
        st = self.player.get_state()
        S = vlc.State
        if st == S.Playing:
            return "playing"
        if st == S.Paused:
            return "paused"
        if st in (S.Opening, S.Buffering):
            return "loading"
        if st == S.Ended:
            return "ended"
        if st == S.Error:
            return "error"
        return "stopped"

    def toggle_pause(self):
        """Açık durum geçişi (VLC'nin toggle'ına güvenmeden). Yeni duraklatılma durumunu döndürür."""
        state = self.get_state()
        if state == "playing":
            self.player.set_pause(1)
            return True
        if state == "paused":
            self.player.set_pause(0)
            return False
        return state == "paused"

    def pause(self):
        self.toggle_pause()

    def is_playing(self):
        return self.get_state() == "playing"

    def seek(self, delta_ms):
        if self.get_state() not in ("playing", "paused"):
            return
        target = max(0, self.get_time() + delta_ms)
        length = self.get_length()
        if length > 0:
            target = min(target, max(0, length - 1000))
        self.player.set_time(int(target))

    def seek_to(self, ms):
        if self.get_state() in ("playing", "paused"):
            self.player.set_time(max(0, int(ms)))

    def get_time(self):
        if self.player:
            return max(0, self.player.get_time())
        return 0

    def get_length(self):
        if self.player:
            return max(0, self.player.get_length())
        return 0

    def get_volume(self):
        return self.volume

    def set_volume(self, vol):
        self.volume = self._clamp(vol)
        if self.player:
            self.player.audio_set_volume(self.volume)

    def tick(self):
        """Döngüde çağrılır: ses çıkışı geç hazır olduğunda istenen ses seviyesini yeniden uygular."""
        if self.player and self.get_state() == "playing":
            current = self.player.audio_get_volume()
            if current != -1 and current != self.volume:
                self.player.audio_set_volume(self.volume)
