import io
import pathlib
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PIL import Image, ImageChops, ImageStat
from rich.console import Console
from rich.panel import Panel
from terminal_graphics import GraphicsSupport, SixelLive, encode_sixel, fit_cover, parse_replies


def decode_sixel(data):
    """Independent decoder for pixel-level regression checks of the wire format."""
    width, height = map(int, re.search(r'"1;1;(\d+);(\d+)', data).groups())
    result = Image.new("RGB", (width, height))
    colors = {}
    x = y = color = 0
    start = data.index(f'"1;1;{width};{height}') + len(f'"1;1;{width};{height}')
    for match in re.finditer(r"#(\d+)(?:;2;(\d+);(\d+);(\d+))?|!(\d+)([?-~])|([?-~])|([$-])", data[start:-2]):
        index, red, green, blue, run, repeated, single, control = match.groups()
        if index is not None:
            color = int(index)
            if red is not None:
                colors[color] = tuple(round(int(c) * 255 / 100) for c in (red, green, blue))
        elif control:
            x = 0
            if control == "-":
                y += 6
        else:
            bits = ord(repeated or single) - 63
            for _ in range(int(run or 1)):
                for dy in range(6):
                    if bits & (1 << dy) and x < width and y + dy < height:
                        result.putpixel((x, y + dy), colors[color])
                x += 1
    return result


class GraphicsTests(unittest.TestCase):
    def test_capability_requires_explicit_sixel_and_pixel_dimensions(self):
        self.assertEqual(parse_replies("\x1b[?65;4;22c\x1b[6;24;12t"), GraphicsSupport(True, 12, 24))
        for reply in ("", "\x1b[?65;22c\x1b[6;24;12t", "\x1b[?65;4c", "\x1b[?4c\x1b[6;0;12t"):
            self.assertFalse(parse_replies(reply).sixel)

    def test_square_uses_real_cell_aspect_ratio(self):
        cols, rows, side = fit_cover(40, 20, GraphicsSupport(True, 11, 25))
        self.assertEqual(side, 440)
        self.assertEqual((cols, rows), (40, 18))
        self.assertLessEqual(side, rows * 25)

    def test_sixel_pixels_round_trip_including_partial_band_and_runs(self):
        pic = Image.new("RGB", (33, 17), "white")
        for y in range(17):
            for x in range(33):
                if x % 7 == 0 or y % 5 == 0:
                    pic.putpixel((x, y), (255, 0, 0) if x % 2 else (0, 0, 255))
        encoded = encode_sixel(pic, pic.size)
        self.assertIn("!", encoded)
        self.assertIsNone(ImageChops.difference(pic, decode_sixel(encoded)).getbbox())

    def test_fine_details_survive_above_character_resolution(self):
        pic = Image.new("RGB", (240, 240))
        for y in range(240):
            for x in range(240):
                pic.putpixel((x, y), (x, y, 255 if (x // 2) % 2 else 0))
        decoded = decode_sixel(encode_sixel(pic, pic.size))
        self.assertEqual(decoded.size, (240, 240))
        error = ImageStat.Stat(ImageChops.difference(pic, decoded)).mean
        self.assertLess(max(error), 10)

    def test_live_keeps_image_between_frames_and_clears_on_mode_changes(self):
        stream = io.StringIO()
        console = Console(file=stream, width=80, height=30, force_terminal=True)
        picture = Image.new("RGB", (64, 64), "red")
        spec = [(picture, (3, 4, 20, 10), (200, 200))]
        live = SixelLive(Panel("one"), console, lambda: spec[0])
        with live:
            before = stream.getvalue()
            live.update(Panel("one"))
            self.assertEqual(before, stream.getvalue())
            live.update(Panel("two"))
            self.assertEqual(stream.getvalue().count("\x1bP0;1;0q"), 1)
            spec[0] = None
            live.update(Panel("mini"))
            self.assertEqual(stream.getvalue().count("\x1b[2J"), 2)
            spec[0] = (picture, (3, 4, 20, 10), (200, 200))
            live.update(Panel("one"))
            self.assertEqual(stream.getvalue().count("\x1bP0;1;0q"), 2)
        self.assertTrue(stream.getvalue().endswith("\x1b[?1049l"))

    def test_resize_and_song_change_redraw_raster(self):
        stream = io.StringIO()
        console = Console(file=stream, width=80, height=30, force_terminal=True)
        spec = [(Image.new("RGB", (20, 20), "red"), (3, 4, 10, 5), (100, 100))]
        with SixelLive(Panel("test"), console, lambda: spec[0]) as live:
            console.width = 100
            live.update(Panel("test"))
            spec[0] = (Image.new("RGB", (20, 20), "blue"), (3, 4, 10, 5), (100, 100))
            live.update(Panel("test"))
        self.assertEqual(stream.getvalue().count("\x1bP0;1;0q"), 3)


class CoverIntegrationTests(unittest.TestCase):
    def test_old_playlist_thumbnail_is_upgraded_and_falls_back(self):
        import main
        payload = io.BytesIO()
        Image.new("RGB", (120, 80), "blue").save(payload, format="PNG")
        class Response:
            content = payload.getvalue()
            def raise_for_status(self):
                pass
        url = "https://lh3.googleusercontent.com/cover=w120-h120-l90-rj"
        with patch.object(main.requests, "get", side_effect=[main.requests.RequestException(), Response()]) as get:
            image = main.fetch_cover(url)
        self.assertIn("w1024-h1024", get.call_args_list[0].args[0])
        self.assertEqual(get.call_args_list[1].args[0], url)
        self.assertEqual(image.size, (80, 80))

    def test_native_region_fits_rendered_panel_and_mini_removes_it(self):
        import main
        from song_utils import sanitize_song
        song = sanitize_song({"videoId": "abcdefghijk", "title": "Test"})
        class Player:
            get_state = lambda self: "playing"
            get_time = lambda self: 1000
            get_length = lambda self: 180000
            get_volume = lambda self: 90
        class Playlists:
            contains = lambda *args: False
        with patch.object(main, "player", Player()), patch.object(main, "playlist_manager", Playlists()), patch.dict(main.app_settings, {"cover_style": "block"}):
            session = main.PlayerSession(song, [song])
            session.graphics = GraphicsSupport(True, 10, 20)
            session.cover = Image.new("RGB", (1024, 1024))
            for width, height in ((80, 25), (160, 50), (220, 65)):
                console = Console(file=io.StringIO(), width=width, height=height)
                with patch.object(main, "console", console):
                    frame = session.render()
                    image, (x, y, cols, rows), size = session._pixel_cover
                    self.assertLessEqual(x + cols, width)
                    self.assertLessEqual(y + rows, height)
                    self.assertEqual(size[0], size[1])
                    lines = console.render_lines(frame, console.options.update_dimensions(width, height))
                    for line in lines[y:y + rows]:
                        from rich.segment import Segment
                        center = list(Segment.divide(line, [x, x + cols]))[1]
                        self.assertFalse("".join(s.text for s in center).strip())
                    session.mini_mode = True
                    session.render()
                    self.assertIsNone(session._pixel_cover)
                    session.mini_mode = False


if __name__ == "__main__":
    unittest.main()
