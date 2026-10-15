"""Kalıcı veri (JSON) dosyaları için ortak yardımcılar.

- Tüm dosyalar çalışma dizinine değil, uygulamanın bulunduğu klasöre göre açılır.
- Yazma işlemleri atomiktir (geçici dosya + os.replace); yarıda kalan bir yazma
  mevcut dosyayı bozamaz.
- Okunamayan/bozuk bir dosya sessizce yok sayılmaz: yedeği alınır ve uyarı kaydedilir.
"""
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent

# Başlangıçta kullanıcıya gösterilecek uyarılar (ör. bozuk dosya yedeklendi).
startup_warnings = []


def data_path(name):
    return DATA_DIR / name


def load_json(path, default):
    """JSON dosyasını okur. Dosya yoksa `default` döner.

    Dosya bozuksa yedeğini alır, uyarı kaydeder ve `default` döner. Böylece bir
    sonraki kayıt işlemi kullanıcının verisini geri dönüşsüz şekilde silmez.
    """
    path = Path(path)
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        backup = path.with_name(f"{path.stem}.corrupt-{int(time.time())}{path.suffix}")
        try:
            shutil.copy2(path, backup)
            backup_info = f"Yedek: {backup.name}"
        except OSError:
            backup_info = "Yedek alınamadı"
        msg = f"{path.name} okunamadı ({e.__class__.__name__}). {backup_info}"
        logger.error(msg, exc_info=True)
        startup_warnings.append(msg)
        return default


def save_json_atomic(path, data, retries=5):
    """JSON verisini atomik olarak yazar. Hata durumunda OSError fırlatır."""
    path = Path(path)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        # OneDrive/antivirüs dosyayı kısa süreliğine kilitleyebilir; birkaç kez dene.
        for attempt in range(retries):
            try:
                os.replace(tmp_name, path)
                return
            except PermissionError:
                if attempt == retries - 1:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
