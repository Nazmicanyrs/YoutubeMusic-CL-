"""GUI için yardımcı pencereler: tema galerisi/editörü, kullanım rehberi; tema renk yardımcıları."""
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHeaderView,
    QAbstractItemView,
)

from themes import THEMES

GUI_BASE_ACCENT = "#1ED760"
# GUI'nin varsayılan (yeşil) görünümünü veren temalar: bunlarda renk değiştirilmez.
DEFAULT_LOOK_THEMES = ("Spotify",)
HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")

# Tasarımda kullanılan sabit renkler -> vurgu renginden türetilir.
_BASE_PALETTE = {
    "accent": "#1ED760",
    "accent_hover": "#24F56E",
    "accent_hover2": "#22E567",
    "accent_dark": "#123C2A",
}


def normalize_hex(val):
    val = val.strip()
    if not val.startswith("#"):
        val = "#" + val
    return val.upper()


def _mix(hex_a, hex_b, ratio):
    a, b = QColor(hex_a), QColor(hex_b)
    r = int(a.red() * (1 - ratio) + b.red() * ratio)
    g = int(a.green() * (1 - ratio) + b.green() * ratio)
    bl = int(a.blue() * (1 - ratio) + b.blue() * ratio)
    return QColor(r, g, bl).name().upper()


def build_palette(primary):
    """Vurgu renginden (hover/koyu tonlar dahil) tüm tasarım paletini üretir."""
    primary = normalize_hex(primary)
    return {
        "accent": primary,
        "accent_hover": _mix(primary, "#FFFFFF", 0.18),
        "accent_hover2": _mix(primary, "#FFFFFF", 0.10),
        "accent_dark": _mix(primary, "#000000", 0.72),
    }


def base_palette():
    return {k: v.upper() for k, v in _BASE_PALETTE.items()}


def recolor_text(text, current, target):
    """`text` içindeki hem orijinal hem mevcut palet renklerini hedef palete çevirir."""
    if not text:
        return text
    base = base_palette()
    out = text
    for i, key in enumerate(base):
        for old in {base[key], current[key]}:
            out = re.sub(re.escape(old), f"@@P{i}@@", out, flags=re.I)
    for i, key in enumerate(base):
        out = out.replace(f"@@P{i}@@", target[key])
    return out


def all_themes(settings):
    themes = dict(THEMES)
    custom = settings.get("custom_themes")
    if isinstance(custom, dict):
        themes.update({k: v for k, v in custom.items() if isinstance(v, dict) and "primary" in v})
    return themes


def accent_for_theme(settings):
    """Aktif temaya göre GUI vurgu rengini döndürür."""
    name = settings.get("theme", "Spotify")
    if name in DEFAULT_LOOK_THEMES:
        return GUI_BASE_ACCENT
    theme = all_themes(settings).get(name)
    if not theme or not HEX_RE.match(str(theme.get("primary", ""))):
        return GUI_BASE_ACCENT
    return normalize_hex(theme["primary"])


def _swatch(primary, border):
    pm = QPixmap(46, 22)
    pm.fill(QColor(border))
    inner = QPixmap(38, 14)
    inner.fill(QColor(primary))
    from PyQt6.QtGui import QPainter
    p = QPainter(pm)
    p.drawPixmap(4, 4, inner)
    p.end()
    return QIcon(pm)


BTN_STYLE = """
QPushButton { background-color: #16201B; border: 1px solid #25362E; border-radius: 6px;
              padding: 8px 16px; color: #E6E6E6; font-weight: 600; }
QPushButton:hover { background-color: #1D2A24; color: #FFFFFF; }
QPushButton:disabled { color: #55605A; }
"""
PRIMARY_BTN_STYLE = """
QPushButton { background-color: #1ED760; border: none; border-radius: 6px;
              padding: 8px 18px; color: #000000; font-weight: 700; }
QPushButton:hover { background-color: #22E567; }
"""


