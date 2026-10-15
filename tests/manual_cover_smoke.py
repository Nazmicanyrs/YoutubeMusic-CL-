"""Run in Windows Terminal for live image/playback QA; no personal settings saved.

Usage: python tests/manual_cover_smoke.py
Writes progress to %TEMP%/ytm_cover_smoke-<pid>.json and exits after one minute.
"""
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import traceback

# A shell launched by a build agent may inherit TERM=dumb / fixed dimensions.
# The test is launched explicitly in Windows Terminal, which probes Sixel itself.
for key in ("TERM", "COLUMNS", "LINES"):
    os.environ.pop(key, None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import main

report = pathlib.Path(tempfile.gettempdir()) / f"ytm_cover_smoke-{os.getpid()}.json"


def record(data):
    report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run():
    main.init_app()
    main.app_settings["notifications_enabled"] = False
    main.app_settings["cover_style"] = "block"
    main.save_settings = lambda: None
    songs = main.api.search("Gemilerde Talim Var Beyaz")
    song = next((s for s in songs if "Beyaz" in s["artist"]), songs[0])
    session = main.PlayerSession(song, songs)

    def observe():
        samples = []
        for n in range(60):
            time.sleep(1)
            with session.lock:
                samples.append({"elapsed": n + 1, "graphics": vars(session.graphics),
                        "console": list(main.console.size), "mini": session.mini_mode,
                        "style": main.app_settings['cover_style'], "track": session.idx,
                        "cover": getattr(session.cover, "size", None),
                        "region": session._pixel_cover[1:] if session._pixel_cover else None,
                        "state": main.player.get_state(), "time_ms": main.player.get_time(),
                        "error": session.error, "loading": session.loading})
                record({"samples": samples})
            if n + 1 in (20, 25):
                main.ACTION_QUEUE.append("toggle_mini")
            if n + 1 in (30, 35):
                main.ACTION_QUEUE.append("toggle_cover")
            if n + 1 == 40:
                main.ACTION_QUEUE.append("next")
        main.ACTION_QUEUE.append("quit")

    threading.Thread(target=observe, daemon=True).start()
    try:
        session.run()
    finally:
        main.shutdown()


if __name__ == "__main__":
    try:
        run()
    except BaseException:
        record({"exception": traceback.format_exc()})
        raise
