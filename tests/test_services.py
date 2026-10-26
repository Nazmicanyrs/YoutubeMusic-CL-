import unittest
import tempfile
from pathlib import Path

from themes import THEMES
from gui_dialogs import accent_for_theme, build_palette, recolor_text
from cloud_share import SHARE_CODE_RE, DPASTE_URL_RE
from download_service import DownloadService
from song_utils import parse_duration_ms, clean_text, sanitize_song
from storage import load_json, save_json_atomic

class TestCrossPlatformServices(unittest.TestCase):
    def test_themes_and_palette(self):
        self.assertIn("yt-music-cli", THEMES)
        self.assertIn("Spotify", THEMES)
        settings = {"theme": "Spotify"}
        accent = accent_for_theme(settings)
        self.assertEqual(accent.upper(), "#1ED760")
        
        pal = build_palette(accent)
        self.assertIn("accent", pal)
        qss = recolor_text("color: #1ED760; background: #123C2A;", build_palette("#1ED760"), pal)
        self.assertIsInstance(qss, str)

    def test_cloud_share_regex(self):
        self.assertTrue(bool(SHARE_CODE_RE.match("abcd1234")))
        self.assertFalse(bool(SHARE_CODE_RE.match("!invalid!")))
        m = DPASTE_URL_RE.match("https://dpaste.com/AbCdEf")
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "AbCdEf")

    def test_download_service_index(self):
        svc = DownloadService()
        self.assertIsInstance(svc.songs(), list)
        self.assertFalse(svc.is_downloaded("non_existent_id_xyz"))

    def test_song_utils(self):
        self.assertEqual(parse_duration_ms("03:45"), 225000)
        self.assertEqual(parse_duration_ms("1:01:05"), 3665000)
        cleaned = clean_text("  Test   Song   \n  ", "Bilinmeyen")
        self.assertEqual(cleaned, "Test Song")
        
        raw_song = {"title": "Test", "videoId": "v1234567890", "artist": "Artist1"}
        sanitized = sanitize_song(raw_song)
        self.assertIsNotNone(sanitized)
        self.assertEqual(sanitized["artist"], "Artist1")

    def test_storage_atomic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.json"
            data = {"key": "value", "list": [1, 2, 3]}
            save_json_atomic(test_file, data)
            loaded = load_json(test_file, {})
            self.assertEqual(loaded, data)

if __name__ == "__main__":
    unittest.main()
