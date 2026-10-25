#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
yt-music-gui — Modern Desktop Music Player
Referans Spotify/Modern Dark UI tasarımına tam uyumlu grafikler,
Mikrofon seçim desteği, konsol ses debug takibi ve dinamik karaoke motoru.
"""

import getpass
import io
import json
import logging
import math
import os
import platform
import re
import sys
import threading
import time
import wave
from collections import deque
from pathlib import Path

import numpy as np
from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRect,
    QSize,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpacerItem,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import qtawesome as qta
import requests
from PIL import Image

try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except Exception:
    sd = None
    SOUNDDEVICE_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_REC_AVAILABLE = True
except Exception:
    sr = None
    SPEECH_REC_AVAILABLE = False

# CLI ve Çekirdek Servisler
from api_service import MusicAPI, MusicAPIError
from player_service import PlayerService
from playlist_service import PlaylistManager
from song_utils import (
    clean_text,
    make_song,
    parse_duration_ms,
    sanitize_song,
    upscale_thumbnail,
)
from storage import data_path, load_json, save_json_atomic

try:
    import syncedlyrics
except ImportError:
    syncedlyrics = None

try:
    from win11toast import toast
except ImportError:
    toast = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("yt-music-gui")

SETTINGS_FILE = data_path("settings.json")
HISTORY_FILE = data_path("history.json")
FAVORITES_NAME = "Favorilerim"
IMAGE_HEADERS = {"User-Agent": "Mozilla/5.0"}
_LRC_TS = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def format_ms(ms):
    s = max(0, int(ms)) // 1000
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    return f"{s // 60:02d}:{s % 60:02d}"


def parse_lrc(lrc_text):
    if not lrc_text:
        return []
    out = []
    for raw in lrc_text.splitlines():
        line = raw.strip()
        pos = 0
        stamps = []
        while True:
            m = _LRC_TS.match(line, pos)
            if not m:
                break
            stamps.append(m)
            pos = m.end()
        text = line[pos:].strip()
        if not stamps or not text:
            continue
        for m in stamps:
            frac = (m.group(3) or "0").ljust(3, "0")[:3]
            time_ms = int(m.group(1)) * 60000 + int(m.group(2)) * 1000 + int(frac)
            out.append((time_ms, text))
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------------------
# Referans Görsele Birebir Modern Karanlık Stil (QSS)
# ---------------------------------------------------------------------------
MODERN_STYLE = """
* {
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Circular Std", Roboto, sans-serif;
    color: #FFFFFF;
    outline: none;
}

QMainWindow, QWidget#centralWidget {
    background-color: #000000;
}

/* Çizgileri tamamen gizle */
QSplitter, QSplitter::handle {
    background-color: transparent;
    border: none;
    width: 0px;
    height: 0px;
}

/* Sol Panel */
QFrame#sidebarFrame {
    background-color: #0E1210;
    border-radius: 12px;
    border: 1px solid #161F1A;
}

QPushButton.navHomeBtn {
    background-color: #123C2A;
    color: #FFFFFF;
    border: 1px solid #1ED760;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 700;
    text-align: left;
}

QPushButton.navBtn {
    background-color: transparent;
    color: #B3B3B3;
    border-radius: 8px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 600;
    text-align: left;
    border: none;
}

QPushButton.navBtn:hover {
    color: #FFFFFF;
    background-color: #161D18;
}

QPushButton.pillBtn {
    background-color: #1A241F;
    color: #A0A0A0;
    border-radius: 14px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    border: none;
}

QPushButton.pillBtn:hover {
    background-color: #24332B;
    color: #FFFFFF;
}

QPushButton.pillBtn.active {
    background-color: #1ED760;
    color: #000000;
    font-weight: 700;
}

/* Sol Menü Hızlı Erişim */
QPushButton.quickAccessBtn {
    background: transparent;
    border: none;
    text-align: left;
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 13px;
    color: #B3B3B3;
    font-weight: 600;
}

QPushButton.quickAccessBtn:hover {
    background-color: #161F1A;
    color: #FFFFFF;
}

/* Orta Panel */
QFrame#contentFrame {
    background-color: #0A0D0B;
    border-radius: 12px;
    border: 1px solid #161F1A;
}

/* Hero Banner */
QFrame#heroBanner {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0F2D1F, stop:0.5 #091A12, stop:1 #060F0B);
    border-radius: 12px;
    border: 1px solid #1C3D2D;
}

QLineEdit#heroSearchInput {
    background-color: #131E18;
    border: 1px solid #23382C;
    border-radius: 20px;
    padding: 10px 18px;
    font-size: 13px;
    color: #FFFFFF;
    selection-background-color: #1ED760;
}

QLineEdit#heroSearchInput:focus {
    border: 1px solid #1ED760;
    background-color: #16241D;
}

QPushButton.heroIconBtn {
    background-color: rgba(255, 255, 255, 0.08);
    border: none;
    border-radius: 18px;
    width: 36px;
    height: 36px;
    min-width: 36px;
    min-height: 36px;
}

QPushButton.heroIconBtn:hover {
    background-color: rgba(255, 255, 255, 0.18);
}

/* Sağ Panel */
QFrame#rightPanelFrame {
    background-color: #0E1210;
    border-radius: 12px;
    border: 1px solid #161F1A;
}

/* Alt Oynatıcı Barı */
QFrame#bottomPlayerBar {
    background-color: #050706;
    min-height: 86px;
    max-height: 86px;
    border-top: 1px solid #141A16;
    padding: 0 16px;
}

QPushButton.mediaCtrlBtn {
    background: transparent;
    border: none;
    padding: 6px;
    border-radius: 16px;
}

QPushButton.mediaCtrlBtn:hover {
    background-color: rgba(255, 255, 255, 0.08);
}

QPushButton#playPauseCircleBtn {
    background-color: #1ED760;
    border-radius: 20px;
    width: 40px;
    height: 40px;
    min-width: 40px;
    min-height: 40px;
    border: none;
}

QPushButton#playPauseCircleBtn:hover {
    background-color: #24F56E;
}

