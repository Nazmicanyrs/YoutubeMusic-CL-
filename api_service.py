from ytmusicapi import YTMusic

class MusicAPI:
    def __init__(self):
        self.yt = YTMusic()
        
    def search(self, query: str, limit: int = 10):
        """
        Şarkı araması yapar ve sonuçları döndürür.
        """
        results = self.yt.search(query, filter="songs", limit=limit)
        
        parsed_results = []
        for item in results:
            video_id = item.get("videoId")
            title = item.get("title")
            
            # Artists can be a list of dicts
            artists = item.get("artists", [])
            artist_name = ", ".join([a.get("name") for a in artists]) if artists else "Bilinmeyen Sanatçı"
            
            duration = item.get("duration", "0:00")
            thumbnails = item.get("thumbnails", [])
            thumbnail_url = thumbnails[-1]["url"] if thumbnails else None
            
            if video_id and title:
                parsed_results.append({
                    "videoId": video_id,
                    "title": title,
                    "artist": artist_name,
                    "duration": duration,
                    "url": f"https://music.youtube.com/watch?v={video_id}",
                    "thumbnail": thumbnail_url
                })
                
        return parsed_results
        
    def get_recommendations(self, video_id: str, limit: int = 15):
        try:
            res = self.yt.get_watch_playlist(videoId=video_id, limit=limit)
            tracks = res.get("tracks", [])
            parsed = []
            for item in tracks:
                vid = item.get("videoId")
                if not vid or vid == video_id:
                    continue
                title = item.get("title")
                artists = item.get("artists", [])
                artist_name = ", ".join([a.get("name") for a in artists]) if artists else "Bilinmeyen Sanatçı"
                duration = item.get("length", "0:00")
                thumbnails = item.get("thumbnails", [])
                thumbnail_url = thumbnails[-1]["url"] if thumbnails else None
                
                parsed.append({
                    "videoId": vid,
                    "title": title,
                    "artist": artist_name,
                    "duration": duration,
                    "url": f"https://music.youtube.com/watch?v={vid}",
                    "thumbnail": thumbnail_url
                })
            return parsed
        except Exception as e:
            return []
