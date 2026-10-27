"""Native appearance review using isolated fictional data and fresh evidence."""
from pathlib import Path
import argparse
import json
import os
import sys
import time
from copy import deepcopy
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run-root',type=Path,required=True)
    parser.add_argument('--platform',choices=['windows','offscreen'],default='windows');args=parser.parse_args()
    out=args.run_root.resolve()
    if out.exists() or not out.is_relative_to(ROOT):raise SystemExit('Choose a new directory inside this checkout.')
    out.mkdir(parents=True);os.environ['QT_QPA_PLATFORM']=args.platform
    for path in (ROOT,ROOT/'O3/O3_PRODUCT/APP',ROOT/'AI_RUNTIME'):sys.path.insert(0,str(path))
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAccessible,QFont,QFontMetrics,QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QWidget,QDialog,QAbstractButton,QComboBox,QLineEdit,QLabel,QScrollArea
    from review_examples import create_example
    from o3_gui.app import O3Window
    from o3_gui.appearance import THEMES,DEFAULTS,appearance_from_config
    from o3_gui.appearance_editor import ThemeGallery
    from o3_gui.km_client import WorkspaceLock
    from o3_gui.logic import read_config
    from o3_gui.panels import SettingsPanel
    from o3_gui.startup import WelcomeScreen,ReviewStartup
    app=QApplication([]);app.setStyle('Fusion');app.setQuitOnLastWindowClosed(False)
    checks=[];errors=[];windows=[];dialogs=[]
    def check(name,ok,details=None):
        checks.append({'name':name,'pass':bool(ok),'details':details});print(('PASS ' if ok else 'FAIL ')+name,flush=True)
    def wait(condition,label):
        stop=time.monotonic()+40
        while time.monotonic()<stop:
            app.processEvents()
            if condition():QTest.qWait(50);return
            QTest.qWait(20)
        raise AssertionError('Timed out: '+label)
    def capture(widget,name):
        app.processEvents();QTest.qWait(100);widget.grab().save(str(out/(name+'.png')))
    def names(widget):
        accessible=QAccessible.queryAccessibleInterface(widget)
        return accessible.text(QAccessible.Name) if accessible else widget.accessibleName()
    def audit(dialog,label):
        app.processEvents();QTest.qWait(70)
        controls=[w for w in dialog.findChildren(QWidget) if isinstance(w,(QAbstractButton,QComboBox,QLineEdit)) and w.isVisible() and not w.visibleRegion().isEmpty()]
        unnamed=[type(w).__name__ for w in controls if not names(w)]
        check(label+' accessible control names',not unnamed,unnamed)
        overlap=[]
        for i,a in enumerate(controls):
            for b in controls[i+1:]:
                if a.parentWidget() is b.parentWidget() and a.geometry().intersects(b.geometry()):overlap.append([names(a),names(b)])
        check(label+' controls do not overlap',not overlap,overlap)
        cut=[]
        for w in controls:
            if isinstance(w,QAbstractButton) and w.text() and w.fontMetrics().horizontalAdvance(w.text())>w.width()-8:cut.append(w.text())
        for w in dialog.findChildren(QLabel):
            if w.isVisible() and not w.visibleRegion().isEmpty() and w.wordWrap() and w.heightForWidth(w.width())>w.height()+2:cut.append(w.text()[:100])
        check(label+' labels fit',not cut,cut)
        footer=[b for b in controls if isinstance(b,QAbstractButton) and b.text() in ('Save appearance','Cancel appearance')]
        check(label+' Save and Cancel fully reachable',len(footer)==2 and all(w.visibleRegion().boundingRect().contains(w.rect().adjusted(1,1,-1,-1)) for w in footer))
        check(label+' fits the available screen',dialog.width()<=dialog.screen().availableGeometry().width() and dialog.height()<=dialog.screen().availableGeometry().height(),[dialog.width(),dialog.height()])
    def close(window):
        window.preferences_error=None;window.close();wait(lambda:window.allow_close and not window.thread.isRunning(),'worker shutdown')
    try:
        state=create_example(out/'example');lock=WorkspaceLock(state);assert lock.tryLock(0)
        welcome=WelcomeScreen(DEFAULTS);dialogs.append(welcome);welcome.show();capture(welcome,'welcome-light')
        w=O3Window(state,read_config(state),lock);windows.append(w);startup=ReviewStartup(w,welcome)
        wait(lambda:w.initialized and w.page=='mail' and w.mail_workspace.ready,'initialization')
        check('Welcome hands off on real workspace readiness',startup.finished and startup.succeeded and not welcome.isVisible() and w.isVisible())
        w.resize(1360,860);capture(w,'mail-harbor')
        for mode in ('light','dark'):
            gallery=ThemeGallery();dialogs.append(gallery);gallery.resize(950,380);gallery.filter(mode);gallery.show();app.processEvents();gallery.adjustSize();gallery.resize(950,gallery.sizeHint().height())
            capture(gallery,'palettes-'+mode)
            check(mode+' gallery has twelve distinct choices',sum(not c.isHidden() for c in gallery.cards.values())==12)
            gallery.hide()
        panel=SettingsPanel(w);dialogs.append(panel);panel.show();editor=panel.appearance_editor
        capture(panel,'appearance-light');audit(panel,'Settings 100%')
        editor.filter.setCurrentIndex(editor.filter.findData('dark'))
        card=editor.gallery.cards['deep-ocean'];card.setFocus(Qt.TabFocusReason);QTest.keyClick(card,Qt.Key_Space)
        check('Theme can be selected with the keyboard',editor.get_value()['theme']=='deep-ocean')
        capture(panel,'appearance-dark')
        for scale in (1.0,1.5):
            editor.set_value({**DEFAULTS,'text_scale':scale});panel.resize(760,680);app.processEvents();audit(panel,'Compact Settings '+str(scale))
            check('Compact Settings retains requested width '+str(scale),panel.width()<=760,[panel.width(),panel.height()])
            check('Compact Settings exposes every section '+str(scale),panel.section_choice.isVisible() and panel.section_choice.count()==5)
        panel.resize(1080,850)
        before=deepcopy(read_config(state));editor.accent='#ffeeaa';editor.emit_change()
        check('Preview has not changed saved appearance',appearance_from_config(read_config(state))==appearance_from_config(before))
        for font in ('default','open','soft'):
            editor.set_value({**DEFAULTS,'theme':'night','text_scale':1.5,'font':font,'density':'comfortable'})
            panel.resize(960,780);app.processEvents()
            for index,label in enumerate(('Themes','Colors','Text','Layout','My looks')):
                editor.tabs.setCurrentIndex(index);audit(panel,label+' 150% '+font)
                scroll=editor.tabs.currentWidget();scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum());audit(panel,label+' bottom 150% '+font)
            if font=='default':editor.tabs.setCurrentIndex(2);capture(panel,'reading-controls-150')
        editor.set_value({**DEFAULTS,'theme':'forest','reader_font':'book','line_spacing':1.7,'reading_width':'narrow','density':'comfortable','navigation':'focus'})
        editor.tabs.setCurrentIndex(4);editor.look_name.setText('Evening reading');editor.add_look()
        with patch('o3_gui.app.save_config',side_effect=OSError('Synthetic appearance save failure')):panel.save_appearance()
        check('Failed save retains preview and library without writing',panel.appearance_save_failed and editor.looks and appearance_from_config(read_config(state))==appearance_from_config(before))
        capture(panel,'saved-looks');panel.save_appearance()
        check('Retry saves the complete appearance and look',read_config(state)['alpha3']['saved_looks'][0]['name']=='Evening reading' and appearance_from_config(read_config(state))['theme']=='forest')
        panel=SettingsPanel(w);dialogs.append(panel);panel.appearance_editor.set_value({**DEFAULTS,'theme':'plum'});panel.reject()
        check('Cancel returns to the saved look',w.appearance['theme']=='forest' and w.preview_theme is None)
        check('Quiet layout keeps navigation reachable',not w.sidebar.isVisible() and w.workspace_menu.isVisible())
        item=w.mail_workspace.listing.item(0);w.mail_workspace.open_item(item)
        wait(lambda:w.page=='reader' and w.current_detail,'reader')
        capture(w,'reading-forest');check('Reading width is applied',w.reading.width()<=640)
        selection=w.reader_text.textCursor();selection.setPosition(2);selection.setPosition(12,QTextCursor.MoveMode.KeepAnchor);w.reader_text.setTextCursor(selection)
        panel=SettingsPanel(w);dialogs.append(panel);panel.show();panel.appearance_editor.set_value({**w.appearance,'theme':'aubergine','reader_scale':1.25})
        check('Appearance preview preserves reading selection',w.reader_text.textCursor().anchor()==2 and w.reader_text.textCursor().position()==12)
        panel.reject();saved=appearance_from_config(read_config(state));close(w)
        lock2=WorkspaceLock(state);assert lock2.tryLock(0)
        reopened=O3Window(state,read_config(state),lock2);windows.append(reopened);reopened.show();wait(lambda:reopened.initialized,'reopen')
        check('Appearance survives reopening',reopened.appearance==saved)
        dark_welcome=WelcomeScreen(saved,preview=True);dialogs.append(dark_welcome);dark_welcome.show();capture(dark_welcome,'welcome-dark');dark_welcome.accept()
        close(reopened)
    except Exception as error:
        import traceback
        errors.append(str(error));traceback.print_exc()
    finally:
        for dialog in dialogs:
            try:dialog.close()
            except RuntimeError:pass
        for window in windows:
            if window.thread.isRunning():
                try:close(window)
                except Exception as error:errors.append('Shutdown: '+str(error))
        (out/'results.json').write_text(json.dumps({'platform':args.platform,'checks':checks,'errors':errors},indent=2),encoding='utf-8')
    return 1 if errors or any(not c['pass'] for c in checks) else 0


if __name__=='__main__':raise SystemExit(main())
