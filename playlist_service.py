"""Çalma listelerini kalıcı olarak yöneten servis."""
import logging

from song_utils import clean_text, sanitize_song
from storage import data_path, load_json, save_json_atomic

logger = logging.getLogger(__name__)

PLAYLIST_FILE = "playlists.json"


class PlaylistManager:
    def __init__(self, path=None):
        self.path = path or data_path(PLAYLIST_FILE)
        self.playlists = self.load()

    def load(self):
        raw = load_json(self.path, {})
        if not isinstance(raw, dict):
            logger.error("%s beklenmeyen formatta, yok sayıldı.", self.path)
            return {}
        playlists = {}
        dropped = 0
        for name, songs in raw.items():
            if not isinstance(name, str) or not isinstance(songs, list):
                dropped += 1
                continue
            clean = []
            seen = set()
            for s in songs:
                song = sanitize_song(s)
                if song and song["videoId"] not in seen:
                    seen.add(song["videoId"])
                    clean.append(song)
                else:
                    dropped += 1
            playlists[name] = clean
        if dropped:
            logger.warning("%d geçersiz kayıt playlist dosyasından atlandı.", dropped)
        return playlists

    def save(self):
        """Atomik kayıt. Hata durumunda OSError fırlatır (çağıran bildirmeli)."""
        save_json_atomic(self.path, self.playlists)

    def get_all(self):
        return self.playlists

    def get_songs(self, playlist_name):
        """Listenin bir KOPYASINI döndürür (çalma kuyruğu bozulmasın diye). Liste yoksa None."""
        songs = self.playlists.get(playlist_name)
        return list(songs) if songs is not None else None

    def contains(self, playlist_name, video_id):
        return any(s["videoId"] == video_id for s in self.playlists.get(playlist_name, []))

    def unique_name(self, base, label="Bulut"):
        if base not in self.playlists:
            return base
        candidate = f"{base} ({label})"
        n = 2
        while candidate in self.playlists:
            candidate = f"{base} ({label} {n})"
            n += 1
        return candidate

    def add_song(self, playlist_name, song):
        return self.add_songs(playlist_name, [song]) == 1

    def add_songs(self, playlist_name, songs):
        """Şarkıları tek seferde ekler ve tek bir kez kaydeder. Eklenen şarkı sayısını döndürür."""
        playlist_name = clean_text(playlist_name, "")
        if not playlist_name:
            raise ValueError("Geçersiz liste adı")
        target = self.playlists.setdefault(playlist_name, [])
        existing = {s["videoId"] for s in target}
        added = 0
        for s in songs:
            song = sanitize_song(s)
            if song and song["videoId"] not in existing:
                existing.add(song["videoId"])
                target.append(song)
                added += 1
        self.save()
        return added

    def remove_song(self, playlist_name, video_id):
        songs = self.playlists.get(playlist_name)
        if not songs:
            return False
        for i, s in enumerate(songs):
            if s["videoId"] == video_id:
                songs.pop(i)
                self.save()
                return True
        return False

    def toggle_song(self, playlist_name, song):
        """Şarkı listede varsa çıkarır (False), yoksa ekler (True)."""
        if self.remove_song(playlist_name, song["videoId"]):
            return False
        return self.add_song(playlist_name, song)

    def delete_playlist(self, playlist_name):
        if playlist_name in self.playlists:
            del self.playlists[playlist_name]
            self.save()
            return True
        return False
