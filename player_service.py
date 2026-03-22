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
        
        if VLC_AVAILABLE:
            try:
                self.instance = vlc.Instance()
            except Exception:
                self.instance = None
                print("VLC örneği oluşturulamadı.")
        else:
            self.instance = None
            print("Sisteminizde VLC Player bulunamadı.")
        
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

