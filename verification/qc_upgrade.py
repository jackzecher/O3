"""Isolated, repeatable application QC. Never uses the installed workspace."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--platform', choices=['offscreen', 'windows'], default='offscreen')
    parser.add_argument('--build-root', type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.run_root.resolve()
    if out.exists():
        raise SystemExit('Choose a new run-root; evidence and state are never overwritten.')
    out.mkdir(parents=True)
    os.environ['QT_QPA_PLATFORM'] = args.platform
    sys.path.insert(0, str(args.build_root / 'O3/O3_PRODUCT/APP'))
    sys.path.insert(0, str(args.build_root / 'AI_RUNTIME'))
    from seed import seed
    from o3_gui.km_session import KMSession
    from o3_gui.logic import read_config
    from o3_gui.km_client import WorkspaceLock
    from o3_gui.app import O3Window
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    state = seed(out / 'sample')
    source = out / 'sample/O3Data'
    (source / 'Mail/Sent').mkdir()
    session = KMSession(state)
    session.open()
    session.scan(source)
    session.close()
    hashes = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in source.rglob('*') if p.is_file()}
    config = read_config(state)
    config.pop('navigation', None)
    config.setdefault('alpha3', {})['navigation_adopted'] = False
    app = QApplication([])
    app.setStyle('Fusion')
    app.setQuitOnLastWindowClosed(False)
    lock = WorkspaceLock(state)
    assert lock.tryLock(0)
    window = O3Window(state, config, lock)
    window.show()
    checks = []

    def wait(predicate, label, seconds=35):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            if predicate():
                QTest.qWait(60)
                return
            QTest.qWait(20)
        raise AssertionError('Timed out: ' + label + '; last_error=' + str(window.last_error))

    def check(name, condition, details=None):
        checks.append({'name': name, 'pass': bool(condition), 'details': details})
        print(('PASS ' if condition else 'FAIL ') + name, flush=True)
        if not condition:
            raise AssertionError(name + ': ' + str(details))

    def snapshot(name):
        app.processEvents()
        QTest.qWait(160)
        window.grab().save(str(out / (name + '.png')))

    try:
        wait(lambda: window.initialized and window.page == 'mail' and window.mail_workspace.ready, 'default mail')
        check('Default useful Mail journey without customization', window.navigation.current['view'] == 'mail:unanswered')
        check('Unanswered mail has visible results', bool(window.mail_workspace.rows))
        snapshot('01-default-mail')
        window.open_mail('all')
        wait(lambda: window.mail_workspace.ready and window.mail_workspace.task == 'all', 'all mail')
        check('All mail accessible independently', bool(window.mail_workspace.rows))
        window.open_mail('unanswered')
        wait(lambda: window.mail_workspace.ready and window.mail_workspace.task == 'unanswered', 'unanswered reload')
        listing = window.mail_workspace.listing
        first = next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(Qt.UserRole))
        listing.setCurrentItem(first)
        listing.setFocus()
        QTest.keyClick(listing, Qt.Key_Down)
        app.processEvents()
        check('Keyboard arrows keep mail list open', window.page == 'mail')
        QTest.keyClick(listing, Qt.Key_Return)
        wait(lambda: window.page == 'reader' and window.current_detail, 'keyboard opens reader')
        check('Keyboard Enter opens readable mail', bool(window.reader_text.toPlainText()))
        window.back()
        wait(lambda: window.page == 'mail' and window.mail_workspace.ready, 'mail return')
        check('Back restores mail selection', window.mail_workspace.selected_row() is not None)

        for scale in (1.0, 1.25, 1.5):
            window.apply_scale(scale, persist=False)
            for width in (1360, 1000, 860, 760):
                window.resize(width, 820)
                app.processEvents()
                QTest.qWait(100)
                controls = [b for b in (window.back_button, window.workspace_menu, window.more, window.context_button, window.search) if b.isVisible()]
                overlaps = []
                for i, a in enumerate(controls):
                    ar = a.geometry()
                    for b in controls[i + 1:]:
                        if ar.intersects(b.geometry()):
                            overlaps.append([a.accessibleName() or a.objectName(), b.accessibleName() or b.objectName()])
                check(f'D2 toolbar {width}px at {scale}', not overlaps, overlaps)
                snapshot(f'mail-{width}-{int(scale*100)}')
        window.resize(1360, 860)
        window.apply_scale(1.5, persist=False)
        window.go_home()
        wait(lambda: window.page == 'overview' and window.overview.isEnabled() and bool(window.home_data.get('loe_id')), 'project home')
        check('Project links retained information', window.mail_list.count() > 0)
        if window.mail_list.count():
            QTest.mouseClick(window.mail_list.viewport(), Qt.LeftButton, pos=window.mail_list.visualItemRect(window.mail_list.item(0)).center())
            wait(lambda: window.page == 'reader' and window.current_detail, 'compact preview activation')
            check('D3 wide enlarged-text activation is visible', window.reader.isVisible())
        detail = copy.deepcopy(window.current_detail)
        detail['title'] = 'A long project subject that remains fully available with an explicit expansion action — ' * 8
        window.current_detail = detail
        window.paint_reader(detail)
        app.processEvents()
        check('D6 long title has visible full-title action', window.title_expand.isVisible())
        snapshot('reader-long-title-150')

        window.source_failure = 'Synthetic unavailable source'
        window.preferences_error = 'Synthetic save failure'
        window.update_notices()
        window.open_mail()
        wait(lambda: window.page == 'mail' and window.mail_workspace.ready, 'mail after error')
        check('D1 source notice survives unrelated reads', window.health_notice.isVisible())
        check('D1 save notice survives unrelated reads', window.save_notice.isVisible())
        window.preferences_error = None
        window.update_notices()
        check('D1 clearing save state preserves source error', window.health_notice.isVisible() and not window.save_notice.isVisible())
        window.source_failure = None
        window.update_notices()

        window.apply_scale(1.0, persist=False)
        window.resize(1360, 860)
        for kind in ('Person', 'Document', 'Event', 'LineOfEffort'):
            window.open_collection(kind)
            wait(lambda: window.page == 'collection' and window.collection_ready, kind + ' default')
            check(kind + ' default available', window.collection_data.get('state') == 'available')
            snapshot('default-' + kind)
        for theme in ('harbor', 'warm-paper', 'sage', 'slate', 'night'):
            window.apply_theme(theme, persist=False)
            window.open_mail()
            wait(lambda: window.mail_workspace.ready and window.page == 'mail', theme + ' mail')
            snapshot('theme-' + theme)
        window.apply_theme('harbor', persist=False)
        window.open_record(next(iter(window.mail_workspace.rows)), 'Email')
        wait(lambda: window.current_detail and window.page == 'reader', 'reader before spatial')
        window.open_spatial()
        wait(lambda: window.page == 'spatial' and window.spatial.canvas.isEnabled(), 'connections')
        snapshot('connections')
        window.resize(860, 760)
        window.apply_scale(1.5, persist=False)
        snapshot('connections-compact-150')
        audit = {}
        window.km.request('system.audit', {}, lambda response: audit.update(response), owner=window)
        wait(lambda: bool(audit), 'integrity audit')
        check('Integrated knowledge audit succeeded', audit.get('ok') is True)
        (out / 'audit.json').write_text(json.dumps(audit, indent=2, default=str), encoding='utf-8')
        check('Read-only source bytes preserved', hashes == {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob('*') if p.is_file()})
    finally:
        window.source_failure = None
        window.preferences_error = None
        window.close()
        wait(lambda: window.allow_close and not window.thread.isRunning(), 'clean shutdown')
        (out / 'results.json').write_text(json.dumps({'platform': args.platform, 'build_root': str(args.build_root), 'checks': checks,
            'scope': 'Synthetic application verification, not native launcher or managed runtime qualification.'}, indent=2), encoding='utf-8')
    print('QC_FINISHED ' + str(out), flush=True)


if __name__ == '__main__':
    main()
