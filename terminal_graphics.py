"""Native Sixel cover art and a differential Rich renderer.

Text refreshes must never paint spaces over the image: ordinary Rich Live
repaints the whole screen, which erases terminal graphics on every frame.
"""
import io
import math
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from itertools import groupby

from PIL import Image
from rich.console import Console
from rich.segment import Segment, Segments

PENDING_KEYS = deque()
_REPLIES = re.compile(r"\x1b\[\?[\d;]*c|\x1b\[6;\d+;\d+t")


@dataclass(frozen=True)
class GraphicsSupport:
    sixel: bool = False
    cell_width: int = 0
    cell_height: int = 0


def parse_replies(reply):
    attributes = re.search(r"\x1b\[\?([\d;]*)c", reply)
    cells = re.search(r"\x1b\[6;(\d+);(\d+)t", reply)
    supported = attributes and "4" in attributes.group(1).split(";")
    if supported and cells:
        height, width = map(int, cells.groups())
        if 1 <= width <= 200 and 1 <= height <= 400:
            return GraphicsSupport(True, width, height)
    return GraphicsSupport()


def detect_graphics(console, timeout=0.6):
    """Ask the actual terminal, not its name/version. Preserve typed keys."""
    if os.name != "nt" or not console.is_terminal:
        return GraphicsSupport()
    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    old_input = wintypes.DWORD()
    old_output = wintypes.DWORD()
    reply = ""
    changed = False
    try:
        import sys
        input_handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        output_handle = msvcrt.get_osfhandle(console.file.fileno())
        if not kernel.GetConsoleMode(input_handle, ctypes.byref(old_input)):
            return GraphicsSupport()
        if not kernel.GetConsoleMode(output_handle, ctypes.byref(old_output)):
            return GraphicsSupport()
        # Raw VT input is needed for the response; no echo / line buffering.
        if not kernel.SetConsoleMode(input_handle, (old_input.value | 0x200) & ~6):
            return GraphicsSupport()
        changed = True
        kernel.SetConsoleMode(output_handle, old_output.value | 4)
        console.file.write("\x1b[c\x1b[16t")
        console.file.flush()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                reply += msvcrt.getch().decode("latin1")
                if re.search(r"\x1b\[\?[\d;]*c", reply) and re.search(r"\x1b\[6;\d+;\d+t", reply):
                    break
            else:
                time.sleep(0.005)
        return parse_replies(reply)
    except (OSError, ValueError, AttributeError):
        return GraphicsSupport()
    finally:
        if changed:
            kernel.SetConsoleMode(input_handle, old_input.value)
        PENDING_KEYS.extend(bytes([b]) for b in _REPLIES.sub("", reply).encode("latin1"))


def fit_cover(columns, rows, support, max_pixels=1024):
    """Square image in physical pixels, contained in the available cell area."""
    side = min(columns * support.cell_width, rows * support.cell_height, max_pixels)
    side = max(1, side)
    return (math.ceil(side / support.cell_width), math.ceil(side / support.cell_height), side)


def _run_length(text):
    parts = []
    for char, group in groupby(text):
        count = sum(1 for _ in group)
        parts.append(f"!{count}{char}" if count > 3 else char * count)
    return "".join(parts)


def encode_sixel(image, size):
    """Encode actual image pixels (256 adaptive colors), not character blocks."""
    pic = image.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    pic = pic.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    width, height = pic.size
    pixels = pic.load()
    palette = pic.getpalette()
    used = sorted(color for _, color in pic.getcolors())
    # P2=1: leave pixels outside the raster untouched. 1:1 pixel aspect ratio.
    out = [f'\x1bP0;1;0q"1;1;{width};{height}']
    for color in used:
        rgb = palette[color * 3:color * 3 + 3]
        out.append(f"#{color};2;" + ";".join(str(round(v * 100 / 255)) for v in rgb))
    for y in range(0, height, 6):
        bands = {}
        for dy in range(min(6, height - y)):
            bit = 1 << dy
            for x in range(width):
                color = pixels[x, y + dy]
                if color not in bands:
                    bands[color] = bytearray(width)
                bands[color][x] |= bit
        for color, band in bands.items():
            data = "".join(chr(value + 63) for value in band).rstrip("?")
            out.append(f"#{color}" + _run_length(data) + "$")
        if y + 6 < height:
            out.append("-")
    out.append("\x1b\\")
    return "".join(out)


class SixelLive:
    """Render changed text regions only; cache the raster until cover/size changes.

    image_provider returns (PIL image, (x, y, columns, rows), pixel_size) or None.
    Coordinates are zero-based terminal cells. All writes happen on the UI thread.
    """

    def __init__(self, renderable, console, image_provider):
        self.console = console
        self.renderable = renderable
        self.image_provider = image_provider
        self.active = False
        self._previous = {}
        self._frame_key = None
        self._encoded_key = None
        self._encoded = ""
        self._image = None
        self._buffer = io.StringIO()
        self._encoder = Console(file=self._buffer, force_terminal=True,
                                color_system="truecolor", legacy_windows=False)

    def __enter__(self):
        self.start(refresh=True)
        return self

    def __exit__(self, *exc):
        self.stop()

    def start(self, refresh=False):
        if self.active:
            return
        self.active = True
        self._frame_key = None
        self._write("\x1b[?1049h\x1b[?25l\x1b[?7l")
        try:
            if refresh:
                self.update(self.renderable)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.active:
            self._write("\x1b[0m\x1b[?7h\x1b[?25h\x1b[?1049l")
            self.active = False

    def _write(self, text):
        self.console.file.write(text)
        self.console.file.flush()

    def _ansi(self, segments):
        self._buffer.seek(0)
        self._buffer.truncate()
        self._encoder.print(Segments(segments), end="", soft_wrap=True)
        return self._buffer.getvalue()

    def update(self, renderable):
        self.renderable = renderable
        if not self.active:
            return
        width, height = self.console.size
        image_spec = self.image_provider()
        image_key = None
        region = None
        if image_spec:
            picture, region, pixel_size = image_spec
            image_key = (id(picture), region, pixel_size)
            encode_key = (id(picture), pixel_size)
            if encode_key != self._encoded_key:
                self._encoded = encode_sixel(picture, pixel_size)
                self._encoded_key = encode_key
                self._image = picture  # keep alive; id cannot be recycled
        frame_key = (width, height, image_key)
        reset = frame_key != self._frame_key
        output = []
        if reset:
            output.append("\x1b[2J\x1b[H")
            self._previous.clear()
        lines = self.console.render_lines(renderable, self.console.options.update_dimensions(width, height), pad=True)
        for y, line in enumerate(lines[:height]):
            if region and region[1] <= y < region[1] + region[3]:
                x, _, cols, _ = region
                pieces = list(Segment.divide(line, [x, x + cols, width]))
                spans = [(0, pieces[0]), (x + cols, pieces[2])]
            else:
                spans = [(0, line)]
            for x, segments in spans:
                if not segments or x >= width:
                    continue
                key = (y, x)
                if self._previous.get(key) != segments:
                    output.append(f"\x1b[{y + 1};{x + 1}H" + self._ansi(segments))
                    self._previous[key] = segments
        if reset and image_spec:
            output.append(f"\x1b[{region[1] + 1};{region[0] + 1}H" + self._encoded)
        if output:
            self._write("\x1b[?2026h" + "".join(output) + "\x1b[?2026l")
        self._frame_key = frame_key
