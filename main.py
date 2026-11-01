import os
import sys
import tempfile


def main() -> int:
    from app import log, winutils
    log.setup()
    args = sys.argv[1:]

    if winutils.IS_WIN and not winutils.is_admin() and "--no-elevate" not in args:
        if winutils.relaunch_as_admin():
            return 0

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app.config import APP_NAME, Config
    from app.context import AppContext
    from app.ui.main_window import MainWindow
    from app.ui.style import build_qss, make_icon

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss())
    app.setWindowIcon(make_icon())
    app.setQuitOnLastWindowClosed(False)

    lock = QLockFile(os.path.join(tempfile.gettempdir(), "zapret_manager.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, APP_NAME, "Программа уже запущена (проверьте значок в трее).")
        return 0

    ctx = AppContext(Config())
    win = MainWindow(ctx, minimized="--minimized" in args)
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
