#!/usr/bin/env bash
# YouTube Music CLI Player — macOS & Linux Başlatıcı

set -e

# Betiğin bulunduğu dizine geç
cd "$(dirname "$0")"

# UTF-8 karakter desteğini garantiye al
export PYTHONIOENCODING=utf-8
export LANG="${LANG:-en_US.UTF-8}"

# macOS için VLC kütüphane yolunu ekle
if [[ "$OSTYPE" == "darwin"* ]]; then
    if [[ -d "/Applications/VLC.app/Contents/MacOS/lib" ]]; then
        export PYTHON_VLC_LIB_PATH="/Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib"
        export VLC_PLUGIN_PATH="/Applications/VLC.app/Contents/MacOS/plugins"
    elif [[ -d "$HOME/Applications/VLC.app/Contents/MacOS/lib" ]]; then
        export PYTHON_VLC_LIB_PATH="$HOME/Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib"
        export VLC_PLUGIN_PATH="$HOME/Applications/VLC.app/Contents/MacOS/plugins"
    fi
fi

# Sanal ortam python'u var mı kontrol et
if [[ -f "venv/bin/python3" ]]; then
    PYTHON_BIN="venv/bin/python3"
elif [[ -f "venv/bin/python" ]]; then
    PYTHON_BIN="venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif command -v python &>/dev/null; then
    PYTHON_BIN="python"
else
    echo "Hata: Python bulunamadı! Lütfen Python 3.10+ kurun." >&2
    exit 1
fi

"$PYTHON_BIN" main.py "$@"
