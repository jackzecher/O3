"""Optional isolated dialog capture; run with --platform windows for native QC.

Uses a disposable new KM and uniquely titled windows. Never opens user's O3
state. This is an inspection helper, not a substitute for the full app pass.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--platform',choices=('offscreen','windows'),default='offscreen')
    args=parser.parse_args();os.environ['QT_QPA_PLATFORM']=args.platform
    app_dir=Path(__file__).resolve().parents[1];sys.path.insert(0,str(app_dir))
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication,QLabel,QPushButton
    from PySide6.QtTest import QTest
    from o3_gui.km_session import KMSession
    from o3_km.service import VERSION
    from o3_gui.human_customization import HumanViewEditor
    from o3_gui.workspace_editor import SharedSettings
    from o3_gui.presentation import stylesheet_for,native_palette
    output=app_dir.parents[2]/'test-artifacts'/'customization'/(args.platform+'-150');output.mkdir(parents=True,exist_ok=True)
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion');app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(stylesheet_for(scale=1.5,theme='harbor'));app.setPalette(native_palette('harbor'))
    class Client:
        def __init__(self,session):self.session=session
        @property
        def revision(self):return self.session.km.revision()
        def cancel_owner(self,owner):pass
        def request(self,op,params,done,*,owner=None,expected=None,as_of=None):
            request={'contract':VERSION,'operation':op,'params':params}
            if expected is not None:request['expected_workspace_revision']=expected
            if as_of is not None:request['as_of']=as_of
            done(self.session.call(request))
    results=[]
    def capture(widget,name):
        widget.show();QTest.qWait(180)
        widget.grab().save(str(output/(name+'.png')))
        results.append({'name':name,'width':widget.width(),'height':widget.height(),
            'visible_text':[w.text() for w in widget.findChildren(QLabel) if w.isVisibleTo(widget)],
            'buttons':[w.text() for w in widget.findChildren(QPushButton) if w.isVisibleTo(widget)]})
    with tempfile.TemporaryDirectory(prefix='capture-',dir=output) as directory:
        session=KMSession(Path(directory)/'state',actor='test:customization-capture');session.open()
        try:
            client=Client(session);schema=session.query('builder.schema',{'record_type':'Email'})
            editor=HumanViewEditor(client,'Email',schema);editor.setWindowTitle('O3 customization QC — saved view, 150%')
            editor.name.setText('Messages about the garden');editor.add_condition({'field':'subject','operator':'contains','value':'garden'})
            for index,name in enumerate(('view-name','view-include','view-layout','view-preview')):
                if index==3:editor.preview()
                editor.editor_body.setCurrentIndex(index);capture(editor,name)
            editor.hide();editor.deleteLater();app.processEvents()
            identity=SharedSettings(client);identity.setWindowTitle('O3 customization QC — your details, 150%')
            capture(identity,'identity');identity.hide();identity.deleteLater();app.processEvents()
        finally:session.close()
    (output/'capture-results.json').write_text(json.dumps(results,indent=2),encoding='utf8')
    print(output)


if __name__=='__main__':main()
