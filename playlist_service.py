import json
import os

PLAYLIST_FILE = "playlists.json"

class PlaylistManager:
    def __init__(self):
        self.playlists = self.load()
        
    def load(self):
        if not os.path.exists(PLAYLIST_FILE):
            return {}
        try:
            with open(PLAYLIST_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
            
    def save(self):
        with open(PLAYLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.playlists, f, ensure_ascii=False, indent=4)
            
    def get_all(self):
        return self.playlists
        
    def add_song(self, playlist_name, song):
        if playlist_name not in self.playlists:
            self.playlists[playlist_name] = []
            
        # check duplicate
        for s in self.playlists[playlist_name]:
            if s['videoId'] == song['videoId']:
                return False # already exists
                
        self.playlists[playlist_name].append(song)
        self.save()
        return True

    def toggle_song(self, playlist_name, song):
        if playlist_name not in self.playlists:
            self.playlists[playlist_name] = []
            
        for i, s in enumerate(self.playlists[playlist_name]):
            if s['videoId'] == song['videoId']:
                self.playlists[playlist_name].pop(i)
                self.save()
                return False # removed
                
        self.playlists[playlist_name].append(song)
        self.save()
        return True # added

    def delete_playlist(self, playlist_name):
        if playlist_name in self.playlists:
            del self.playlists[playlist_name]
            self.save()
            return True
        return False