/* Slider Tasarımı */
QSlider::groove:horizontal {
    height: 4px;
    background: #27382F;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background: #1ED760;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: #FFFFFF;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}

QSlider::handle:horizontal:hover {
    background: #1ED760;
}

/* İnce Modern Scrollbar */
QScrollBar:horizontal {
    height: 5px;
    background: transparent;
    margin: 0px;
    border: none;
}

QScrollBar::handle:horizontal {
    background: rgba(30, 215, 96, 0.3);
    min-width: 24px;
    border-radius: 2px;
}

QScrollBar::handle:horizontal:hover {
    background: rgba(30, 215, 96, 0.7);
}

QScrollBar:vertical {
    width: 5px;
    background: transparent;
    margin: 0px;
    border: none;
}

QScrollBar::handle:vertical {
    background: rgba(30, 215, 96, 0.3);
    min-height: 24px;
    border-radius: 2px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(30, 215, 96, 0.7);
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    border: none;
    width: 0px;
    height: 0px;
}

/* Şarkı Sözleri */
QListWidget#karaokeList {
    background: transparent;
    border: none;
}
"""

# ---------------------------------------------------------------------------
# Özel Şarkı Sözü Boyama Temsilcisi (Canlı Renkli Karaoke)
# ---------------------------------------------------------------------------
class KaraokeItemDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        state = index.data(Qt.ItemDataRole.UserRole + 1) or "future"
        rect = option.rect

        if state == "active":
            bg_path = QPainterPath()
            bg_path.addRoundedRect(float(rect.x() + 4), float(rect.y() + 2), float(rect.width() - 8), float(rect.height() - 4), 8.0, 8.0)
            painter.fillPath(bg_path, QColor(30, 215, 96, 35))

            font = QFont("Segoe UI", 22, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("#1ED760"))
            painter.drawText(rect.adjusted(16, 0, -16, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"♪  {text}")
        elif state == "past":
            font = QFont("Segoe UI", 18, QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(rect.adjusted(20, 0, -20, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        else:
            font = QFont("Segoe UI", 18, QFont.Weight.Normal)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255, 75))
            painter.drawText(rect.adjusted(20, 0, -20, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

        painter.restore()

    def sizeHint(self, option, index):
        state = index.data(Qt.ItemDataRole.UserRole + 1) or "future"
        if state == "active":
            return QSize(option.rect.width(), 64)
        return QSize(option.rect.width(), 48)


# ---------------------------------------------------------------------------
# Varsayılan Kullanıcı & Mikrofon Filtreleme Yardımcıları
# ---------------------------------------------------------------------------
def get_default_username():
    """Sistemden bilgisayar veya oturum açan kullanıcı adını otomatik alır."""
    try:
        # Öncelik: COMPUTERNAME (kullanıcının açıkça belirttiği bilgisayar adı), sonra USERNAME
        name = os.environ.get("COMPUTERNAME") or getpass.getuser() or platform.node() or "Kullanıcı"
        if name.startswith("DESKTOP-") and os.environ.get("USERNAME"):
            name = os.environ.get("USERNAME")
        if name.isupper():
            name = name.title()
        return name
    except Exception:
        return "Kullanıcı"


def get_clean_microphones():
    """
    Sistemdeki mikrofonları tarar; MME/DirectSound/WASAPI/WDM tekrarlarını eler,
    sanal/loopback aygıtları filtreler ve en yüksek kaliteli (WASAPI öncelikli)
    fiziksel cihazları temiz bir liste olarak döner.
    """
    if not SOUNDDEVICE_AVAILABLE:
        return []
    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception as e:
        logger.warning(f"Mikrofon listeleme hatası: {e}")
        return []

    api_names = {i: api.get("name", "") for i, api in enumerate(hostapis)}

    def api_priority(api_id):
        name = api_names.get(api_id, "").lower()
        if "directsound" in name:
            return 1
        if "mme" in name:
            return 2
        if "wasapi" in name:
            return 3
        return 10

    ignore_keywords = [
        "microsoft ses", "birincil ses", "primary sound", "stereo mix",
        "stereo kar", "pc hoparl", "wave", "mapper", "rec. playback",
        "what u hear"
    ]

    candidates = []
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        dev_name = dev.get("name", "").strip()
        dev_lower = dev_name.lower()

        if any(ign in dev_lower for ign in ignore_keywords):
            continue

        host_id = dev.get("hostapi", 0)
        host_name = api_names.get(host_id, "")

        # WDM-KS genellikle PortAudio'da çok sayıda ham endpoint üretir, atla
        if "wdm-ks" in host_name.lower():
            continue

        clean_name = dev_name
        clean_name = re.sub(r"\(Dijital Mikrofonlar için Intel.*?Teknolojisi\)", "(Intel Dijital Mikrofon)", clean_name, flags=re.IGNORECASE)
        clean_name = re.sub(r"\(Realtek HD Audio.*?input\)", "(Realtek)", clean_name, flags=re.IGNORECASE)
        if "(" in clean_name and ")" not in clean_name:
            clean_name += ")"

        # Cihazı ayırt etmek için anahtar
        core = re.sub(r"^(mikrofon( dizisi)?|microphone( array)?)\s*\(?", "", dev_name, flags=re.IGNORECASE)
        norm_key = re.sub(r"[^a-z0-9]", "", core.lower())[:10]

        candidates.append({
            "index": idx,
            "original_name": dev_name,
            "display_name": clean_name,
            "norm_key": norm_key,
            "priority": api_priority(host_id),
            "hostapi": host_name
        })

    candidates.sort(key=lambda x: x["priority"])

    unique_devices = []
    seen_keys = set()
    for c in candidates:
        if c["norm_key"] not in seen_keys:
            seen_keys.add(c["norm_key"])
            unique_devices.append(c)

    return unique_devices


# ---------------------------------------------------------------------------
# Uygulama & Mikrofon Ayarları İletişim Kutusu (SettingsDialog)
# ---------------------------------------------------------------------------
class SettingsDialog(QDialog):
    def __init__(self, current_device_index=None, current_user_name="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayarlar & Mikrofon")
        self.setFixedWidth(460)
        self.setStyleSheet(MODERN_STYLE)
        self.selected_device_index = current_device_index
        self.user_name = current_user_name or get_default_username()

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 22, 24, 22)

        # Başlık
        title = QLabel("⚙️ Uygulama & Mikrofon Ayarları")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #1ED760;")
        layout.addWidget(title)

        # 1. BÖLÜM: Kullanıcı Karşılama Adı
        user_section = QVBoxLayout()
        user_section.setSpacing(6)
        lbl_user = QLabel("👤 Karşılama Adı (Hero Banner):")
        lbl_user.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        user_section.addWidget(lbl_user)

        user_input_layout = QHBoxLayout()
        user_input_layout.setSpacing(8)

        self.user_name_input = QLineEdit(self.user_name)
        self.user_name_input.setPlaceholderText("İsminizi girin...")
        self.user_name_input.setStyleSheet("""
            QLineEdit {
                background-color: #1A241F;
                border: 1px solid #2B3D34;
                border-radius: 6px;
                padding: 8px 12px;
                color: #FFFFFF;
                font-size: 13px;
            }
            QLineEdit:focus {
                border: 1px solid #1ED760;
            }
        """)
        user_input_layout.addWidget(self.user_name_input, stretch=1)

        btn_default_pc = QPushButton("💻 Bilgisayar Adı")
        btn_default_pc.setToolTip("Varsayılan bilgisayar adını otomatik çek")
        btn_default_pc.setStyleSheet("""
            QPushButton {
                background-color: #1C2B22;
                border: 1px solid #1ED760;
                border-radius: 6px;
                padding: 8px 12px;
                color: #1ED760;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #1ED760;
                color: #000000;
            }
        """)
        btn_default_pc.clicked.connect(self._reset_to_pc_name)
        user_input_layout.addWidget(btn_default_pc)
        user_section.addLayout(user_input_layout)

        desc_user = QLabel("Ana ekranda 'İyi akşamlar', 'Günaydın' mesajlarının altında bu isim görünür.")
        desc_user.setStyleSheet("font-size: 11px; color: #8C9990;")
        user_section.addWidget(desc_user)
        layout.addLayout(user_section)

        # Ayırıcı çizgi
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #1A2620; max-height: 1px;")
        layout.addWidget(line)

        # 2. BÖLÜM: Mikrofon Seçimi
        mic_section = QVBoxLayout()
        mic_section.setSpacing(6)
        lbl_mic = QLabel("🎙️ Sesli Arama İçin Mikrofon:")
        lbl_mic.setStyleSheet("font-size: 13px; font-weight: 600; color: #FFFFFF;")
        mic_section.addWidget(lbl_mic)

        self.device_combo = QComboBox()
        self.device_combo.setStyleSheet("""
            QComboBox {
                background-color: #1A241F;
                border: 1px solid #2B3D34;
                border-radius: 6px;
                padding: 8px 12px;
                color: #FFFFFF;
                font-size: 13px;
            }
            QComboBox:focus {
                border: 1px solid #1ED760;
            }
            QComboBox QAbstractItemView {
                background-color: #121A15;
                color: #FFFFFF;
                selection-background-color: #1ED760;
                selection-color: #000000;
            }
        """)

        # Varsayılan Sistem Mikrofonu en başta
        self.device_combo.addItem("⭐ Varsayılan Mikrofon (Windows Varsayılanı - Önerilen)", None)

        clean_mics = get_clean_microphones()
        selected_combo_idx = 0
        for i, mic in enumerate(clean_mics):
            self.device_combo.addItem(f"🎙️ {mic['display_name']}", mic["index"])
            if self.selected_device_index is not None and mic["index"] == self.selected_device_index:
                selected_combo_idx = i + 1

        self.device_combo.setCurrentIndex(selected_combo_idx)
        mic_section.addWidget(self.device_combo)

        desc_mic = QLabel("Gereksiz/yinelenen girişler filtrelenmiş ve en kaliteli (WASAPI) donanımlar listelenmiştir.")
        desc_mic.setWordWrap(True)
        desc_mic.setStyleSheet("font-size: 11px; color: #8C9990;")
        mic_section.addWidget(desc_mic)
        layout.addLayout(mic_section)

        layout.addSpacing(6)

        # Alt Butonlar
        btn_box = QHBoxLayout()
        btn_box.setSpacing(10)
        btn_box.addStretch()

        btn_cancel = QPushButton("İptal")
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #16201B;
                border: 1px solid #25362E;
                border-radius: 6px;
                padding: 8px 18px;
                color: #B3B3B3;
                font-weight: 600;
            }
            QPushButton:hover {
                color: #FFFFFF;
                background-color: #1D2A24;
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_save = QPushButton("Kaydet")
        btn_save.setStyleSheet("""
            QPushButton {
                background-color: #1ED760;
                border: none;
                border-radius: 6px;
                padding: 8px 22px;
                color: #000000;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #22E567;
            }
        """)
        btn_save.clicked.connect(self._on_accept)
        btn_box.addWidget(btn_save)

        layout.addLayout(btn_box)

    def _reset_to_pc_name(self):
        pc_name = get_default_username()
        self.user_name_input.setText(pc_name)

    def _on_accept(self):
        self.selected_device_index = self.device_combo.currentData()
        name = self.user_name_input.text().strip()
        self.user_name = name if name else get_default_username()
        self.accept()


# Geriye uyumluluk için alias
MicrophoneSelectDialog = SettingsDialog


# ---------------------------------------------------------------------------
# Gelişmiş & İptal Edilebilir Sesli Arama İş Parçacığı (Cancelable Voice Search)
# ---------------------------------------------------------------------------
class VoiceSearchWorker(QThread):
    text_recognized = pyqtSignal(str)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, device_index=None, duration=4, sample_rate=16000):
        super().__init__()
        self.device_index = device_index
        self.duration = duration
        self.sample_rate = sample_rate
        self._is_cancelled = False

    def cancel(self):
        """Kullanıcı mikrofonu kapatmak/iptal etmek istediğinde çağrılır."""
        self._is_cancelled = True
        if SOUNDDEVICE_AVAILABLE:
            try:
                sd.stop()
            except Exception:
                pass

    def run(self):
        print("\n" + "=" * 65, flush=True)
        print(" [VOICE SEARCH DEBUG] Sesli arama başlatıldı...", flush=True)

        if not SOUNDDEVICE_AVAILABLE or not SPEECH_REC_AVAILABLE:
            err = "Ses kütüphaneleri (sounddevice veya speech_recognition) eksik."
            print(f" [VOICE SEARCH DEBUG] HATA: {err}", flush=True)
            self.error_occurred.emit(err)
            return

        try:
            # Mikrofon cihazı tespiti
            if self.device_index is None:
                try:
                    dev_info = sd.query_devices(kind="input")
                    dev_name = dev_info.get("name", "Sistem Varsayılan Mikrofonu")
                except Exception:
                    dev_name = "Sistem Varsayılan Mikrofonu"
            else:
                try:
                    dev_info = sd.query_devices(self.device_index, kind="input")
                    dev_name = dev_info.get("name", f"Aygıt {self.device_index}")
                except Exception:
                    dev_name = f"Aygıt {self.device_index}"

            # Aday cihazları belirle:
            # 1. Seçili cihaz (None ise sistem varsayılanı)
            # 2. Aynı donanıma ait alternatif API girişleri (DirectSound, MME vb.)
            candidate_devices = [self.device_index]
            if dev_name:
                clean_core = re.sub(r'[^a-zA-Z0-9]', '', dev_name.lower())[:10]
                for idx, dev in enumerate(sd.query_devices()):
                    if dev.get("max_input_channels", 0) > 0 and idx not in candidate_devices:
                        curr_name = dev.get("name", "")
                        curr_core = re.sub(r'[^a-zA-Z0-9]', '', curr_name.lower())[:10]
                        if clean_core and clean_core in curr_core:
                            candidate_devices.append(idx)

            print(f" [VOICE SEARCH DEBUG] Seçili Mikrofon: [{self.device_index}] {dev_name}", flush=True)
            print(f" [VOICE SEARCH DEBUG] Kayıt süresi: {self.duration} saniye", flush=True)

            if self._is_cancelled:
                return

            self.status_changed.emit("Dinleniyor... Şarkı veya sanatçı adını söyleyin")

            # Çoklu Hız & Alternatif API Güvenli Kayıt Döngüsü
            audio_data = None
            actual_rate = 44100
            for dev in candidate_devices:
                try:
                    d_info = sd.query_devices(dev, kind="input") if dev is not None else sd.query_devices(kind="input")
                    native_r = int(d_info.get("default_samplerate", 44100) or 44100)
                    test_rates = [native_r]
                    for r in [48000, 44100, 16000]:
                        if r not in test_rates:
                            test_rates.append(r)
                except Exception:
                    test_rates = [48000, 44100, 16000]

                for r in test_rates:
                    if self._is_cancelled:
                        return
                    try:
                        audio_data = sd.rec(
                            int(self.duration * r),
                            samplerate=r,
                            channels=1,
                            dtype="int16",
                            device=dev,
                        )
                        sd.wait()
                        actual_rate = r
                        print(f" [VOICE SEARCH DEBUG] Başarılı akış: Cihaz [{dev}] @ {r} Hz", flush=True)
                        break
                    except Exception as e_stream:
                        audio_data = None
                        print(f" [VOICE SEARCH DEBUG] Deneme başarısız (Cihaz {dev} @ {r} Hz): {e_stream}", flush=True)

                if audio_data is not None:
                    break

            if audio_data is None:
                raise RuntimeError(f"Mikrofon desteklenen hiçbir hız veya arabirimde açılamadı.")

            if self._is_cancelled:
                print(" [VOICE SEARCH DEBUG] Sesli arama kullanıcı tarafından kapatıldı / iptal edildi.", flush=True)
                return

            # Ses seviyesi analizi (RMS & Peak)
            float_data = audio_data.astype(np.float32)
            rms = np.sqrt(np.mean(float_data ** 2))
            peak = np.max(np.abs(float_data))
            print(f" [VOICE SEARCH DEBUG] Kayıt tamamlandı ({actual_rate} Hz). RMS Seviyesi: {rms:.2f}, Peak: {peak:.2f}", flush=True)

            if rms < 30.0:
                warn_msg = f"Mikrofondan neredeyse hiç ses alınamadı (RMS: {rms:.1f} < 30). Lütfen mikrofona daha yakın konuşun veya doğru mikrofonu seçin."
                print(f" [VOICE SEARCH DEBUG] UYARI: {warn_msg}", flush=True)

            # Dinamik Kazanç (Peak Normalization): Kısık sesleri anlaşılır seviyeye çıkar
            if peak > 0 and peak < 25000:
                gain = min(15.0, 25000.0 / peak)
                float_data = np.clip(float_data * gain, -32767, 32767)
                audio_data = float_data.astype(np.int16)
                print(f" [VOICE SEARCH DEBUG] Otomatik ses kazancı uygulandı: {gain:.2f}x (Yeni RMS: {np.sqrt(np.mean(float_data**2)):.2f})", flush=True)

            if self._is_cancelled:
                return

            self.status_changed.emit("Ses çözümleniyor...")

            # WAV belleğe yaz
            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(actual_rate)
                wf.writeframes(audio_data.tobytes())
            wav_buf.seek(0)

            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_buf) as source:
                audio = recognizer.record(source)

            if self._is_cancelled:
                return

            print(" [VOICE SEARCH DEBUG] Google Speech Recognition motoruna istek gönderiliyor...", flush=True)
            text = ""
            try:
                text = recognizer.recognize_google(audio, language="tr-TR")
                print(f" [VOICE SEARCH DEBUG] Türkçe tanıma başarılı: '{text}'", flush=True)
            except sr.UnknownValueError:
                print(" [VOICE SEARCH DEBUG] Türkçe tanınamadı, evrensel dil deneniyor...", flush=True)
                try:
                    text = recognizer.recognize_google(audio)
                    print(f" [VOICE SEARCH DEBUG] Evrensel tanıma başarılı: '{text}'", flush=True)
                except Exception as e2:
                    print(f" [VOICE SEARCH DEBUG] Tanıma başarısız: {e2}", flush=True)
            except Exception as e:
                print(f" [VOICE SEARCH DEBUG] API Hatası: {e}", flush=True)

            print("=" * 65 + "\n", flush=True)

            if self._is_cancelled:
                return

            if text and text.strip():
                self.text_recognized.emit(text.strip())
            else:
                self.error_occurred.emit("Ses anlaşılamadı. Lütfen mikrofon ayarını kontrol edip tekrar deneyin.")

        except Exception as e:
            if self._is_cancelled:
                return
            logger.exception("Sesli arama sırasında istisna")
            print(f" [VOICE SEARCH DEBUG] KRİTİK HATA: {e}", flush=True)
            print("=" * 65 + "\n", flush=True)
            self.error_occurred.emit(f"Mikrofon hatası: {e}")


# ---------------------------------------------------------------------------
# Yardımcı İşçiler
# ---------------------------------------------------------------------------
class SearchWorker(QThread):
    results_ready = pyqtSignal(list, str)
    error_occurred = pyqtSignal(str)

    def __init__(self, api, query, limit=25):
        super().__init__()
        self.api = api
        self.query = query
        self.limit = limit

    def run(self):
        try:
            results = self.api.search(self.query, limit=self.limit)
            self.results_ready.emit(results, self.query)
        except Exception as e:
            self.error_occurred.emit(str(e))


class ResolveStreamWorker(QThread):
    resolved = pyqtSignal(dict, str, dict)
    error_occurred = pyqtSignal(dict, str)

    def __init__(self, player_service, song):
        super().__init__()
        self.player_service = player_service
        self.song = song

    def run(self):
        try:
            url = self.song.get("url") or f"https://music.youtube.com/watch?v={self.song['videoId']}"
            stream, headers = self.player_service.resolve(url)
            self.resolved.emit(self.song, stream, headers)
        except Exception as e:
            self.error_occurred.emit(self.song, str(e))


class LyricsWorker(QThread):
    lyrics_ready = pyqtSignal(str, str)

    def __init__(self, song):
        super().__init__()
        self.song = song

    def run(self):
        if not syncedlyrics:
            return
        try:
            term = f"{self.song.get('artist', '')} - {self.song.get('title', '')}".strip(" -")
            lyrics = None
            try:
                lyrics = syncedlyrics.search(term, synced_only=True)
            except TypeError:
                lyrics = syncedlyrics.search(term)
            self.lyrics_ready.emit(self.song["videoId"], lyrics or "")
        except Exception:
            self.lyrics_ready.emit(self.song["videoId"], "")


class ImageLoaderWorker(QThread):
    image_loaded = pyqtSignal(str, QPixmap)

    def __init__(self, key, url):
        super().__init__()
        self.key = key
        self.url = url

    def run(self):
        if not self.url:
            return
        try:
            r = requests.get(self.url, headers=IMAGE_HEADERS, timeout=6)
            if r.status_code == 200:
                pix = QPixmap()
                if pix.loadFromData(r.content):
                    self.image_loaded.emit(self.key, pix)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Özel Grafik Kartları
# ---------------------------------------------------------------------------
class RoundedImageWidget(QWidget):
    def __init__(self, size=48, radius=6, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.radius = radius
        self._pixmap = None

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        path = QPainterPath()
        path.addRoundedRect(0, 0, rect.width(), rect.height(), self.radius, self.radius)
        painter.setClipPath(path)

        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            painter.fillRect(rect, QColor("#141F18"))
            painter.setPen(QColor("#1ED760"))
            font = painter.font()
            pt_size = max(1, self.width() // 3)
            font.setPointSize(pt_size)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "♫")


class SmoothHorizontalScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setStyleSheet("background: transparent; border: none;")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            h_bar = self.horizontalScrollBar()
            h_bar.setValue(h_bar.value() - delta)
            event.accept()
        else:
            super().wheelEvent(event)


class HeroBannerWidget(QFrame):
    """Görseldeki görkemli üst karşılama kartı (Hero Banner & Arama)."""
    search_submitted = pyqtSignal(str)
    mic_clicked = pyqtSignal()
    mic_config_clicked = pyqtSignal()

    def __init__(self, user_name=None, parent=None):
        super().__init__(parent)
        self.setObjectName("heroBanner")
        self.setFixedHeight(210)

        if not user_name:
            user_name = get_default_username()

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(28, 20, 28, 20)
        main_layout.setSpacing(20)

        # Sol Bilgiler ve Arama
        left_layout = QVBoxLayout()
        left_layout.setSpacing(6)

        hour = time.localtime().tm_hour
        greeting = "İyi akşamlar" if 17 <= hour or hour < 5 else ("Günaydın" if 5 <= hour < 12 else "İyi günler")
        self.greet_lbl = QLabel(greeting)
        self.greet_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #A0A0A0;")
        left_layout.addWidget(self.greet_lbl)

        self.name_lbl = QLabel(user_name)
        self.name_lbl.setStyleSheet("font-size: 34px; font-weight: 900; color: #1ED760; letter-spacing: -0.5px;")
        left_layout.addWidget(self.name_lbl)

        sub_lbl = QLabel("Bugünün ruh haline uygun parçalar keşfet.")
        sub_lbl.setStyleSheet("font-size: 13px; color: #8C9990; margin-bottom: 8px;")
        left_layout.addWidget(sub_lbl)

        # Arama Kutusu
        search_box = QFrame()
        search_box.setStyleSheet("background-color: #0E1612; border: 1px solid #1C2E24; border-radius: 20px;")
        search_box.setFixedHeight(44)
        sb_layout = QHBoxLayout(search_box)
        sb_layout.setContentsMargins(12, 0, 14, 0)
        sb_layout.setSpacing(8)

        search_icon = QLabel()
        search_icon.setPixmap(qta.icon("fa5s.search", color="#66776E").pixmap(15, 15))
        sb_layout.addWidget(search_icon)

        self.search_input = QLineEdit()
        self.search_input.setStyleSheet("background: transparent; border: none; font-size: 13px; color: #FFFFFF;")
        self.search_input.setPlaceholderText("Sanatçı, şarkı, albüm veya çalma listesi ara...")
        self.search_input.returnPressed.connect(lambda: self.search_submitted.emit(self.search_input.text()))
        sb_layout.addWidget(self.search_input, stretch=1)

        shortcut_lbl = QLabel("Ctrl + K")
        shortcut_lbl.setStyleSheet("font-size: 11px; color: #55665D; font-weight: 700; background-color: #16241C; padding: 3px 8px; border-radius: 4px;")
        sb_layout.addWidget(shortcut_lbl)

        left_layout.addWidget(search_box)
        main_layout.addLayout(left_layout, stretch=1)

        # Sağ: Mikrofon, Zil ve Profil Rozeti
        right_layout = QVBoxLayout()
        right_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        top_icons = QHBoxLayout()
        top_icons.setSpacing(10)

        # Mikrofon Butonu
        self.btn_mic = QPushButton()
        self.btn_mic.setIcon(qta.icon("fa5s.microphone", color="#FFFFFF"))
        self.btn_mic.setProperty("class", "heroIconBtn")
        self.btn_mic.setToolTip("Mikrofonla Sesli Arama")
        self.btn_mic.clicked.connect(self.mic_clicked)
        top_icons.addWidget(self.btn_mic)

        # Mikrofon Seçim/Ayar Butonu
        btn_mic_cfg = QPushButton()
        btn_mic_cfg.setIcon(qta.icon("fa5s.cog", color="#A0A0A0"))
        btn_mic_cfg.setProperty("class", "heroIconBtn")
        btn_mic_cfg.setToolTip("Uygulama & Mikrofon Ayarları")
        btn_mic_cfg.clicked.connect(self.mic_config_clicked)
        top_icons.addWidget(btn_mic_cfg)

        # Bildirim Zili
        btn_bell = QPushButton()
        btn_bell.setIcon(qta.icon("fa5s.bell", color="#FFFFFF"))
        btn_bell.setProperty("class", "heroIconBtn")
        top_icons.addWidget(btn_bell)

        # Profil Rozeti (İlk Harf)
        initial = user_name[0].upper() if user_name else "U"
        self.profile_badge = QLabel(initial)
        self.profile_badge.setFixedSize(36, 36)
        self.profile_badge.setStyleSheet("""
            background-color: #1ED760;
            color: #000000;
            font-weight: 900;
            font-size: 16px;
            border-radius: 18px;
            qproperty-alignment: AlignCenter;
        """)
        top_icons.addWidget(self.profile_badge)

        right_layout.addLayout(top_icons)
        main_layout.addLayout(right_layout)

    def set_user_name(self, user_name):
        clean_name = (user_name or "").strip() or get_default_username()
        self.name_lbl.setText(clean_name)
        initial = clean_name[0].upper() if clean_name else "U"
        self.profile_badge.setText(initial)


class QuickMixBannerCard(QFrame):
    clicked = pyqtSignal(dict)
    play_clicked = pyqtSignal(dict)

    def __init__(self, song, is_selected=False, pixmap_cache=None, parent=None):
        super().__init__(parent)
        self.song = song
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        border_style = "border: 1px solid #1ED760;" if is_selected else "border: 1px solid #1A2620;"
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #101713;
                border-radius: 6px;
                {border_style}
            }}
            QFrame:hover {{
                background-color: #17221C;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(12)

        self.img = RoundedImageWidget(size=64, radius=6)
        vid = song.get("videoId")
        if pixmap_cache and vid in pixmap_cache:
            self.img.set_pixmap(pixmap_cache[vid])
        layout.addWidget(self.img)

        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(2)
        meta_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.title_lbl = QLabel(song.get("title", ""))
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 13px; color: #FFFFFF; background: transparent; border: none;")
        self.title_lbl.setWordWrap(False)
        meta_layout.addWidget(self.title_lbl)

        self.artist_lbl = QLabel(song.get("artist", ""))
        self.artist_lbl.setStyleSheet("font-size: 11px; color: #8A9990; background: transparent; border: none;")
        self.artist_lbl.setWordWrap(False)
        meta_layout.addWidget(self.artist_lbl)

        layout.addLayout(meta_layout, stretch=1)

        # Yeşil Play Butonu
        self.play_btn = QPushButton()
        self.play_btn.setIcon(qta.icon("fa5s.play", color="#000000"))
        self.play_btn.setIconSize(QSize(13, 13))
        self.play_btn.setFixedSize(36, 36)
        self.play_btn.setStyleSheet("""
            QPushButton {
                background-color: #1ED760;
                border-radius: 18px;
                border: none;
            }
            QPushButton:hover {
                background-color: #24F56E;
            }
        """)
        shadow = QGraphicsDropShadowEffect(self.play_btn)
        shadow.setBlurRadius(12)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self.play_btn.setGraphicsEffect(shadow)
        self.play_btn.clicked.connect(lambda: self.play_clicked.emit(self.song))
        layout.addWidget(self.play_btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.song)
        super().mousePressEvent(event)


class MusicGridCard(QFrame):
    clicked = pyqtSignal(dict)
    play_clicked = pyqtSignal(dict)

    def __init__(self, song, pixmap_cache=None, parent=None):
        super().__init__(parent)
        self.song = song
        self.setFixedSize(176, 260)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QFrame {
                background-color: #101613;
                border-radius: 8px;
                border: 1px solid #17221C;
            }
            QFrame:hover {
                background-color: #17221C;
                border: 1px solid #24382E;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Kapak
        cover_container = QWidget()
        cover_container.setFixedSize(152, 152)
        c_layout = QVBoxLayout(cover_container)
        c_layout.setContentsMargins(0, 0, 0, 0)

        self.img = RoundedImageWidget(size=152, radius=8)
        vid = song.get("videoId")
        if pixmap_cache and vid in pixmap_cache:
            self.img.set_pixmap(pixmap_cache[vid])
        c_layout.addWidget(self.img)

        # Hover Play Butonu
        self.hover_play_btn = QPushButton(cover_container)
        self.hover_play_btn.setIcon(qta.icon("fa5s.play", color="#000000"))
        self.hover_play_btn.setIconSize(QSize(16, 16))
        self.hover_play_btn.setFixedSize(44, 44)
        self.hover_play_btn.move(98, 98)
        self.hover_play_btn.setStyleSheet("""
            QPushButton {
                background-color: #1ED760;
                border-radius: 22px;
                border: none;
            }
            QPushButton:hover {
                background-color: #24F56E;
            }
        """)
        shadow = QGraphicsDropShadowEffect(self.hover_play_btn)
        shadow.setBlurRadius(16)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 5)
        self.hover_play_btn.setGraphicsEffect(shadow)
        self.hover_play_btn.hide()
        self.hover_play_btn.clicked.connect(lambda: self.play_clicked.emit(self.song))

        layout.addWidget(cover_container)

        # Metinler
        self.title_lbl = QLabel(song.get("title", ""))
        self.title_lbl.setStyleSheet("font-weight: 700; font-size: 14px; color: #FFFFFF; background: transparent; border: none;")
        self.title_lbl.setFixedHeight(20)
        layout.addWidget(self.title_lbl)

        sub_info = QHBoxLayout()
        sub_info.setSpacing(4)

        self.artist_lbl = QLabel(song.get("artist", ""))
        self.artist_lbl.setStyleSheet("font-size: 12px; color: #8A9990; background: transparent; border: none;")
        sub_info.addWidget(self.artist_lbl, stretch=1)

        dur_text = song.get("duration", "")
        if dur_text:
            dur_lbl = QLabel(dur_text)
            dur_lbl.setStyleSheet("font-size: 11px; color: #5E6E64; background: transparent; border: none;")
            sub_info.addWidget(dur_lbl)

        layout.addLayout(sub_info)
        layout.addStretch()

    def enterEvent(self, event):
        self.hover_play_btn.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_play_btn.hide()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.song)
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Ana Masaüstü Penceresi (yt-music-gui)
# ---------------------------------------------------------------------------
class YtMusicGuiApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("yt-music-gui")
        self.resize(1340, 880)
        self.setMinimumSize(1080, 720)

        # Servisler
        self.api = MusicAPI()
        self.playlist_mgr = PlaylistManager()
        self.settings = self._load_settings()
        self.player = PlayerService(
            normalization=self.settings.get("normalization", True),
            volume=self.settings.get("volume", 90),
        )

        # Durum Verileri
        self.current_song = None
        self.queue = []
        self.queue_index = -1
        self.history = self._load_history()
        self.is_seeking = False
        self.is_shuffle = False
        self.repeat_mode = "none"
        self.lyrics_cache = {}
        self.cover_pixmap_cache = {}
        self.active_workers = []
        self.voice_worker = None

        # Zamanlayıcı (250ms)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self._on_player_tick)
        self.timer.start()

        # UI & Kısayollar
        self.setStyleSheet(MODERN_STYLE)
        self._build_interface()
        self._setup_shortcuts()

        # Başlangıç Yüklemesi
        self.load_featured_and_home()

    # ----------------------------------------------------------------------- Veri Yönetimi
    def _load_settings(self):
        default_user = get_default_username()
        default = {
            "normalization": True,
            "volume": 90,
            "notifications_enabled": True,
            "selected_microphone_index": None,  # None = Sistem Varsayılan Mikrofonu (Önerilen)
            "user_name": default_user,
        }
        data = load_json(SETTINGS_FILE, default)
        if isinstance(data, dict):
            default.update(data)

        # Eğer eski sabit "Nazmican" kayıtlıysa ve bu bilgisayarın adı farklıysa,
        # kullanıcının isteği doğrultusunda varsayılan bilgisayar adını ata
        if default.get("user_name") == "Nazmican" and default_user != "Nazmican":
            default["user_name"] = default_user

        return default

    def _save_settings(self):
        try:
            save_json_atomic(SETTINGS_FILE, self.settings)
        except Exception:
            logger.exception("Ayar kaydı hatası")

    def _load_history(self):
        data = load_json(HISTORY_FILE, [])
        return [h for h in data if isinstance(h, str)] if isinstance(data, list) else []

    def _save_history(self, q):
        if not q:
            return
        if q in self.history:
            self.history.remove(q)
        self.history.insert(0, q)
        self.history = self.history[:50]
        try:
            save_json_atomic(HISTORY_FILE, self.history)
        except Exception:
            pass

    # ----------------------------------------------------------------------- Arayüz İnşası (3 Sütunlu Görsel Düzen)
    def _build_interface(self):
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)

        main_vbox = QVBoxLayout(central)
        main_vbox.setContentsMargins(8, 8, 8, 0)
        main_vbox.setSpacing(8)

        body_splitter = QSplitter(Qt.Orientation.Horizontal)
        body_splitter.setHandleWidth(0)

        # 1. Sol Panel
        self.left_sidebar = self._build_left_sidebar()
        body_splitter.addWidget(self.left_sidebar)

        # 2. Orta Panel
        self.center_frame = self._build_center_frame()
        body_splitter.addWidget(self.center_frame)

        # 3. Sağ Panel ("Şimdi Çalıyor" & Mini Player)
        self.right_panel = self._build_right_panel()
        body_splitter.addWidget(self.right_panel)

        body_splitter.setSizes([260, 720, 340])
        main_vbox.addWidget(body_splitter, stretch=1)

        # 4. Alt Oynatıcı Barı
        self.bottom_bar = self._build_bottom_player_bar()
        main_vbox.addWidget(self.bottom_bar, stretch=0)

    # ----------------------------------------------------------------------- Sol Kenar Çubuğu
    def _build_left_sidebar(self):
        frame = QFrame()
        frame.setObjectName("sidebarFrame")
        frame.setFixedWidth(270)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(10)

        # Logo: Yeşil ses dalgası + yt.music-gui
        logo_box = QHBoxLayout()
        logo_icon = QLabel()
        logo_icon.setPixmap(qta.icon("fa5s.music", color="#1ED760").pixmap(20, 20))
        logo_box.addWidget(logo_icon)

        brand_lbl = QLabel("yt.music-gui")
        brand_lbl.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF; letter-spacing: -0.3px;")
        logo_box.addWidget(brand_lbl)
        logo_box.addStretch()
        layout.addLayout(logo_box)

        layout.addSpacing(6)

        # Ana Sayfa ve Arama Butonları
        self.btn_nav_home = QPushButton("  Ana Sayfa")
        self.btn_nav_home.setIcon(qta.icon("fa5s.home", color="#FFFFFF"))
        self.btn_nav_home.setProperty("class", "navHomeBtn")
        self.btn_nav_home.clicked.connect(self.show_home_view)
        layout.addWidget(self.btn_nav_home)

        self.btn_nav_search = QPushButton("  Arama")
        self.btn_nav_search.setIcon(qta.icon("fa5s.search", color="#A0A0A0"))
        self.btn_nav_search.setProperty("class", "navBtn")
        self.btn_nav_search.clicked.connect(self.show_search_view)
        layout.addWidget(self.btn_nav_search)

        # Kitaplığın Başlığı ve '+'
        lib_head = QHBoxLayout()
        lib_head.setContentsMargins(4, 4, 4, 0)
        lib_title = QLabel("Kitaplığın")
        lib_title.setStyleSheet("font-size: 14px; font-weight: 700; color: #A0A0A0;")
        lib_head.addWidget(lib_title)
        lib_head.addStretch()

        add_btn = QPushButton("+")
        add_btn.setFixedSize(26, 26)
        add_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #A0A0A0;
                font-size: 18px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                color: #FFFFFF;
            }
        """)
        add_btn.clicked.connect(self._create_playlist_dialog)
        lib_head.addWidget(add_btn)
        layout.addLayout(lib_head)

        # Filtre Hapları: Tümü / Çalma Listeleri
        pill_box = QHBoxLayout()
        pill_box.setSpacing(6)
        pill_box.setContentsMargins(4, 0, 4, 0)

        self.pill_all = QPushButton("Tümü")
        self.pill_all.setProperty("class", "pillBtn active")
        self.pill_all.clicked.connect(lambda: self._filter_library("all"))
        pill_box.addWidget(self.pill_all)

        self.pill_pl = QPushButton("Çalma Listeleri")
        self.pill_pl.setProperty("class", "pillBtn")
        self.pill_pl.clicked.connect(lambda: self._filter_library("playlists"))
        pill_box.addWidget(self.pill_pl)

        pill_box.addStretch()
        layout.addLayout(pill_box)

        # Hızlı Erişim Başlığı
        layout.addSpacing(6)
        qa_lbl = QLabel("Hızlı Erişim")
        qa_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #5E6E64; padding-left: 6px;")
        layout.addWidget(qa_lbl)

        # Beğenilen Şarkılar Kartı (Mavi yuvarlak kalp)
        self.btn_fav_access = QPushButton("  Beğenilen Şarkılar\n   Çalma Listesi • 0 şarkı")
        self.btn_fav_access.setIcon(qta.icon("fa5s.heart", color="#1ED760"))
        self.btn_fav_access.setProperty("class", "quickAccessBtn")
        self.btn_fav_access.clicked.connect(lambda: self.open_playlist_view(FAVORITES_NAME))
        layout.addWidget(self.btn_fav_access)

        btn_recent_access = QPushButton("  Yakın Zamanda Çalınanlar")
        btn_recent_access.setIcon(qta.icon("fa5s.history", color="#8A9990"))
        btn_recent_access.setProperty("class", "quickAccessBtn")
        btn_recent_access.clicked.connect(self.show_home_view)
        layout.addWidget(btn_recent_access)

        btn_dl_access = QPushButton("  İndirilenler")
        btn_dl_access.setIcon(qta.icon("fa5s.arrow-circle-down", color="#8A9990"))
        btn_dl_access.setProperty("class", "quickAccessBtn")
        layout.addWidget(btn_dl_access)

        btn_custom_pl = QPushButton("  Oluşturduğun Çalma Listeleri")
        btn_custom_pl.setIcon(qta.icon("fa5s.list-ul", color="#8A9990"))
        btn_custom_pl.setProperty("class", "quickAccessBtn")
        btn_custom_pl.clicked.connect(lambda: self._filter_library("playlists"))
        layout.addWidget(btn_custom_pl)

        layout.addStretch()

        # Sol Alt: Yeşil Ses Dalgaları Visualizer & Slogan
        vis_box = QFrame()
        vis_box.setStyleSheet("background-color: #0B100D; border: 1px solid #141F18; border-radius: 8px; padding: 10px;")
        v_layout = QVBoxLayout(vis_box)
        v_layout.setSpacing(6)

        # 8 çubuklu yeşil dalga simülasyonu
        waves_layout = QHBoxLayout()
        waves_layout.setSpacing(3)
        waves_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.wave_bars = []
        for _ in range(12):
            bar = QFrame()
            bar.setFixedWidth(3)
            bar.setFixedHeight(14)
            bar.setStyleSheet("background-color: #1ED760; border-radius: 1px;")
            waves_layout.addWidget(bar)
            self.wave_bars.append(bar)
        v_layout.addLayout(waves_layout)

        vis_text = QLabel("Müziğin her zaman seninle olsun.")
        vis_text.setStyleSheet("font-size: 11px; color: #5E6E64; qproperty-alignment: AlignCenter;")
        v_layout.addWidget(vis_text)
        layout.addWidget(vis_box)

        # En Alt: Ayarlar Butonu
        btn_settings = QPushButton("  Ayarlar & Mikrofon")
        btn_settings.setIcon(qta.icon("fa5s.cog", color="#8A9990"))
        btn_settings.setProperty("class", "quickAccessBtn")
        btn_settings.clicked.connect(self._open_mic_select_dialog)
        layout.addWidget(btn_settings)

        return frame

    def _refresh_library_list(self):
        fav_count = len(self.playlist_mgr.get_songs(FAVORITES_NAME) or [])
        self.btn_fav_access.setText(f"  Beğenilen Şarkılar\n   Çalma Listesi • {fav_count} şarkı")

    def _filter_library(self, mode):
        self.pill_all.setProperty("class", "pillBtn active" if mode == "all" else "pillBtn")
        self.pill_pl.setProperty("class", "pillBtn active" if mode == "playlists" else "pillBtn")
        self.pill_all.style().polish(self.pill_all)
        self.pill_pl.style().polish(self.pill_pl)

    # ----------------------------------------------------------------------- Orta Panel
    def _build_center_frame(self):
        frame = QFrame()
        frame.setObjectName("contentFrame")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Stacked Widget (Home, Search, Playlist, Lyrics)
        self.stack = QStackedWidget()
        self.view_home = self._build_home_view()
        self.view_search = self._build_search_view()
        self.view_playlist = self._build_playlist_view()
        self.view_lyrics = self._build_lyrics_view()

        self.stack.addWidget(self.view_home)      # 0
        self.stack.addWidget(self.view_search)    # 1
        self.stack.addWidget(self.view_playlist)  # 2
        self.stack.addWidget(self.view_lyrics)    # 3

        layout.addWidget(self.stack, stretch=1)
        return frame

    # ----------------------------------------------------------------------- Ana Sayfa Görünümü (Home)
    def _build_home_view(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 20, 20, 24)
        layout.setSpacing(24)

        # 1. Hero Banner (Karşılama & Sesli Arama)
        self.hero_banner = HeroBannerWidget(user_name=self.settings.get("user_name", get_default_username()))
        self.hero_banner.search_submitted.connect(self._on_hero_search)
        self.hero_banner.mic_clicked.connect(self.toggle_voice_search)
        self.hero_banner.mic_config_clicked.connect(self._open_mic_select_dialog)
        layout.addWidget(self.hero_banner)

        # 2. İyi Akşamlar Bölümü (2x3 Grid)
        layout.addWidget(self._create_section_header("İyi Akşamlar", show_all_action=True))
        self.quick_mix_grid = QGridLayout()
        self.quick_mix_grid.setSpacing(12)
        layout.addLayout(self.quick_mix_grid)

        # 3. Son Çalınanlar Bölümü
        layout.addWidget(self._create_section_header("Son Çalınanlar", show_all_action=True))
        self.recent_cards_scroll = self._create_horizontal_cards_container()
        layout.addWidget(self.recent_cards_scroll)

        # 4. Senin İçin Önerilenler Bölümü (Tür Filtre Hapları)
        layout.addWidget(self._create_section_header("Senin İçin Önerilenler", show_all_action=True))

        genre_pills = QHBoxLayout()
        genre_pills.setSpacing(8)
        self.genre_buttons = []
        genres = ["Tümü", "Rap", "Pop", "Rock", "Arabesk", "Alternatif", "Elektronik"]
        for g in genres:
            btn = QPushButton(g)
            btn.setProperty("class", "pillBtn active" if g == "Tümü" else "pillBtn")
            btn.clicked.connect(lambda _, gen=g: self._on_genre_clicked(gen))
            genre_pills.addWidget(btn)
            self.genre_buttons.append(btn)
        genre_pills.addStretch()
        layout.addLayout(genre_pills)

        self.recommended_cards_scroll = self._create_horizontal_cards_container()
        layout.addWidget(self.recommended_cards_scroll)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def _create_section_header(self, title, show_all_action=False):
        head = QWidget()
        h_layout = QHBoxLayout(head)
        h_layout.setContentsMargins(0, 4, 0, 0)

        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 20px; font-weight: 800; color: #FFFFFF;")
        h_layout.addWidget(lbl)

        h_layout.addStretch()

        if show_all_action:
            show_all = QPushButton("Tümünü Göster  >")
            show_all.setStyleSheet("background: transparent; color: #8A9990; font-size: 12px; font-weight: 700; border: none;")
            show_all.setCursor(Qt.CursorShape.PointingHandCursor)
            h_layout.addWidget(show_all)
        return head

    def _create_horizontal_cards_container(self):
        scroll = SmoothHorizontalScrollArea()
        scroll.setFixedHeight(275)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        c_layout = QHBoxLayout(content)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(14)
        c_layout.addStretch()

        scroll.setWidget(content)
        scroll._card_layout = c_layout
        return scroll

    def _on_genre_clicked(self, genre):
        for btn in self.genre_buttons:
            is_act = (btn.text() == genre)
            btn.setProperty("class", "pillBtn active" if is_act else "pillBtn")
            btn.style().polish(btn)
        q = "Pop Hits" if genre == "Tümü" else f"{genre} Türkçe"
        worker = SearchWorker(self.api, q, limit=10)
        worker.results_ready.connect(self._on_genre_results_ready)
        worker.start()
        self.active_workers.append(worker)

    def _on_genre_results_ready(self, songs, query):
        layout = self.recommended_cards_scroll._card_layout
        for i in reversed(range(layout.count() - 1)):
            w = layout.itemAt(i).widget()
            if w:
                w.deleteLater()
        for s in songs:
            card = MusicGridCard(s, self.cover_pixmap_cache)
            card.clicked.connect(self.play_single_song)
            card.play_clicked.connect(self.play_single_song)
            layout.insertWidget(layout.count() - 1, card)
            if s.get("thumbnail"):
                self._fetch_image_for_widget(s["videoId"], s["thumbnail"], card.img)

    # ----------------------------------------------------------------------- Arama Görünümü
    def _build_search_view(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(20)

        self.search_header_title = QLabel("Arama Sonuçları")
        self.search_header_title.setStyleSheet("font-size: 24px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(self.search_header_title)

        self.search_grid = QGridLayout()
        self.search_grid.setSpacing(16)
        layout.addLayout(self.search_grid)

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    # ----------------------------------------------------------------------- Çalma Listesi Görünümü
    def _build_playlist_view(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(16)

        banner = QWidget()
        b_layout = QHBoxLayout(banner)
        b_layout.setContentsMargins(0, 0, 0, 16)
        b_layout.setSpacing(20)

        self.pl_cover_hero = RoundedImageWidget(size=140, radius=8)
        b_layout.addWidget(self.pl_cover_hero)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(6)
        type_lbl = QLabel("ÇALMA LİSTESİ")
        type_lbl.setStyleSheet("font-size: 11px; font-weight: 700; color: #1ED760;")
        info_layout.addWidget(type_lbl)

        self.pl_hero_title = QLabel("Çalma Listesi")
        self.pl_hero_title.setStyleSheet("font-size: 38px; font-weight: 900; color: #FFFFFF;")
        info_layout.addWidget(self.pl_hero_title)

        self.pl_hero_desc = QLabel("0 şarkı")
        self.pl_hero_desc.setStyleSheet("font-size: 13px; color: #B3B3B3;")
        info_layout.addWidget(self.pl_hero_desc)

        b_layout.addLayout(info_layout, stretch=1)
        layout.addWidget(banner)

        # Kontroller
        act_bar = QHBoxLayout()
        act_bar.setSpacing(14)

        self.btn_hero_play = QPushButton()
        self.btn_hero_play.setIcon(qta.icon("fa5s.play", color="#000000"))
        self.btn_hero_play.setIconSize(QSize(20, 20))
        self.btn_hero_play.setFixedSize(52, 52)
        self.btn_hero_play.setStyleSheet("""
            QPushButton {
                background-color: #1ED760;
                border-radius: 26px;
                border: none;
            }
            QPushButton:hover {
                background-color: #24F56E;
            }
        """)
        self.btn_hero_play.clicked.connect(self._play_current_playlist_all)
        act_bar.addWidget(self.btn_hero_play)

        self.btn_hero_shuffle = QPushButton()
        self.btn_hero_shuffle.setIcon(qta.icon("fa5s.random", color="#B3B3B3"))
        self.btn_hero_shuffle.setFixedSize(36, 36)
        self.btn_hero_shuffle.setStyleSheet("background: transparent; border: none;")
        self.btn_hero_shuffle.setToolTip("Karışık Çal")
        self.btn_hero_shuffle.clicked.connect(self._shuffle_current_playlist)
        act_bar.addWidget(self.btn_hero_shuffle)

        self.btn_hero_delete = QPushButton()
        self.btn_hero_delete.setIcon(qta.icon("fa5s.trash-alt", color="#B3B3B3"))
        self.btn_hero_delete.setFixedSize(36, 36)
        self.btn_hero_delete.setStyleSheet("background: transparent; border: none;")
        self.btn_hero_delete.setToolTip("Listeyi Sil")
        self.btn_hero_delete.clicked.connect(self._delete_current_playlist)
        act_bar.addWidget(self.btn_hero_delete)

        act_bar.addStretch()
        layout.addLayout(act_bar)

        self.playlist_songs_table = QTableWidget()
        self.playlist_songs_table.setColumnCount(5)
        self.playlist_songs_table.setHorizontalHeaderLabels(["#", "Başlık", "Sanatçı", "Süre", "İşlemler"])
        self.playlist_songs_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.playlist_songs_table.setColumnWidth(0, 44)
        self.playlist_songs_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.playlist_songs_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.playlist_songs_table.setColumnWidth(2, 220)
        self.playlist_songs_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.playlist_songs_table.setColumnWidth(3, 70)
        self.playlist_songs_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.playlist_songs_table.setColumnWidth(4, 80)

        self.playlist_songs_table.verticalHeader().setVisible(False)
        self.playlist_songs_table.verticalHeader().setDefaultSectionSize(48)
        self.playlist_songs_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.playlist_songs_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.playlist_songs_table.setStyleSheet("background: transparent; border: none;")
        self.playlist_songs_table.cellDoubleClicked.connect(self._on_playlist_table_double_click)

        layout.addWidget(self.playlist_songs_table)
        scroll.setWidget(container)
        return scroll

    # ----------------------------------------------------------------------- Şarkı Sözleri Görünümü
    def _build_lyrics_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(16)

        self.lyrics_hero_title = QLabel("Şarkı Sözleri")
        self.lyrics_hero_title.setStyleSheet("font-size: 26px; font-weight: 800; color: #FFFFFF;")
        layout.addWidget(self.lyrics_hero_title)

        hint = QLabel("💡 Şarkı akışına göre sözler anlık olarak parlar. İstediğiniz satıra tıklayarak o saniyeye atlayabilirsiniz.")
        hint.setStyleSheet("font-size: 12px; color: #777777;")
        layout.addWidget(hint)

        self.karaoke_list = QListWidget()
        self.karaoke_list.setObjectName("karaokeList")
        self.karaoke_delegate = KaraokeItemDelegate(self.karaoke_list)
        self.karaoke_list.setItemDelegate(self.karaoke_delegate)
        self.karaoke_list.itemClicked.connect(self._on_karaoke_line_clicked)
        layout.addWidget(self.karaoke_list)

        return container

    def _on_karaoke_line_clicked(self, item):
        time_ms = item.data(Qt.ItemDataRole.UserRole)
        if time_ms is not None and self.player.available:
            self.player.seek_to(time_ms)

    # ----------------------------------------------------------------------- Sağ Panel ("Şimdi Çalıyor" & Mini Player)
    def _build_right_panel(self):
        frame = QFrame()
        frame.setObjectName("rightPanelFrame")
        frame.setFixedWidth(320)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("♫  Şimdi Çalıyor")
        header.setStyleSheet("font-size: 15px; font-weight: 800; color: #1ED760;")
        layout.addWidget(header)

        # Büyük Albüm Kapağı
        self.rp_cover = RoundedImageWidget(size=288, radius=8)
        layout.addWidget(self.rp_cover)

        # Şarkı Başlığı ve Sanatçı
        meta_box = QHBoxLayout()
        t_layout = QVBoxLayout()
        t_layout.setSpacing(2)

        self.rp_title = QLabel("Henüz Çalınan Parça Yok")
        self.rp_title.setStyleSheet("font-size: 16px; font-weight: 800; color: #FFFFFF;")
        self.rp_title.setWordWrap(True)
        t_layout.addWidget(self.rp_title)

        self.rp_artist = QLabel("yt-music-gui")
        self.rp_artist.setStyleSheet("font-size: 13px; color: #8A9990;")
        t_layout.addWidget(self.rp_artist)
        meta_box.addLayout(t_layout, stretch=1)

        rp_heart = QPushButton()
        rp_heart.setIcon(qta.icon("fa5.heart", color="#8A9990"))
        rp_heart.setFixedSize(30, 30)
        rp_heart.setStyleSheet("background: transparent; border: none;")
        rp_heart.clicked.connect(self._toggle_current_favorite)
        meta_box.addWidget(rp_heart)
        layout.addLayout(meta_box)

        # Mini Oynatıcı İlerleme Çubuğu ve Süreler
        rp_prog = QHBoxLayout()
        rp_prog.setSpacing(6)
        self.rp_cur_time = QLabel("0:00")
        self.rp_cur_time.setStyleSheet("font-size: 10px; color: #5E6E64;")
        rp_prog.addWidget(self.rp_cur_time)

        self.rp_slider = QSlider(Qt.Orientation.Horizontal)
        self.rp_slider.setRange(0, 1000)
        self.rp_slider.sliderReleased.connect(self._on_seek_released)
        rp_prog.addWidget(self.rp_slider)

        self.rp_total_time = QLabel("0:00")
        self.rp_total_time.setStyleSheet("font-size: 10px; color: #5E6E64;")
        rp_prog.addWidget(self.rp_total_time)
        layout.addLayout(rp_prog)

        # Mini Oynatıcı Kontrolleri (Büyük Yeşil Oynat Butonlu)
        rp_ctrls = QHBoxLayout()
        rp_ctrls.setSpacing(10)
        rp_ctrls.setAlignment(Qt.AlignmentFlag.AlignCenter)

        rp_prev = QPushButton()
        rp_prev.setIcon(qta.icon("fa5s.step-backward", color="#FFFFFF"))
        rp_prev.setProperty("class", "mediaCtrlBtn")
        rp_prev.clicked.connect(self.play_previous)
        rp_ctrls.addWidget(rp_prev)

        self.rp_play_btn = QPushButton()
        self.rp_play_btn.setIcon(qta.icon("fa5s.play", color="#000000"))
        self.rp_play_btn.setIconSize(QSize(16, 16))
        self.rp_play_btn.setObjectName("playPauseCircleBtn")
        self.rp_play_btn.clicked.connect(self.toggle_play_pause)
        rp_ctrls.addWidget(self.rp_play_btn)

        rp_next = QPushButton()
        rp_next.setIcon(qta.icon("fa5s.step-forward", color="#FFFFFF"))
        rp_next.setProperty("class", "mediaCtrlBtn")
        rp_next.clicked.connect(self.play_next)
        rp_ctrls.addWidget(rp_next)

        layout.addLayout(rp_ctrls)

        # Çalma Listesi / Sıradaki Şarkılar Tablosu
        layout.addSpacing(6)
        pl_title = QLabel("Çalma Listesi")
        pl_title.setStyleSheet("font-size: 12px; font-weight: 700; color: #A0A0A0;")
        layout.addWidget(pl_title)

        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setStyleSheet("""
            QListWidget {
                background-color: #080C0A;
                border: 1px solid #141F18;
                border-radius: 8px;
            }
            QListWidget::item {
                padding: 6px 8px;
                border-bottom: 1px solid #0F1713;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #121C16;
            }
        """)
        self.queue_list_widget.itemDoubleClicked.connect(self._on_queue_item_clicked)
        layout.addWidget(self.queue_list_widget, stretch=1)

        return frame

    def _refresh_queue_ui(self):
        self.queue_list_widget.clear()
        for idx, s in enumerate(self.queue):
            item = QListWidgetItem()
            is_active = (idx == self.queue_index)
            prefix = "▶ " if is_active else f"{idx + 1}. "
            item.setText(f"{prefix}{s.get('title', '')} — {s.get('artist', '')}")
            if is_active:
                item.setForeground(QColor("#1ED760"))
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            else:
                item.setForeground(QColor("#A0A0A0"))
            self.queue_list_widget.addItem(item)
        if 0 <= self.queue_index < self.queue_list_widget.count():
            self.queue_list_widget.scrollToItem(self.queue_list_widget.item(self.queue_index))

    def _on_queue_item_clicked(self, item):
        row = self.queue_list_widget.row(item)
        if 0 <= row < len(self.queue):
            self.play_song_at_index(row)

    # ----------------------------------------------------------------------- Alt Oynatıcı Barı
    def _build_bottom_player_bar(self):
        bar = QFrame()
        bar.setObjectName("bottomPlayerBar")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(16)

        # Sol
        left_box = QHBoxLayout()
        left_box.setSpacing(12)

        self.bar_cover = RoundedImageWidget(size=56, radius=6)
        left_box.addWidget(self.bar_cover)

        meta_layout = QVBoxLayout()
        meta_layout.setSpacing(2)
        meta_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.bar_title = QLabel("Şarkı Seçilmedi")
        self.bar_title.setStyleSheet("font-weight: 700; font-size: 13px; color: #FFFFFF;")
        self.bar_artist = QLabel("yt-music-gui")
        self.bar_artist.setStyleSheet("font-size: 11px; color: #8A9990;")

        meta_layout.addWidget(self.bar_title)
        meta_layout.addWidget(self.bar_artist)
        left_box.addLayout(meta_layout)

        self.bar_heart_btn = QPushButton()
        self.bar_heart_btn.setIcon(qta.icon("fa5.heart", color="#B3B3B3"))
        self.bar_heart_btn.setIconSize(QSize(16, 16))
        self.bar_heart_btn.setFixedSize(32, 32)
        self.bar_heart_btn.setStyleSheet("background: transparent; border: none;")
        self.bar_heart_btn.setToolTip("Favorilere Ekle / Çıkar")
        self.bar_heart_btn.clicked.connect(self._toggle_current_favorite)
        left_box.addWidget(self.bar_heart_btn)

        layout.addLayout(left_box, stretch=3)

        # Orta Kontroller
        center_box = QVBoxLayout()
        center_box.setSpacing(4)
        center_box.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ctrls = QHBoxLayout()
        ctrls.setSpacing(14)
        ctrls.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.bar_shuffle_btn = QPushButton()
        self.bar_shuffle_btn.setIcon(qta.icon("fa5s.random", color="#B3B3B3"))
        self.bar_shuffle_btn.setProperty("class", "mediaCtrlBtn")
        self.bar_shuffle_btn.setToolTip("Karışık Çal")
        self.bar_shuffle_btn.clicked.connect(self._toggle_shuffle)
        ctrls.addWidget(self.bar_shuffle_btn)

        self.bar_prev_btn = QPushButton()
        self.bar_prev_btn.setIcon(qta.icon("fa5s.step-backward", color="#FFFFFF"))
        self.bar_prev_btn.setProperty("class", "mediaCtrlBtn")
        self.bar_prev_btn.setToolTip("Önceki Şarkı")
        self.bar_prev_btn.clicked.connect(self.play_previous)
        ctrls.addWidget(self.bar_prev_btn)

        self.bar_play_btn = QPushButton()
        self.bar_play_btn.setIcon(qta.icon("fa5s.play", color="#000000"))
        self.bar_play_btn.setIconSize(QSize(16, 16))
        self.bar_play_btn.setObjectName("playPauseCircleBtn")
        self.bar_play_btn.clicked.connect(self.toggle_play_pause)
        ctrls.addWidget(self.bar_play_btn)

        self.bar_next_btn = QPushButton()
        self.bar_next_btn.setIcon(qta.icon("fa5s.step-forward", color="#FFFFFF"))
        self.bar_next_btn.setProperty("class", "mediaCtrlBtn")
        self.bar_next_btn.setToolTip("Sonraki Şarkı")
        self.bar_next_btn.clicked.connect(self.play_next)
        ctrls.addWidget(self.bar_next_btn)

        self.bar_repeat_btn = QPushButton()
        self.bar_repeat_btn.setIcon(qta.icon("fa5s.redo", color="#B3B3B3"))
        self.bar_repeat_btn.setProperty("class", "mediaCtrlBtn")
        self.bar_repeat_btn.setToolTip("Tekrar Modu")
        self.bar_repeat_btn.clicked.connect(self._cycle_repeat)
        ctrls.addWidget(self.bar_repeat_btn)

        center_box.addLayout(ctrls)

        # İlerleme Çubuğu
        prog_layout = QHBoxLayout()
        prog_layout.setSpacing(8)

        self.bar_time_cur = QLabel("0:00")
        self.bar_time_cur.setStyleSheet("font-size: 11px; color: #8A9990;")
        prog_layout.addWidget(self.bar_time_cur)

        self.bar_seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.bar_seek_slider.setRange(0, 1000)
        self.bar_seek_slider.sliderPressed.connect(lambda: setattr(self, "is_seeking", True))
        self.bar_seek_slider.sliderReleased.connect(self._on_seek_released)
        prog_layout.addWidget(self.bar_seek_slider)

        self.bar_time_total = QLabel("0:00")
        self.bar_time_total.setStyleSheet("font-size: 11px; color: #8A9990;")
        prog_layout.addWidget(self.bar_time_total)

        center_box.addLayout(prog_layout)
        layout.addLayout(center_box, stretch=5)

        # Sağ Kontroller
        right_box = QHBoxLayout()
        right_box.setSpacing(10)
        right_box.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        lyrics_btn = QPushButton()
        lyrics_btn.setIcon(qta.icon("fa5s.microphone-alt", color="#B3B3B3"))
        lyrics_btn.setProperty("class", "mediaCtrlBtn")
        lyrics_btn.setToolTip("Şarkı Sözleri")
        lyrics_btn.clicked.connect(self.show_lyrics_view)
        right_box.addWidget(lyrics_btn)

        vol_icon = QLabel()
        vol_icon.setPixmap(qta.icon("fa5s.volume-up", color="#B3B3B3").pixmap(16, 16))
        right_box.addWidget(vol_icon)

        self.bar_vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.bar_vol_slider.setRange(0, 100)
        self.bar_vol_slider.setValue(self.player.get_volume())
        self.bar_vol_slider.setFixedWidth(90)
        self.bar_vol_slider.valueChanged.connect(self._on_volume_changed)
        right_box.addWidget(self.bar_vol_slider)

        layout.addLayout(right_box, stretch=2)
        return bar

    # ----------------------------------------------------------------------- Sesli Arama ve Mikrofon Seçimi
    def _open_mic_select_dialog(self):
        current_idx = self.settings.get("selected_microphone_index", None)
        current_user = self.settings.get("user_name", get_default_username())
        dlg = SettingsDialog(current_device_index=current_idx, current_user_name=current_user, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings["selected_microphone_index"] = dlg.selected_device_index
            self.settings["user_name"] = dlg.user_name
            self._save_settings()
            self.hero_banner.set_user_name(dlg.user_name)
            print(f"[SETTINGS] Ayarlar kaydedildi: Mikrofon={dlg.selected_device_index}, İsim='{dlg.user_name}'", flush=True)

    def toggle_voice_search(self):
        """Mikrofon butonuna basıldığında dinlemeyi başlatır veya kapatır."""
        if self.voice_worker and self.voice_worker.isRunning():
            self.stop_voice_search()
            return
        self.start_voice_search()

    def stop_voice_search(self):
        """Sesli aramayı / mikrofonu kapatır ve iptal eder."""
        if self.voice_worker and self.voice_worker.isRunning():
            print(" [VOICE SEARCH] Mikrofon kapatılıyor / iptal ediliyor...", flush=True)
            self.voice_worker.cancel()
            self.voice_worker.wait(300)
            self.voice_worker = None
        self._on_voice_finished()
        self.hero_banner.search_input.setPlaceholderText("Sanatçı, şarkı, albüm veya çalma listesi ara...")

    def start_voice_search(self):
        if not SOUNDDEVICE_AVAILABLE or not SPEECH_REC_AVAILABLE:
            QMessageBox.warning(self, "Uyarı", "Mikrofon ses tanıma kütüphanesi (sounddevice / speech_recognition) bulunamadı.")
            return

        if self.voice_worker and self.voice_worker.isRunning():
            self.stop_voice_search()
            return

        # Mikrofon butonunu aktif (kırmızı atan) hale getir
        self.hero_banner.btn_mic.setIcon(qta.icon("fa5s.microphone", color="#FF3B30", animation=qta.Pulse(self.hero_banner.btn_mic)))
        self.hero_banner.btn_mic.setToolTip("Mikrofonu Kapat / İptal Et (Tıklayın)")
        self.hero_banner.search_input.setPlaceholderText("🎤 Dinleniyor... (Kapatmak için mikrofona tekrar tıklayın)")
        self.hero_banner.search_input.clear()

        mic_idx = self.settings.get("selected_microphone_index", None)
        self.voice_worker = VoiceSearchWorker(device_index=mic_idx, duration=4)
        self.voice_worker.status_changed.connect(lambda txt: self.hero_banner.search_input.setPlaceholderText(f"🎤 {txt}"))
        self.voice_worker.text_recognized.connect(self._on_voice_recognized)
        self.voice_worker.error_occurred.connect(self._on_voice_error)
        self.voice_worker.finished.connect(self._on_voice_finished)
        self.voice_worker.start()

    def _on_voice_recognized(self, text):
        print(f"[VOICE SUCCESS] Sesli arama sonucu alındı: '{text}' -> Arama yapılıyor...", flush=True)
        self.hero_banner.search_input.setText(text)
        self.hero_banner.search_input.setPlaceholderText("Sanatçı, şarkı, albüm veya çalma listesi ara...")
        self.on_search_submitted(text)

    def _on_voice_error(self, err):
        print(f"[VOICE ERROR] {err}", flush=True)
        self.hero_banner.search_input.setPlaceholderText(f"⚠️ {err}")
        QTimer.singleShot(4000, lambda: self.hero_banner.search_input.setPlaceholderText("Sanatçı, şarkı, albüm veya çalma listesi ara..."))

    def _on_voice_finished(self):
        self.hero_banner.btn_mic.setIcon(qta.icon("fa5s.microphone", color="#FFFFFF"))
        self.hero_banner.btn_mic.setToolTip("Mikrofonla Sesli Arama")

    # ----------------------------------------------------------------------- Gezinme
    def show_home_view(self):
        self.btn_nav_home.setProperty("class", "navHomeBtn")
        self.btn_nav_search.setProperty("class", "navBtn")
        self.btn_nav_home.style().polish(self.btn_nav_home)
        self.btn_nav_search.style().polish(self.btn_nav_search)
        self.stack.setCurrentIndex(0)

    def show_search_view(self):
        self.btn_nav_home.setProperty("class", "navBtn")
        self.btn_nav_search.setProperty("class", "navHomeBtn")
        self.btn_nav_home.style().polish(self.btn_nav_home)
        self.btn_nav_search.style().polish(self.btn_nav_search)
        self.stack.setCurrentIndex(1)

    def show_lyrics_view(self):
        self.stack.setCurrentIndex(3)

    def open_playlist_view(self, name):
        self.current_playlist_name = name
        self.pl_hero_title.setText(name)
        songs = self.playlist_mgr.get_songs(name) or []
        self.pl_hero_desc.setText(f"{len(songs)} şarkı")

        self.playlist_songs_table.setRowCount(len(songs))
        for row, s in enumerate(songs):
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.playlist_songs_table.setItem(row, 0, idx_item)

            t_item = QTableWidgetItem(s.get("title", ""))
            t_item.setData(Qt.ItemDataRole.UserRole, s)
            self.playlist_songs_table.setItem(row, 1, t_item)

            a_item = QTableWidgetItem(s.get("artist", ""))
            self.playlist_songs_table.setItem(row, 2, a_item)

            d_item = QTableWidgetItem(s.get("duration", ""))
            d_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.playlist_songs_table.setItem(row, 3, d_item)

            del_btn = QPushButton()
            del_btn.setIcon(qta.icon("fa5s.times", color="#777777"))
            del_btn.setFixedSize(28, 28)
            del_btn.setStyleSheet("background: transparent; border: none;")
            del_btn.setToolTip("Listeden Kaldır")
            del_btn.clicked.connect(lambda _, song=s: self._remove_from_current_playlist(song))
            self.playlist_songs_table.setCellWidget(row, 4, del_btn)

        if songs and songs[0].get("thumbnail"):
            self._fetch_image_for_widget(songs[0]["videoId"], songs[0]["thumbnail"], self.pl_cover_hero)

        self.stack.setCurrentIndex(2)

    # ----------------------------------------------------------------------- Ana Sayfa İçeriği
    def load_featured_and_home(self):
        seed = self.history[0] if self.history else "Pompalımasyon"
        worker = SearchWorker(self.api, seed, limit=16)
        worker.results_ready.connect(self._on_home_data_ready)
        worker.start()
        self.active_workers.append(worker)

    def _on_home_data_ready(self, songs, query):
        if not songs:
            return

        # 2x3 Quick Mix
        for i in reversed(range(self.quick_mix_grid.count())):
            w = self.quick_mix_grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        for idx, s in enumerate(songs[:6]):
            card = QuickMixBannerCard(s, is_selected=(idx == 0), pixmap_cache=self.cover_pixmap_cache)
            card.clicked.connect(self.play_single_song)
            card.play_clicked.connect(self.play_single_song)
            row = idx // 3
            col = idx % 3
            self.quick_mix_grid.addWidget(card, row, col)
            if s.get("thumbnail"):
                self._fetch_image_for_widget(s["videoId"], s["thumbnail"], card.img)

        # Son Çalınanlar
        layout_recents = self.recent_cards_scroll._card_layout
        for s in songs[:8]:
            card = MusicGridCard(s, self.cover_pixmap_cache)
            card.clicked.connect(self.play_single_song)
            card.play_clicked.connect(self.play_single_song)
            layout_recents.insertWidget(layout_recents.count() - 1, card)
            if s.get("thumbnail"):
                self._fetch_image_for_widget(s["videoId"], s["thumbnail"], card.img)

        # Senin İçin Önerilenler
        layout_recom = self.recommended_cards_scroll._card_layout
        for s in songs[8:16]:
            card = MusicGridCard(s, self.cover_pixmap_cache)
            card.clicked.connect(self.play_single_song)
            card.play_clicked.connect(self.play_single_song)
            layout_recom.insertWidget(layout_recom.count() - 1, card)
            if s.get("thumbnail"):
                self._fetch_image_for_widget(s["videoId"], s["thumbnail"], card.img)

        self._refresh_library_list()

    # ----------------------------------------------------------------------- Arama Akışı
    def _on_hero_search(self, q):
        self.on_search_submitted(q)

    def on_search_submitted(self, query=None):
        q = (query or self.hero_banner.search_input.text()).strip()
        if not q:
            return
        self._save_history(q)
        self.show_search_view()
        self.search_header_title.setText(f"'{q}' için En İyi Sonuçlar")

        for i in reversed(range(self.search_grid.count())):
            w = self.search_grid.itemAt(i).widget()
            if w:
                w.deleteLater()

        worker = SearchWorker(self.api, q, limit=20)
        worker.results_ready.connect(self._on_search_results)
        worker.error_occurred.connect(lambda err: QMessageBox.warning(self, "Arama Hatası", err))
        worker.start()
        self.active_workers.append(worker)

    def _on_search_results(self, songs, query):
        if not songs:
            self.search_header_title.setText("Sonuç bulunamadı.")
            return

        columns = 4
        for idx, s in enumerate(songs):
            card = MusicGridCard(s, self.cover_pixmap_cache)
            card.clicked.connect(lambda song=s, song_list=songs: self._play_from_search(song, song_list))
            card.play_clicked.connect(lambda song=s, song_list=songs: self._play_from_search(song, song_list))
            r = idx // columns
            c = idx % columns
            self.search_grid.addWidget(card, r, c)
            if s.get("thumbnail"):
                self._fetch_image_for_widget(s["videoId"], s["thumbnail"], card.img)

    def _play_from_search(self, song, song_list):
        self.queue = list(song_list)
        try:
            self.queue_index = self.queue.index(song)
        except ValueError:
            self.queue_index = 0
        self.play_song_at_index(self.queue_index)

    # ----------------------------------------------------------------------- Görsel İndirici
    def _fetch_image_for_widget(self, key, url, widget):
        if key in self.cover_pixmap_cache:
            widget.set_pixmap(self.cover_pixmap_cache[key])
            return
        w = ImageLoaderWorker(key, url)
        w.image_loaded.connect(lambda k, p, wgt=widget: self._on_image_downloaded(k, p, wgt))
        w.start()
        self.active_workers.append(w)

    def _on_image_downloaded(self, key, pixmap, widget):
        self.cover_pixmap_cache[key] = pixmap
        widget.set_pixmap(pixmap)

    # ----------------------------------------------------------------------- Oynatma & Akış
    def play_single_song(self, song):
        self.queue = [song]
        self.queue_index = 0
        self.play_song_at_index(0)

    def play_song_at_index(self, index):
        if not (0 <= index < len(self.queue)):
            return
        self.queue_index = index
        song = self.queue[index]
        self.current_song = song

        title = song.get("title", "")
        artist = song.get("artist", "")
        self.bar_title.setText(title)
        self.bar_artist.setText(artist)
        self.rp_title.setText(title)
        self.rp_artist.setText(artist)

        self.bar_play_btn.setIcon(qta.icon("fa5s.spinner", color="#000000", animation=qta.Pulse(self.bar_play_btn)))
        self.rp_play_btn.setIcon(qta.icon("fa5s.spinner", color="#000000", animation=qta.Pulse(self.rp_play_btn)))

        vid = song.get("videoId")
        thumb = song.get("thumbnail")
        if thumb:
            self._fetch_image_for_widget(vid, thumb, self.bar_cover)
            self._fetch_image_for_widget(vid, thumb, self.rp_cover)

        is_fav = self.playlist_mgr.contains(FAVORITES_NAME, vid)
        if is_fav:
            self.bar_heart_btn.setIcon(qta.icon("fa5s.heart", color="#1ED760"))
        else:
            self.bar_heart_btn.setIcon(qta.icon("fa5.heart", color="#B3B3B3"))

        self._refresh_queue_ui()
        self._load_lyrics_for_song(song)

        if self.settings.get("notifications_enabled", True) and toast:
            try:
                toast("yt-music-gui", f"{title}\n{artist}", app_id="yt-music-gui")
            except Exception:
                pass

        resolve_worker = ResolveStreamWorker(self.player, song)
        resolve_worker.resolved.connect(self._on_stream_resolved)
        resolve_worker.error_occurred.connect(lambda s, err: QMessageBox.warning(self, "Hata", err))
        resolve_worker.start()
        self.active_workers.append(resolve_worker)

    def _on_stream_resolved(self, song, stream_url, headers):
        if self.current_song and self.current_song["videoId"] != song["videoId"]:
            return
        success = self.player.play_stream(stream_url, headers)
        if success:
            self.bar_play_btn.setIcon(qta.icon("fa5s.pause", color="#000000"))
            self.rp_play_btn.setIcon(qta.icon("fa5s.pause", color="#000000"))
        else:
            self.bar_play_btn.setIcon(qta.icon("fa5s.play", color="#000000"))
            self.rp_play_btn.setIcon(qta.icon("fa5s.play", color="#000000"))
            QMessageBox.warning(self, "Hata", f"Akış başlatılamadı: {self.player.last_error}")

    def toggle_play_pause(self):
        if not self.player.available:
            return
        state = self.player.get_state()
        if state == "stopped":
            if self.queue and 0 <= self.queue_index < len(self.queue):
                self.play_song_at_index(self.queue_index)
            return
        is_paused = self.player.toggle_pause()
        icon_name = "fa5s.play" if is_paused else "fa5s.pause"
        self.bar_play_btn.setIcon(qta.icon(icon_name, color="#000000"))
        self.rp_play_btn.setIcon(qta.icon(icon_name, color="#000000"))

    def play_next(self):
        if not self.queue:
            return
        if self.repeat_mode == "one":
            self.play_song_at_index(self.queue_index)
            return
        if self.is_shuffle:
            import random
            nxt = random.randint(0, len(self.queue) - 1)
            self.play_song_at_index(nxt)
            return
        nxt = self.queue_index + 1
        if nxt < len(self.queue):
            self.play_song_at_index(nxt)
        elif self.repeat_mode == "all":
            self.play_song_at_index(0)

    def play_previous(self):
        if not self.queue:
            return
        if self.player.get_time() > 3000:
            self.player.seek_to(0)
            return
        prev = self.queue_index - 1
        if prev >= 0:
            self.play_song_at_index(prev)

    def _toggle_shuffle(self):
        self.is_shuffle = not self.is_shuffle
        color = "#1ED760" if self.is_shuffle else "#B3B3B3"
        self.bar_shuffle_btn.setIcon(qta.icon("fa5s.random", color=color))

    def _cycle_repeat(self):
        modes = ["none", "all", "one"]
        idx = (modes.index(self.repeat_mode) + 1) % len(modes)
        self.repeat_mode = modes[idx]
        if self.repeat_mode == "none":
            self.bar_repeat_btn.setIcon(qta.icon("fa5s.redo", color="#B3B3B3"))
        elif self.repeat_mode == "all":
            self.bar_repeat_btn.setIcon(qta.icon("fa5s.redo", color="#1ED760"))
        elif self.repeat_mode == "one":
            self.bar_repeat_btn.setIcon(qta.icon("fa5s.redo-alt", color="#FFA500"))

    def _toggle_current_favorite(self):
        if not self.current_song:
            return
        added = self.playlist_mgr.toggle_song(FAVORITES_NAME, self.current_song)
        if added:
            self.bar_heart_btn.setIcon(qta.icon("fa5s.heart", color="#1ED760"))
        else:
            self.bar_heart_btn.setIcon(qta.icon("fa5.heart", color="#B3B3B3"))
        self._refresh_library_list()

    def _on_volume_changed(self, val):
        self.player.set_volume(val)
        self.settings["volume"] = val
        self._save_settings()

    def _on_seek_released(self):
        length = self.player.get_length()
        if length > 0:
            slider = self.sender() or self.bar_seek_slider
            target_ms = int((slider.value() / 1000.0) * length)
            self.player.seek_to(target_ms)
        self.is_seeking = False

    # ----------------------------------------------------------------------- Zamanlayıcı (Tick)
    def _on_player_tick(self):
        self.player.tick()
        st = self.player.get_state()

        if st == "ended":
            self.play_next()
            return

        cur_ms = self.player.get_time()
        len_ms = self.player.get_length()

        if len_ms > 0:
            cur_str = format_ms(cur_ms)
            tot_str = format_ms(len_ms)
            self.bar_time_cur.setText(cur_str)
            self.bar_time_total.setText(tot_str)
            self.rp_cur_time.setText(cur_str)
            self.rp_total_time.setText(tot_str)

            if not self.is_seeking:
                ratio = max(0.0, min(1.0, cur_ms / float(len_ms)))
                val = int(ratio * 1000)
                self.bar_seek_slider.setValue(val)
                self.rp_slider.setValue(val)

        # Şarkı sözleri her zaman anlık takip edilir
        if self.current_song:
            self._update_karaoke_highlight(cur_ms)

        # Ses dalgası animasyonu
        if st == "playing":
            t = time.time() * 8
            for i, b in enumerate(self.wave_bars):
                h = int(8 + 12 * (0.5 + 0.5 * math.sin(t + i * 0.8)))
                b.setFixedHeight(h)

    # ----------------------------------------------------------------------- Şarkı Sözleri ve Renkli Senkronizasyon
    def _load_lyrics_for_song(self, song):
        vid = song["videoId"]
        self.lyrics_hero_title.setText(f"{song.get('title')} — {song.get('artist')}")
        self.karaoke_list.clear()

        if vid in self.lyrics_cache:
            self._render_lyrics(self.lyrics_cache[vid])
            return

        placeholder = QListWidgetItem("Şarkı sözleri aranıyor...")
        placeholder.setData(Qt.ItemDataRole.UserRole, None)
        placeholder.setData(Qt.ItemDataRole.UserRole + 1, "past")
        self.karaoke_list.addItem(placeholder)

        worker = LyricsWorker(song)
        worker.lyrics_ready.connect(self._on_lyrics_loaded)
        worker.start()
        self.active_workers.append(worker)

    def _on_lyrics_loaded(self, video_id, lrc_text):
        if not lrc_text:
            self.lyrics_cache[video_id] = []
            if self.current_song and self.current_song["videoId"] == video_id:
                self.karaoke_list.clear()
                item = QListWidgetItem("Bu şarkı için şarkı sözü bulunamadı.")
                item.setData(Qt.ItemDataRole.UserRole + 1, "past")
                self.karaoke_list.addItem(item)
            return

        parsed = parse_lrc(lrc_text)
        if parsed:
            self.lyrics_cache[video_id] = parsed
        else:
            lines = [(i * 2000, l) for i, l in enumerate(lrc_text.splitlines()) if l.strip()]
            self.lyrics_cache[video_id] = lines

        if self.current_song and self.current_song["videoId"] == video_id:
            self._render_lyrics(self.lyrics_cache[video_id])

    def _render_lyrics(self, lrc_list):
        self.karaoke_list.clear()
        if not lrc_list:
            item = QListWidgetItem("Şarkı sözü bulunamadı.")
            item.setData(Qt.ItemDataRole.UserRole + 1, "past")
            self.karaoke_list.addItem(item)
            return

        for ms, text in lrc_list:
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, ms)
            it.setData(Qt.ItemDataRole.UserRole + 1, "future")
            self.karaoke_list.addItem(it)

        cur_ms = self.player.get_time()
        self._update_karaoke_highlight(cur_ms)

    def _update_karaoke_highlight(self, cur_ms):
        count = self.karaoke_list.count()
        if count == 0:
            return

        active_idx = -1
        for row in range(count):
            item = self.karaoke_list.item(row)
            t = item.data(Qt.ItemDataRole.UserRole)
            if t is not None and t <= cur_ms:
                active_idx = row
            elif t is not None and t > cur_ms:
                break

        changed = False
        for row in range(count):
            it = self.karaoke_list.item(row)
            old_state = it.data(Qt.ItemDataRole.UserRole + 1)
            if active_idx != -1:
                if row < active_idx:
                    new_state = "past"
                elif row == active_idx:
                    new_state = "active"
                else:
                    new_state = "future"
            else:
                new_state = "future"

            if old_state != new_state:
                it.setData(Qt.ItemDataRole.UserRole + 1, new_state)
                changed = True

        if changed:
            self.karaoke_list.viewport().update()

        if active_idx != -1 and self.stack.currentIndex() == 3:
            active_item = self.karaoke_list.item(active_idx)
            self.karaoke_list.scrollToItem(active_item, QAbstractItemView.ScrollHint.PositionAtCenter)

    # ----------------------------------------------------------------------- Çalma Listeleri
    def _create_playlist_dialog(self):
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Yeni Liste", "Çalma listesi adı:")
        if ok and name.strip():
            name = name.strip()
            self.playlist_mgr.add_songs(name, [])
            self._refresh_library_list()
            self.open_playlist_view(name)

    def _play_current_playlist_all(self):
        if not hasattr(self, "current_playlist_name"):
            return
        songs = self.playlist_mgr.get_songs(self.current_playlist_name) or []
        if not songs:
            return
        self.queue = list(songs)
        self.queue_index = 0
        self.play_song_at_index(0)

    def _shuffle_current_playlist(self):
        import random
        if not hasattr(self, "current_playlist_name"):
            return
        songs = self.playlist_mgr.get_songs(self.current_playlist_name) or []
        if not songs:
            return
        shuffled = list(songs)
        random.shuffle(shuffled)
        self.queue = shuffled
        self.queue_index = 0
        self.play_song_at_index(0)

    def _delete_current_playlist(self):
        if not hasattr(self, "current_playlist_name"):
            return
        if self.current_playlist_name == FAVORITES_NAME:
            QMessageBox.warning(self, "Uyarı", "Beğenilen Şarkılar silinemez.")
            return
        confirm = QMessageBox.question(
            self, "Sil", f"'{self.current_playlist_name}' silinsin mi?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.playlist_mgr.delete_playlist(self.current_playlist_name)
            self._refresh_library_list()
            self.show_home_view()

    def _remove_from_current_playlist(self, song):
        if hasattr(self, "current_playlist_name"):
            self.playlist_mgr.remove_song(self.current_playlist_name, song["videoId"])
            self.open_playlist_view(self.current_playlist_name)

    def _on_playlist_table_double_click(self, row, col):
        t_item = self.playlist_songs_table.item(row, 1)
        if t_item:
            song = t_item.data(Qt.ItemDataRole.UserRole)
            songs = self.playlist_mgr.get_songs(self.current_playlist_name) or []
            self.queue = list(songs)
            try:
                self.queue_index = self.queue.index(song)
            except ValueError:
                self.queue_index = row
            self.play_song_at_index(self.queue_index)

    # ----------------------------------------------------------------------- Kısayollar
    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_Space), self, self.toggle_play_pause)
        QShortcut(QKeySequence("Ctrl+Right"), self, self.play_next)
        QShortcut(QKeySequence("Ctrl+Left"), self, self.play_previous)
        QShortcut(QKeySequence("Left"), self, lambda: self.player.seek(-5000))
        QShortcut(QKeySequence("Right"), self, lambda: self.player.seek(5000))
        QShortcut(QKeySequence("Up"), self, lambda: self.set_volume_delta(5))
        QShortcut(QKeySequence("Down"), self, lambda: self.set_volume_delta(-5))
        QShortcut(QKeySequence("Ctrl+K"), self, lambda: self.hero_banner.search_input.setFocus())
        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.hero_banner.search_input.setFocus())
        QShortcut(QKeySequence("Ctrl+L"), self, self.show_lyrics_view)

    def set_volume_delta(self, d):
        val = max(0, min(100, self.bar_vol_slider.value() + d))
        self.bar_vol_slider.setValue(val)

    def closeEvent(self, event):
        self.timer.stop()
        self.player.close()
        event.accept()


# ---------------------------------------------------------------------------
# Giriş Noktası
# ---------------------------------------------------------------------------
def main():
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("yt-music-gui")

    window = YtMusicGuiApp()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
