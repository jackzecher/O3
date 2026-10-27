"""Independent offscreen mail integration regressions with isolated synthetic state.

This instantiates O3Window directly, not the protected launcher/normal run entry.
Assertions cover behavior, not offscreen font or visual quality.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QCheckBox, QLineEdit, QLabel, QTreeWidgetItemIterator
from o3_gui.app import O3Window
from o3_gui.km_client import WorkspaceLock
from o3_gui.km_session import KMSession
from o3_gui.logic import read_config, save_config

SELF='alex@example.test'
ROOT=Path(__file__).resolve().parents[4]/'test-artifacts'/'mail-integration'
APP=None


class MailIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global APP
        ROOT.mkdir(parents=True,exist_ok=True)
        cls.temporary=tempfile.TemporaryDirectory(prefix='run-',dir=ROOT)
        cls.addClassCleanup(cls.cleanup_workspace)
        cls.root=Path(cls.temporary.name)
        assert cls.root.resolve().is_relative_to(ROOT.resolve())
        cls.source=cls.root/'source';cls.state=cls.root/'state'
        for directory in ('Mail/Inbox','Mail/Sent','Contacts/Profiles','Calendars','Documents'):
            (cls.source/directory).mkdir(parents=True)
        def mail(key,conversation=None,cc_only=False):
            value={'schema_version':'em-raw-v1','mailbox_id':SELF,'message_id':key,
                'internet_message_id':'<'+key+'@example.test>','conversation_id':conversation or key,
                'subject':'Test mail '+key,'source_folder':'Inbox','from':{'name':'Sam','address':'sam@example.test'},
                'to':[{'address':'jo@example.test' if cc_only else SELF}],
                'cc':[{'address':SELF}] if cc_only else [],'received_at_utc':'2026-10-27T12:00:00Z',
                'captured_at_utc':'2026-10-27T14:00:00Z','body_html':'<p>Readable synthetic mail '+key+'.</p>'}
            (cls.source/'Mail/Inbox'/(key+'.json')).write_text(json.dumps(value),encoding='utf8')
        for index in range(125):mail('item-'+str(index).zfill(3))
        mail('branch-a','multi-message');mail('branch-b','multi-message');mail('branch-c','multi-message')
        mail('copied-only',cc_only=True)
        session=KMSession(cls.state,actor='test:mail-ui')
        try:
            session.open();session.query('configuration.save',{'self_addresses':[SELF]},expected_workspace_revision=session.km.revision())
            result=session.scan(cls.source)
            if result['errors']:raise AssertionError(result['errors'])
            save_config(cls.state,{'source_root':str(cls.source),'paused':True})
        finally:session.close()
        APP=QApplication.instance() or QApplication([]);APP.setQuitOnLastWindowClosed(False)
        cls.lock=WorkspaceLock(cls.state)
        if not cls.lock.tryLock(0):raise AssertionError('Synthetic workspace lock unavailable')
        cls.window=O3Window(cls.state,read_config(cls.state),cls.lock);cls.window.show()
        cls.wait_for(lambda:cls.window.initialized and cls.window.mail_workspace.ready,'initial mail')

    @classmethod
    def wait_for(cls,predicate,label,seconds=15):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            APP.processEvents()
            if predicate():
                QTest.qWait(40);return
            QTest.qWait(15)
        raise AssertionError('Timed out: '+label+'; last_error='+str(cls.window.last_error))

    @classmethod
    def cleanup_workspace(cls):
        window=getattr(cls,'window',None)
        if window:
            # Also cleanly stop the synthetic worker if startup itself failed.
            window.tick.stop();window.preference_timer.stop();window.search_timer.stop();window.startup_timer.stop()
            window.closing=True;window.shutdown.emit()
            cls.wait_for(lambda:not window.thread.isRunning(),'worker shutdown')
            window.allow_close=True;window.close();window.deleteLater();APP.processEvents()
        cls.temporary.cleanup()

    def setUp(self):
        self.wait_for(lambda:not self.window.km.pending,'pending requests drained')
        self.window.open_mail('all')
        self.wait_for(lambda:self.window.page=='mail' and self.window.mail_workspace.ready and self.window.mail_workspace.task=='all','all mail')

    def backend_query(self,**params):
        received=[]
        self.window.km.request('mail.tasks.query',params,received.append,owner=self.window)
        self.wait_for(lambda:bool(received),'mail query response')
        self.assertTrue(received[0]['ok'],received[0]);return received[0]

    def button(self,parent,label):
        return next(b for b in parent.findChildren(QPushButton) if b.text()==label)

    def test_page_two_reader_back_preserves_item_and_page(self):
        mail=self.window.mail_workspace
        self.assertGreater(mail.payload['total_count'],100)
        mail.page_next();self.wait_for(lambda:mail.ready and len(mail.previous)==1,'second mail page')
        before=set(mail.rows);item=next(mail.listing.item(i) for i in range(mail.listing.count()) if mail.listing.item(i).data(Qt.UserRole))
        rid=item.data(Qt.UserRole);mail.listing.setCurrentItem(item)
        mail.open_item(item)
        self.wait_for(lambda:self.window.page=='reader' and self.window.current_detail and self.window.current_detail['id']==rid,'reader')
        self.window.back();self.wait_for(lambda:self.window.page=='mail' and mail.ready,'return to page two')
        self.assertEqual(len(mail.previous),1)
        self.assertEqual(set(mail.rows),before)
        self.assertEqual(mail.selected_row()['display_record_id'],rid)

    def test_exact_conversation_action_reaches_all_unlinked_siblings(self):
        self.window.open_mail('all')
        self.wait_for(lambda:self.window.mail_workspace.ready,'conversation list')
        mail=self.window.mail_workspace
        while not any(row['conversation_key']['conversation_id']=='multi-message' for row in mail.rows.values()):
            self.assertTrue(mail.next_cursor);mail.page_next();self.wait_for(lambda:mail.ready,'find conversation page')
        row=next(row for row in mail.rows.values() if row['conversation_key']['conversation_id']=='multi-message')
        rid=row['display_record_id'];self.window.open_record(rid,'Email')
        self.wait_for(lambda:self.window.page=='reader' and self.window.current_detail and self.window.current_detail['id']==rid,'conversation representative')
        button=next(b for b in self.window.findChildren(QPushButton) if b.text().startswith('View conversation ('))
        button.click()
        self.wait_for(lambda:self.window.page=='collection' and self.window.collection_ready,'full conversation')
        self.assertEqual(self.window.navigation.current['parameters'],{'mailbox_id':SELF,'conversation_id':'multi-message'})
        references=[];tree=self.window.active_collection();iterator=QTreeWidgetItemIterator(tree)
        while iterator.value():
            ref=self.window.collection_reference(iterator.value())
            if ref:references.append(ref['record_id'])
            iterator+=1
        self.assertEqual(len(set(references)),3)
        self.assertEqual({r['properties']['message_id'] for group in self.window.collection_data['structured']['rows'] for r in group['messages']}, {'branch-a','branch-b','branch-c'})

    def test_cc_only_dismiss_and_undo_through_widget(self):
        self.window.open_mail('unanswered',{'include_cc':True})
        self.wait_for(lambda:self.window.mail_workspace.ready and self.window.mail_workspace.task=='unanswered','copied-message view')
        mail=self.window.mail_workspace
        while not any(r['record']['properties']['message_id']=='copied-only' for r in mail.rows.values()):
            mail.page_next();self.wait_for(lambda:mail.ready,'find copied row')
        row=next(r for r in mail.rows.values() if r['record']['properties']['message_id']=='copied-only')
        rid=row['display_record_id'];mail.dismiss(row)
        self.wait_for(lambda:bool(mail.undo_token) and mail.ready and not self.window.km.pending,'copied dismissal')
        result=self.backend_query(task='unanswered',include_cc=True,search='copied-only')
        self.assertEqual(result['result']['total_count'],0)
        mail.undo();self.wait_for(lambda:mail.undo_token is None and mail.ready and not self.window.km.pending,'copied undo')
        result=self.backend_query(task='unanswered',include_cc=True,search='copied-only')
        self.assertEqual(result['result']['rows'][0]['display_record_id'],rid)

    def test_stale_route_callback_cannot_repaint_new_task(self):
        old=self.backend_query(task='unanswered');new=self.backend_query(task='waiting')
        callbacks=[]
        def capture(operation,params=None,callback=None,**kwargs):
            callbacks.append(callback);return len(callbacks)
        with patch.object(self.window.km,'request',side_effect=capture):
            self.window.open_mail('unanswered');self.window.open_mail('waiting')
            self.assertEqual(len(callbacks),2)
            callbacks[0](old)
            self.assertEqual(self.window.mail_workspace.rows,{})
            self.assertFalse(self.window.mail_workspace.ready)
            callbacks[1](new)
            self.assertTrue(self.window.mail_workspace.ready)
            self.assertEqual(self.window.mail_workspace.payload['task'],'waiting')

    def test_personalize_preview_generation_save_gate_and_rollback(self):
        self.window.open_mail('unanswered')
        self.wait_for(lambda:self.window.mail_workspace.ready and self.window.mail_workspace.task=='unanswered','personalize base')
        response=self.backend_query(task='unanswered',include_cc=True,page_size=1)
        before=copy.deepcopy(self.window.config.get('alpha3',{}).get('mail_views',[]))
        checks=[]
        def interact(dialog):
            dialog.show();APP.processEvents()
            save=self.button(dialog,'Save as new view');preview=self.button(dialog,'Preview matching mail')
            include=dialog.findChild(QCheckBox);name=dialog.findChild(QLineEdit)
            self.assertFalse(save.isEnabled());name.setText('Copied mail test')
            callbacks=[]
            def capture(operation,params=None,callback=None,**kwargs):callbacks.append(callback);return len(callbacks)
            with patch.object(self.window.km,'request',side_effect=capture):
                preview.click();include.setChecked(True);callbacks[0](response)
                self.assertFalse(save.isEnabled(),'Stale preview must not enable saving')
                preview.click();callbacks[1](response);self.assertTrue(save.isEnabled())
            with patch.object(self.window,'persist_preferences',return_value=False):save.click()
            self.assertEqual(self.window.config['alpha3']['mail_views'],before)
            self.assertTrue(any('Could not save' in label.text() for label in dialog.findChildren(QLabel)))
            checks.append('preview_and_rollback');dialog.reject()
        with patch.object(self.window,'run_dialog',side_effect=interact):self.window.mail_workspace.customize()
        self.assertEqual(checks,['preview_and_rollback'])


if __name__=='__main__':unittest.main()
