import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication

from app.ui.style import make_icon

app = QGuiApplication([])
out = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
out.parent.mkdir(exist_ok=True)
ok = make_icon("stopped").pixmap(256, 256).save(str(out), "ICO")
print("icon.ico:", "готово" if ok else "не удалось создать")
