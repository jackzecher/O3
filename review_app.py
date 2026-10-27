"""Explicit development review entry point; does not change managed launch policy."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Open the O3 upgrade review with isolated local sample data.')
    parser.add_argument('--example', action='store_true', help='Create or reopen the isolated synthetic review workspace.')
    parser.add_argument('--workspace', type=Path, help='Explicit development workspace. Never inferred from installed O3.')
    parser.add_argument('--no-splash', action='store_true', help='Open the review directly without the welcome screen.')
    args = parser.parse_args()
    if not args.example and args.workspace is None:
        parser.error('Choose --example or an explicit --workspace.')
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / 'O3/O3_PRODUCT/APP'))
    sys.path.insert(0, str(ROOT / 'AI_RUNTIME'))
    if args.example:
        base = ROOT / 'review-workspace/example-upgrade1'
        state = base / 'Workspace'
        if not state.exists():
            from review_examples import create_example
            state = create_example(base)
    else:
        state = args.workspace.resolve()
        state.mkdir(parents=True, exist_ok=True)
    from PySide6.QtWidgets import QApplication, QMessageBox
    from o3_gui.app import O3Window
    from o3_gui.logic import read_config
    from o3_gui.km_client import WorkspaceLock
    from o3_gui.appearance import appearance_from_config
    from o3_gui.presentation import application_icon
    from o3_gui.startup import WelcomeScreen, ReviewStartup
    if sys.platform == 'win32':
        # Give the review its own taskbar identity instead of grouping it with Python.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('O3.UpgradeReview')
    app = QApplication([])
    app.setStyle('Fusion')
    app.setWindowIcon(application_icon())
    lock = WorkspaceLock(state)
    if not lock.tryLock(0):
        QMessageBox.information(None, 'O3 is already open', 'This review workspace is open in another O3 window.')
        return 1
    splash = None
    try:
        config = read_config(state)
        appearance = appearance_from_config(config)
        if appearance['show_splash'] and not args.no_splash:
            splash = WelcomeScreen(appearance);splash.show();app.processEvents()
        window = O3Window(state, config, lock)
    except Exception as error:
        if splash:splash.accept()
        lock.unlock()
        message=QMessageBox();message.setWindowTitle('O3 could not open this workspace')
        message.setText('Your workspace could not be opened. Close this message and try again, or use a different review workspace.')
        message.setDetailedText(str(error));message.setIcon(QMessageBox.Critical);message.exec()
        return 1
    window.setWindowTitle('O3 · Upgrade review')
    if splash:window._review_startup=ReviewStartup(window,splash)
    else:window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
