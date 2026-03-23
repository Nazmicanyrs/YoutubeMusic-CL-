import yt_dlp
import time
import sys

try:
    import vlc
    VLC_AVAILABLE = True
except (ImportError, FileNotFoundError, OSError):
    VLC_AVAILABLE = False

class PlayerService:
    def __init__(self):
        self.ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extractor_args': {'youtube': ['player_client=android,web']}
        }
        self.player = None
        self.normalization_enabled = True
        self._init_vlc()
        
    def _init_vlc(self):
        if VLC_AVAILABLE:
            args = []
            if self.normalization_enabled:
                args.extend(["--audio-filter=normvol"])
            try:
                if args:
                    self.instance = vlc.Instance(" ".join(args))
                else:
                    self.instance = vlc.Instance()
            except Exception:
                self.instance = None
                print("VLC örneği oluşturulamadı.")
        else:
            self.instance = None
            print("Sisteminizde VLC Player bulunamadı.")
            
    def set_normalization(self, enabled):
        if self.normalization_enabled != enabled:
            was_playing = self.is_playing()
            self.normalization_enabled = enabled
            self._init_vlc()
            if was_playing:
                # Re-initializing VLC instance while playing will break the stream.
                # Since toggling via menu usually happens when not playing, this is fine.
                pass
        
    def get_stream_url(self, url: str) -> str:
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info['url']
            
    def play(self, url: str):
        if not self.instance:
            return False

        try:
            stream_url = self.get_stream_url(url)
        except Exception as e:
            print("Stream url alınırken hata:", e)
            return False
            
        if self.player:
            self.player.stop()
            
        self.player = self.instance.media_player_new()
        media = self.instance.media_new(stream_url)
        self.player.set_media(media)
        self.player.play()
        return True
        
    def stop(self):
        if self.player:
            self.player.stop()
            
    def pause(self):
        if self.player:
            self.player.pause()
            
    def is_playing(self):
        if self.player:
            return self.player.is_playing() == 1
        return False
        
    def get_time(self):
        if self.player:
            return self.player.get_time()
        return 0
        
    def get_length(self):
        if self.player:
            return self.player.get_length()
        return 0
        
    def get_volume(self):
        if self.player:
            return self.player.audio_get_volume()
        return 0
        
    def set_volume(self, vol):
        if self.player:
            self.player.audio_set_volume(vol)

