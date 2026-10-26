"""Global (uygulama arka plandayken çalışan) kısayollar ve medya tuşları — CLI ile aynı tuşlar."""
import logging

from PyQt6.QtCore import QObject, pyqtSignal

try:
    import keyboard
except Exception:  # paket yok veya platform izin vermiyor
    keyboard = None

logger = logging.getLogger(__name__)

# Ctrl+Alt+Yön tuşları bazı Intel sürücülerinde ekranı döndürdüğü için Shift eklendi.
GLOBAL_HOTKEYS = {
    "ctrl+shift+alt+right": "next",
    "ctrl+shift+alt+left": "prev",
    "ctrl+shift+alt+space": "playpause",
    "ctrl+shift+alt+up": "vol_up",
    "ctrl+shift+alt+down": "vol_down",
    "ctrl+shift+alt+l": "like",
    "next track": "next",
    "previous track": "prev",
    "play/pause media": "playpause",
}


class GlobalHotkeys(QObject):
    """`keyboard` kütüphanesi ayrı iş parçacığında çalışır; eylemler Qt sinyaliyle ana iş parçacığına aktarılır."""
    action = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        if not keyboard:
            return
        for combo, name in GLOBAL_HOTKEYS.items():
            try:
                keyboard.add_hotkey(combo, self.action.emit, args=(name,))
                self.active = True
            except Exception:
                logger.warning("Global kısayol kaydedilemedi: %s", combo, exc_info=True)

    def close(self):
        if keyboard and self.active:
            try:
                keyboard.unhook_all()
            except Exception:
                pass
