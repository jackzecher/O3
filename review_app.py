"""Explicit development review entry point; does not change managed launch policy."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description='Open the O3 upgrade review with isolated local sample data.')
    parser.add_argument('--example', action='store_true', help='Create or reopen the isolated synthetic review workspace.')
    parser.add_argument('--workspace', type=Path, help='Explicit development workspace. Never inferred from installed O3.')
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
    app = QApplication([])
    app.setStyle('Fusion')
    lock = WorkspaceLock(state)
    if not lock.tryLock(0):
        QMessageBox.information(None, 'O3 is already open', 'This review workspace is open in another O3 window.')
        return 1
    window = O3Window(state, read_config(state), lock)
    window.setWindowTitle('O3 · Upgrade review')
    window.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
