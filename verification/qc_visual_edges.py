"""Independent UI boundary checks. Fresh state and output; no installed workspace."""
from __future__ import annotations
import argparse, copy, json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--platform', choices=('offscreen', 'windows'), default='offscreen')
    parser.add_argument('--run-root', type=Path, required=True)
    args = parser.parse_args()
    out = args.run_root.resolve()
    if out.exists(): raise SystemExit('A new run-root is required; existing evidence is never overwritten.')
    if not out.is_relative_to(ROOT): raise SystemExit('run-root must stay inside the isolated implementation.')
    out.mkdir(parents=True)
    os.environ['QT_QPA_PLATFORM'] = args.platform
    sys.path.insert(0, str(ROOT / 'O3/O3_PRODUCT/APP'))
    sys.path.insert(0, str(ROOT / 'AI_RUNTIME'))
    from PySide6.QtCore import Qt, QRect, QPoint
    from PySide6.QtGui import QFont, QFontMetrics, QFontDatabase, QAccessible
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (QApplication, QDialog, QTextBrowser, QListWidget, QListWidgetItem,
                                  QStyleOptionViewItem, QAbstractButton, QComboBox, QLineEdit, QWidget, QLabel)
    from seed import seed
    from o3_gui.km_session import KMSession
    from o3_gui.logic import read_config
    from o3_gui.km_client import WorkspaceLock
    from o3_gui.app import O3Window
    from o3_gui.panels import SettingsPanel
    from o3_gui.human_customization import HumanViewEditor
    from o3_gui.ui import RecordDelegate
    app = QApplication([]); app.setStyle('Fusion'); app.setQuitOnLastWindowClosed(False)
    font_ids = []
    if args.platform == 'offscreen' and os.name == 'nt':
        for name in ('segoeui.ttf', 'seguisb.ttf'):
            path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
            if path.is_file(): font_ids.append(QFontDatabase.addApplicationFont(str(path)))
    checks, errors, windows = [], [], []
    def check(name, ok, details=None):
        checks.append({'name': name, 'pass': bool(ok), 'details': details})
        print(('PASS ' if ok else 'FAIL ') + name, flush=True)
    def wait(predicate, label, seconds=35):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            if predicate(): QTest.qWait(80); return
            QTest.qWait(20)
        raise AssertionError('Timed out: ' + label)
    def capture(widget, name):
        app.processEvents(); QTest.qWait(180); widget.grab().save(str(out / (name + '.png')))
    def opened(state, config):
        state.mkdir(parents=True, exist_ok=True)
        lock = WorkspaceLock(state); assert lock.tryLock(0)
        window = O3Window(state, config, lock); windows.append(window)
        window.resize(860, 760); window.show()
        wait(lambda: window.initialized and window.page == 'mail' and window.mail_workspace.ready, 'mail initialization')
        return window
    def close(window):
        for dialog in window.findChildren(QDialog): dialog.reject()
        window.preferences_error = None; window.source_failure = None; window.close()
        wait(lambda: window.allow_close and not window.thread.isRunning(), 'window shutdown')
    def names(widget):
        interface = QAccessible.queryAccessibleInterface(widget)
        return interface.text(QAccessible.Name) if interface else widget.accessibleName()
    def audit_dialog(dialog, label):
        app.processEvents(); QTest.qWait(100)
        controls = [x for x in dialog.findChildren(QWidget)
                    if isinstance(x, (QAbstractButton, QComboBox, QLineEdit))
                    and x.isVisible() and not x.visibleRegion().isEmpty()]
        overlaps = []
        for i, first in enumerate(controls):
            for second in controls[i + 1:]:
                if first.parentWidget() is second.parentWidget() and first.geometry().intersects(second.geometry()):
                    overlaps.append([names(first) or first.objectName(), names(second) or second.objectName()])
        check(label + ' controls do not overlap', not overlaps, overlaps)
        unnamed = [type(x).__name__ + ':' + (x.objectName() or str(x.geometry())) for x in controls if not names(x)]
        check(label + ' interactive controls have accessible names', not unnamed, unnamed)
        clipped = []
        for control in controls:
            if isinstance(control, QAbstractButton) and control.text() and not control.findChildren(QLineEdit):
                text_width = control.fontMetrics().horizontalAdvance(control.text())
                if text_width > control.width() - 8: clipped.append(control.text())
        check(label + ' button labels fit', not clipped, clipped)
        cut_labels = [{'text':x.text()[:100], 'required':x.heightForWidth(x.width()), 'actual':x.height()}
                      for x in dialog.findChildren(QLabel) if x.isVisible() and x.wordWrap() and x.text()
                      and not x.visibleRegion().isEmpty() and x.heightForWidth(x.width()) > x.height() + 2]
        check(label + ' wrapped descriptions fit', not cut_labels, cut_labels)

    try:
        # No seed(), project creation, scan, or synthesized reconciliation status.
        fresh_state = out / 'fresh-workspace'
        fresh = opened(fresh_state, {'paused': True, 'alpha3': {'text_scale': 1.5}})
        check('True fresh workspace opens without project reconciliation', fresh.initialized and not fresh.last_error,
              {'project_reconciliation': fresh.summary_data.get('project_reconciliation'), 'error': fresh.last_error})
        fresh.resize(760, 700); fresh.apply_scale(1.5, persist=False); app.processEvents()
        choose = next((x for x in fresh.mail_workspace.findChildren(QAbstractButton) if x.text() == 'Choose mail folder'), None)
        visible = bool(choose and choose.isVisible() and choose.isEnabled()
                       and choose.visibleRegion().boundingRect().contains(choose.rect().adjusted(1,1,-1,-1)))
        if choose: choose.setFocus(Qt.TabFocusReason); app.processEvents()
        check('D5 source setup action visible and keyboard reachable at compact 150%', visible and choose.hasFocus() if choose else False,
              {'button': choose.geometry().getRect() if choose else None,
               'visible_rect':choose.visibleRegion().boundingRect().getRect() if choose else None})
        capture(fresh, 'fresh-no-source-compact-150'); close(fresh)

        state = seed(out / 'sample')
        source = out / 'sample/O3Data'; (source / 'Mail/Sent').mkdir()
        session = KMSession(state); session.open(); session.scan(source); session.close()
        config = read_config(state); config.pop('navigation', None)
        config.setdefault('alpha3', {}).update(text_scale=1.5, navigation_adopted=False)
        window = opened(state, config); window.resize(860, 760); window.apply_scale(1.5, persist=False)
        item_id = next(iter(window.mail_workspace.rows))
        window.open_record(item_id, 'Email')
        wait(lambda: window.page == 'reader' and window.current_detail, 'reader')
        detail = copy.deepcopy(window.current_detail)
        detail['title'] = 'Planning for a long and carefully described set of next steps — ' * 10
        window.current_detail = detail; window.paint_reader(detail); app.processEvents()
        dialogs = []
        original_run_dialog = window.run_dialog
        def collect(dialog):
            dialogs.append(dialog); dialog.show(); app.processEvents(); return QDialog.Rejected
        window.run_dialog = collect
        window.title_expand.setFocus(Qt.TabFocusReason)
        QTest.keyClick(window.title_expand, Qt.Key_Space)
        wait(lambda: bool(dialogs), 'keyboard full-title action')
        full = dialogs.pop()
        readers = full.findChildren(QTextBrowser)
        check('D6 keyboard opens complete selectable title', any(reader.toPlainText() == detail['title'] for reader in readers))
        check('D6 full-title reader has accessible name', any(names(reader) == 'Full title' for reader in readers))
        capture(full, 'full-title-keyboard-150'); full.reject()
        window.run_dialog = original_run_dialog
        window.current_detail = detail
        window.open_spatial()
        wait(lambda: window.page == 'spatial' and window.spatial.canvas.isEnabled(), 'connections')
        window.spatial.center_on_seed(); app.processEvents(); QTest.qWait(160); window.spatial.canvas.arrange()
        spatial = window.spatial; viewport = spatial.scroll.viewport().rect()
        focal = spatial.nodes[spatial.seed]
        neighbors = [b for key, b in spatial.nodes.items() if key != spatial.seed]
        check('Connections focal visible at compact 150%', viewport.contains(focal.geometry()), {'focal':focal.geometry().getRect(),'viewport':viewport.getRect()})
        check('Connections first neighbor visible at compact 150%', bool(neighbors) and viewport.contains(neighbors[0].geometry()), {'first':neighbors[0].geometry().getRect() if neighbors else None,'viewport':viewport.getRect()})
        check('Connections no horizontal panning required', spatial.scroll.horizontalScrollBar().maximum() == 0)
        check('Connections cards and edges have accessible names', all(names(x) for x in list(spatial.nodes.values()) + spatial.edge_buttons))
        capture(window, 'connections-compact-150')
        spatial.set_mode('list'); app.processEvents(); capture(window, 'connections-list-150')
        window.open_mail()
        wait(lambda: window.page == 'mail' and window.mail_workspace.ready, 'mail for dialogs')

        settings = SettingsPanel(window); settings.show(); app.processEvents()
        audit_dialog(settings, 'Settings 150%'); capture(settings, 'settings-150'); settings.reject()
        window.run_dialog = collect; window.mail_workspace.customize()
        personal = dialogs.pop(); audit_dialog(personal, 'Mail Personalize 150%')
        capture(personal, 'mail-personalize-150'); personal.reject(); window.run_dialog = original_run_dialog
        schema = {}
        window.km.request('builder.schema', {'record_type':'Email'}, lambda reply: schema.update(reply), owner=window)
        wait(lambda: bool(schema), 'view editor schema')
        if not schema.get('ok'): raise AssertionError('Builder schema unavailable: ' + str(schema))
        editor = HumanViewEditor(window.km, 'Email', schema['result'], parent=window)
        editor.show(); app.processEvents(); audit_dialog(editor, 'Saved-view editor 150%')
        capture(editor, 'human-view-editor-150'); editor.reject(); window.km.cancel_owner(editor)

        # All months use real font measurements, including the original May repro.
        dates = QListWidget(); dates.setWindowTitle('Date measurement fixture'); dates.resize(760, 700)
        dates.setStyleSheet('QListWidget { background: #ffffff; }')  # Opaque standalone capture surface.
        delegate = RecordDelegate(dates); dates.setItemDelegate(delegate)
        font = QFont('Segoe UI'); font.setPixelSize(23); dates.setFont(font); dates.show(); app.processEvents()
        month_checks = []
        for month in ('January','February','March','April','May','June','July','August','September','October','November','December'):
            record = {'title':'A readable title beside a complete date', 'kind':'Mail', 'person':'Morgan',
                      'capture_label':month + ' 28, 2026 · 18:42', 'reason':'No reply from you was found in the saved mail.'}
            item = QListWidgetItem(dates); item.setData(Qt.UserRole+1, record)
            item.setData(Qt.AccessibleTextRole, record['title'] + '. ' + record['capture_label'])
            for width in (280, 420, 760):
                option = QStyleOptionViewItem(); option.font=font; option.rect=QRect(0,0,width,200)
                layout = delegate.layout_for(option, record, width)
                measured = QFontMetrics(layout['small']).horizontalAdvance(record['capture_label'])
                wrapped_height = QFontMetrics(layout['small']).boundingRect(0,0,layout['width'],9999,Qt.TextWordWrap,record['capture_label']).height()
                month_checks.append({'month':month,'width':width,'measured':measured,'allocated':layout['date_width'],
                                     'reflow':layout['separate_date'],'available':layout['width'],'lines':layout['date_lines'],
                                     'pass':layout['date_width'] >= measured and (layout['width'] >= measured or layout['date_lines'] * QFontMetrics(layout['small']).height() >= wrapped_height)})
        check('D7 all long month dates measured and fully allocated', all(row['pass'] for row in month_checks), month_checks)
        capture(dates, 'date-months-150'); dates.close()
        close(window)
    except Exception as exc:
        errors.append(str(exc)); print('ERROR ' + str(exc), flush=True)
    finally:
        for window in windows:
            if window.thread.isRunning():
                try: close(window)
                except Exception as exc: errors.append('Shutdown: ' + str(exc))
        (out / 'results.json').write_text(json.dumps({'platform':args.platform, 'font_registration':font_ids,
            'checks':checks,'errors':errors,'qualification':'Isolated development application UI, not O3.exe or managed runtime.'}, indent=2), encoding='utf-8')
    print('VISUAL_EDGE_QC_FINISHED ' + str(out), flush=True)
    return 1 if errors or any(not check['pass'] for check in checks) else 0


if __name__ == '__main__': raise SystemExit(main())

