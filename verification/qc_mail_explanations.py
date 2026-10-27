"""Check quiet mail rows, on-demand explanation, and the optional detailed setting."""
from pathlib import Path
import argparse, json, os, sys, time
ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-root',type=Path,required=True);args=parser.parse_args()
    out=args.run_root.resolve()
    if out.exists() or not out.is_relative_to(ROOT):raise SystemExit('Choose a fresh directory inside the checkout.')
    out.mkdir(parents=True);os.environ['QT_QPA_PLATFORM']='windows'
    for path in (ROOT,ROOT/'O3/O3_PRODUCT/APP',ROOT/'AI_RUNTIME'):sys.path.insert(0,str(path))
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QStyleOptionViewItem,QAbstractButton
    from review_examples import create_example
    from o3_gui.app import O3Window
    from o3_gui.logic import read_config
    from o3_gui.km_client import WorkspaceLock
    from o3_gui.panels import SettingsPanel
    app=QApplication([]);app.setStyle('Fusion');app.setQuitOnLastWindowClosed(False)
    checks=[];errors=[];w=None;panel=None
    def check(name,ok):checks.append({'name':name,'pass':bool(ok)})
    def wait(predicate):
        until=time.monotonic()+35
        while time.monotonic()<until:
            app.processEvents()
            if predicate():QTest.qWait(60);return
            QTest.qWait(20)
        raise AssertionError('Timed out waiting for the test workspace.')
    def capture(widget,name):app.processEvents();widget.grab().save(str(out/(name+'.png')))
    try:
        state=create_example(out/'example');lock=WorkspaceLock(state);assert lock.tryLock(0)
        w=O3Window(state,read_config(state),lock);w.resize(1360,860);w.show()
        wait(lambda:w.initialized and w.page=='mail' and w.mail_workspace.ready)
        mail=w.mail_workspace;delegate=mail.listing.itemDelegate()
        ordinary=[mail.listing.item(i) for i in range(mail.listing.count()) if mail.listing.item(i).data(Qt.UserRole) and not mail.listing.item(i).data(Qt.UserRole+1).get('inline_notice')]
        check('Ordinary rows have no repeated explanatory line',bool(ordinary) and all(delegate.reason(item.data(Qt.UserRole+1))=='' for item in ordinary))
        capture(w,'quiet-mail')
        first=ordinary[0];mail.listing.setCurrentItem(first)
        check('Selected mail keeps the explanation action available',mail.why_button.isEnabled())
        reason=mail.rows[first.data(Qt.UserRole)]['reason']
        def inspect_explanation():
            dialog=app.activeModalWidget()
            check('Explanation opens with the full reason',bool(dialog and reason in dialog.text()))
            if dialog:capture(dialog,'on-demand-explanation');dialog.accept()
        QTimer.singleShot(100,inspect_explanation);mail.why_button.click()
        check('Full explanation remains available to assistive technology',reason in first.data(Qt.AccessibleDescriptionRole))
        panel=SettingsPanel(w);panel.show();editor=panel.appearance_editor;editor.tabs.setCurrentIndex(3)
        editor.set_value({**editor.get_value(),'text_scale':1.5});panel.resize(760,700);app.processEvents()
        editor.tabs.currentWidget().ensureWidgetVisible(editor.show_explanations);app.processEvents()
        control=editor.show_explanations
        check('Explanation setting fits at 150% text in compact Settings',control.visibleRegion().boundingRect().contains(control.rect().adjusted(1,1,-1,-1)))
        check('Compact Settings keeps Save accessible',all(b.visibleRegion().boundingRect().contains(b.rect().adjusted(1,1,-1,-1)) for b in panel.findChildren(QAbstractButton) if b.text()=='Save appearance'))
        capture(panel,'explanation-setting')
        QTest.mouseClick(control,Qt.LeftButton)
        check('Opting in shows the full inline reason',reason in delegate.reason(first.data(Qt.UserRole+1)))
        panel.reject();panel=None
        check('Cancel restores quiet rows',delegate.reason(first.data(Qt.UserRole+1))=='')
        panel=SettingsPanel(w);panel.appearance_editor.show_explanations.setChecked(True);panel.save_appearance();panel=None
        check('Saving remembers the detailed preference',read_config(state)['alpha3']['appearance']['show_mail_explanations'] is True)
        panel=SettingsPanel(w);check('Reopening Settings restores the saved choice',panel.appearance_editor.show_explanations.isChecked());panel.reject();panel=None
    except Exception as error:
        import traceback
        traceback.print_exc();errors.append(str(error))
    finally:
        if panel:panel.reject()
        if w:
            w.preferences_error=None;w.close();wait(lambda:w.allow_close and not w.thread.isRunning())
        result={'checks':checks,'errors':errors,'platform':'windows'};(out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({'checks':len(checks),'failed':[c for c in checks if not c['pass']],'errors':errors}),flush=True)
    return 1 if errors or any(not c['pass'] for c in checks) else 0


if __name__=='__main__':raise SystemExit(main())