class ThemeDialog(QDialog):
    """CLI'deki Tema Galerisi & Kişisel Tema Editörü'nün GUI karşılığı (aynı settings.json)."""
    theme_applied = pyqtSignal()

    def __init__(self, settings, save_cb, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.save_cb = save_cb
        self.setWindowTitle("Tema Galerisi & Editörü")
        self.setMinimumSize(460, 480)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)

        title = QLabel("🎨 Tema Galerisi")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #1ED760;")
        lay.addWidget(title)
        hint = QLabel("Temalar CLI ile ortaktır. Vurgu rengi hemen uygulanır; simgeler yeniden başlatınca güncellenir.")
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size: 11px; color: #8C9990;")
        lay.addWidget(hint)

        self.list = QListWidget()
        self.list.setStyleSheet(
            "QListWidget { background-color: #0B100D; border: 1px solid #141F18; border-radius: 8px; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background-color: #1A2620; }"
        )
        self.list.itemDoubleClicked.connect(lambda _: self._apply())
        lay.addWidget(self.list, stretch=1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_apply = QPushButton("✓ Uygula")
        self.btn_apply.setStyleSheet(PRIMARY_BTN_STYLE)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_new = QPushButton("➕ Yeni Tema")
        self.btn_new.setStyleSheet(BTN_STYLE)
        self.btn_new.clicked.connect(self._create)
        self.btn_del = QPushButton("🗑️ Sil")
        self.btn_del.setStyleSheet(BTN_STYLE)
        self.btn_del.clicked.connect(self._delete)
        btn_close = QPushButton("Kapat")
        btn_close.setStyleSheet(BTN_STYLE)
        btn_close.clicked.connect(self.accept)
        for b in (self.btn_apply, self.btn_new, self.btn_del):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(btn_close)
        lay.addLayout(row)

        self.list.currentItemChanged.connect(self._update_buttons)
        self._refresh()

    # ------------------------------------------------------------------
    def _refresh(self, select=None):
        themes = all_themes(self.settings)
        custom = self.settings.get("custom_themes") or {}
        active = self.settings.get("theme", "Spotify")
        self.list.clear()
        for name, data in themes.items():
            mark = "✓ " if name == active else "   "
            tag = "  [Özel Tema]" if name in custom else ""
            item = QListWidgetItem(_swatch(data.get("primary", "#FFFFFF"), data.get("border", "#555555")),
                                   f"{mark}{name}{tag}   {data.get('primary', '')}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.list.addItem(item)
            if name == (select or active):
                self.list.setCurrentItem(item)
        self._update_buttons()

    def _selected_name(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self, *_):
        name = self._selected_name()
        custom = self.settings.get("custom_themes") or {}
        self.btn_apply.setEnabled(name is not None)
        self.btn_del.setEnabled(name in custom)

    def _apply(self):
        name = self._selected_name()
        if not name:
            return
        self.settings["theme"] = name
        self.save_cb()
        self.theme_applied.emit()
        self._refresh(select=name)

    def _create(self):
        existing = all_themes(self.settings)
        name, ok = QInputDialog.getText(self, "Yeni Tema", "Tema adı (1-25 karakter):")
        name = name.strip()
        if not ok or not name:
            return
        if len(name) > 25 or name in existing:
            QMessageBox.warning(self, "Geçersiz İsim", "İsim 1-25 karakter olmalı ve mevcut bir temayla aynı olmamalı.")
            return
        primary = QColorDialog.getColor(QColor("#2ECC71"), self, "Ana Vurgu Rengi")
        if not primary.isValid():
            return
        primary_hex = primary.name().upper()
        same = QMessageBox.question(
            self, "Kenarlık Rengi",
            f"Kenarlık rengi ana renkle ({primary_hex}) aynı olsun mu?\n(Hayır: ayrı bir renk seçersiniz.)",
        ) == QMessageBox.StandardButton.Yes
        if same:
            border_hex = primary_hex
        else:
            border = QColorDialog.getColor(QColor("#555555"), self, "Kenarlık Rengi")
            if not border.isValid():
                return
            border_hex = border.name().upper()

        pointers = ["> ", "► ", "● ", ">>", "✨ ", "▶ "]
        pointer, ok = QInputDialog.getItem(self, "İmleç Simgesi", "CLI menü imleci:", pointers, 0, False)
        if not ok:
            return

        custom = self.settings.setdefault("custom_themes", {})
        custom[name] = {
            "primary": primary_hex,
            "border": border_hex,
            "pointer": pointer,
            "style_overrides": {
                "questionmark": f"{primary_hex} bold",
                "answer": f"{primary_hex} bold",
                "input": "white",
                "pointer": f"{primary_hex} bold",
                "marker": primary_hex,
                "instruction": "dim white",
            },
        }
        self.settings["theme"] = name
        self.save_cb()
        self.theme_applied.emit()
        self._refresh(select=name)

    def _delete(self):
        name = self._selected_name()
        custom = self.settings.get("custom_themes") or {}
        if name not in custom:
            return
        if QMessageBox.question(self, "Temayı Sil", f"'{name}' temasını silmek istediğinize emin misiniz?") \
                != QMessageBox.StandardButton.Yes:
            return
        del custom[name]
        if self.settings.get("theme") == name:
            self.settings["theme"] = "Spotify"
            self.theme_applied.emit()
        self.save_cb()
        self._refresh()


class HelpDialog(QDialog):
    """CLI'deki 'Kullanım Rehberi & Kısayollar' ekranının GUI karşılığı."""

    SHORTCUTS = [
        ("Boşluk", "Oynat / Durdur"),
        ("Ctrl + → / Ctrl + ←", "Sonraki / Önceki şarkı (3 sn sonra başa sar)"),
        ("← / →", "5 saniye geri / ileri sar"),
        ("↑ / ↓", "Sesi artır / azalt (%5)"),
        ("Ctrl + K  /  Ctrl + F", "Aramaya odaklan"),
        ("Ctrl + L", "Şarkı sözleri (karaoke)"),
        ("Ctrl + D", "Çalan şarkıyı favorilere ekle / çıkar"),
        ("Ctrl + P", "Çalan şarkıyı çalma listesine ekle"),
        ("Ctrl + R", "Çalan şarkıya göre akıllı öneriler (radyo)"),
        ("Ctrl + S", "Çalan şarkıyı indir"),
        ("Ctrl + M", "Mini oynatıcı modu"),
        ("Ctrl + B / Ctrl + J", "Sol menü / Şimdi Çalıyor panelini aç-kapat"),
        ("Ctrl + T", "Tema galerisi"),
        ("F1", "Bu rehber"),
    ]
    GLOBAL = [
        ("Ctrl+Shift+Alt+Space", "Oynat / Durdur"),
        ("Ctrl+Shift+Alt+← / →", "Önceki / Sonraki şarkı"),
        ("Ctrl+Shift+Alt+↑ / ↓", "Sesi artır / azalt"),
        ("Ctrl+Shift+Alt+L", "Çalan şarkıyı favorile"),
        ("Medya tuşları", "Klavyedeki Oynat/Durdur, İleri, Geri tuşları"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Kullanım Rehberi & Kısayollar")
        self.setMinimumSize(560, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)

        for title_text, rows in (("⌨️ Uygulama Kısayolları", self.SHORTCUTS),
                                 ("🌐 Global Kısayollar (uygulama arka plandayken)", self.GLOBAL)):
            t = QLabel(title_text)
            t.setStyleSheet("font-size: 15px; font-weight: 700; color: #1ED760;")
            lay.addWidget(t)
            table = QTableWidget(len(rows), 2)
            table.horizontalHeader().setVisible(False)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
            table.setStyleSheet("QTableWidget { background: #0B100D; border: 1px solid #141F18; border-radius: 8px; }")
            for r, (k, v) in enumerate(rows):
                ki = QTableWidgetItem(k)
                ki.setForeground(QColor("#FFD54A"))
                table.setItem(r, 0, ki)
                table.setItem(r, 1, QTableWidgetItem(v))
            table.setFixedHeight(min(300, 28 * len(rows) + 6))
            lay.addWidget(table)

        tips = QLabel(
            "💡 <b>İpuçları</b><br>"
            "• Şarkı kartlarına <b>sağ tıklayarak</b> listeye ekleyebilir, indirebilir, radyo başlatabilirsiniz.<br>"
            "• <b>İndirilenler</b> çevrimdışı çalar; indirilmiş şarkılar otomatik yerelden oynatılır.<br>"
            "• <b>Bulut paylaşımı</b> listeleri herkese açık dpaste.com'a yükler; kodu bilen herkes görebilir.<br>"
            "• Temalar ve ayarlar CLI ile ortaktır (settings.json)."
        )
        tips.setWordWrap(True)
        tips.setTextFormat(Qt.TextFormat.RichText)
        tips.setStyleSheet("font-size: 12px; color: #B3B3B3;")
        lay.addWidget(tips)
        lay.addStretch()

        btn = QPushButton("Kapat")
        btn.setStyleSheet(BTN_STYLE)
        btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(btn)
        lay.addLayout(row)
