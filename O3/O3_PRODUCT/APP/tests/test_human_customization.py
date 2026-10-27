"""Offscreen interaction tests against a fresh, real KM; no user state is opened."""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QLabel, QWidget, QListWidget, QComboBox, QPushButton
from o3_gui.km_session import KMSession
from o3_km.service import VERSION
from o3_gui.human_customization import HumanViewEditor, SavedViewsDialog, readable_selection, simple_fields
from o3_gui.workspace_editor import SharedSettings, saved_changes_text
from o3_gui.display_preferences import validate_display_preferences, view_layout
from o3_gui.panels import SettingsPanel
from o3_gui.workspace_type_editor import WorkspaceTypeEditor

APP=QApplication.instance() or QApplication([])
ARTIFACTS=Path(__file__).resolve().parents[4]/'test-artifacts'/'customization'
ASOF='2026-10-27T18:00:00Z'


class Client:
    def __init__(self, session): self.session=session; self.calls=[]; self.deferred=[]; self.defer=False
    @property
    def revision(self): return self.session.km.revision()
    def cancel_owner(self,owner): pass
    def request(self,op,params,done,*,owner=None,expected=None,as_of=None):
        self.calls.append((op,params,expected))
        envelope={'contract':VERSION,'operation':op,'params':params,'as_of':as_of or ASOF}
        if expected is not None: envelope['expected_workspace_revision']=expected
        response=self.session.call(envelope)
        if self.defer: self.deferred.append((done,response))
        else: done(response)
    def deliver(self):
        done,response=self.deferred.pop(0);done(response)


class SettingsHost(QWidget):
    preferences_saved=Signal(bool,str)
    def __init__(self,client):
        super().__init__();self.km=client;self.config={'alpha3':{'theme':'harbor','text_scale':1.0}};self.scale=1.0;self.preferences_error='';self.summary_data={};self.applied=[]
        self.preview_theme=None;self.fail_save=False;self.persisted=deepcopy(self.config);self.writes=0
        self.navigation=type('Navigation',(),{'restore_last':True,'forget_recent':lambda self:None})()
        self.preference_timer=type('Timer',(),{'start':lambda self:None})()
    def apply_theme(self,key,persist=True):
        self.applied.append(key)
        if persist:self.config.setdefault('alpha3',{})['theme']=key;self.preview_theme=None
        else:self.preview_theme=key
    def apply_scale(self,value,persist=True):
        self.scale=value
        if persist:self.config.setdefault('alpha3',{})['text_scale']=value
    def apply_appearance(self,value,preview=False):
        from o3_gui.appearance import normalize_appearance
        self.appearance=normalize_appearance(value);self.scale=self.appearance['text_scale']
        self.preview_appearance_values=deepcopy(self.appearance) if preview else None
        if preview and self.preview_theme!=self.appearance['theme']:self.applied.append(self.appearance['theme'])
        self.preview_theme=self.appearance['theme'] if preview else None
    def persist_preferences(self):
        self.writes+=1
        if not self.fail_save:self.persisted=deepcopy(self.config)
        self.preferences_saved.emit(not self.fail_save,'simulated failure' if self.fail_save else '')
        return not self.fail_save
    def do_backup(self):pass
    def do_restore(self):pass


class HumanCustomizationTest(unittest.TestCase):
    def setUp(self):
        ARTIFACTS.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(prefix='human-',dir=ARTIFACTS)
        self.root=Path(self.temp.name);self.session=KMSession(self.root/'state',actor='test:human-customization');self.session.open()
        self.client=Client(self.session);self.schema=self.session.query('builder.schema',{'record_type':'Email'});self.widgets=[]
    def tearDown(self):
        for widget in reversed(self.widgets): widget.deleteLater()
        APP.processEvents();self.session.close();self.temp.cleanup()
    def editor(self,definition=None,**kwargs):
        d=HumanViewEditor(self.client,'Email',self.schema,definition,**kwargs);self.widgets.append(d);return d
    def mutate(self,op,params):
        return self.session.query(op,params,expected_workspace_revision=self.client.revision,as_of=ASOF)
    def definition(self,spec):
        created=self.mutate('view.create',{'record_type':'Email','specification':spec})
        return next(v for v in self.session.query('registry.views',{'record_type':'Email'})['views'] if v['view_id']==created['definition_id'])
    def test_create_preview_save_and_copy_are_real_authority_calls(self):
        layouts=[];d=self.editor(persist_presentation=lambda *args:layouts.append(args));d.name.setText('My mail')
        d.save();self.assertIsNotNone(d.preview_response);self.assertFalse(d.saved_id)
        self.assertIn('No items match',d.preview_note.text())
        d.save();self.assertTrue(d.saved_id.startswith('view:user:'));self.assertEqual(len(layouts),1)
        saved=next(v for v in self.session.query('registry.views',{'record_type':'Email'})['views'] if v['view_id']==d.saved_id)
        copy=self.editor(saved,duplicate=True,persist_presentation=lambda *args:None);copy.preview();copy.save()
        self.assertNotEqual(copy.saved_id,d.saved_id)
    def test_plain_choice_changes_use_real_preview_without_rule_editor(self):
        d=self.editor();d.name.setText('Attachment mail');d.add_condition({'field':'has_attachments','operator':'equals','value':True})
        d.preview();self.assertIsNotNone(d.preview_response,d.message.text())
        self.assertEqual(d.spec()['filter_expression'],{'all':[{'field':'has_attachments','operator':'equals','value':True}]})
        self.assertEqual([d.editor_body.tabText(i) for i in range(4)],['Name','Include','Layout','Preview'])
        self.assertFalse(d.expression.isVisibleTo(d.editor_body))
        self.assertNotIn('record_id',simple_fields(self.schema))
    def test_incomplete_choice_is_readable_validation_not_an_exception(self):
        d=self.editor();d.name.setText('Draft');d.add_condition({'field':'subject','operator':'contains','value':''})
        d.save();self.assertIn('Finish each choice',d.message.text());self.assertFalse(d.saved_id)
    def test_legacy_filters_and_sort_survive_rename_exactly(self):
        spec={'label':'Older view','record_type':'Email','filters':[{'field':'subject','operator':'equals','value':'Budget'}],'sort':'record_id','sort_direction':'asc','group_by':'none','include_inactive':False}
        original=self.definition(spec);d=self.editor(original);d.name.setText('Budget messages');d.columns.reset()
        for key in ('filters','sort','sort_direction','group_by','include_inactive'):self.assertEqual(d.spec()[key],original[key])
        self.assertNotIn('filter_expression',d.spec());self.assertNotIn('sorts',d.spec())
        d.preview();d.save();self.assertTrue(d.saved_id)
    def test_nested_and_search_selection_survives_layout_and_name_changes(self):
        expression={'all':[{'any':[{'field':'subject','operator':'contains','value':'budget'},{'field':'subject','operator':'contains','value':'plan'}]}]}
        spec={'label':'Complex old view','record_type':'Email','filter_expression':expression,'sorts':[{'field':'updated_at','direction':'desc'}],'search':'Budget'}
        original=self.definition(spec);d=self.editor(original)
        self.assertTrue(d.selection_locked);self.assertFalse(d.add_choice.isVisibleTo(d.editor_body))
        d.name.setText('Planning');d.columns.reset();self.assertEqual(d.spec()['filter_expression'],expression);self.assertEqual(d.spec()['search'],'Budget')
        d.preview();d.save();self.assertTrue(d.saved_id,d.message.text())
    def test_old_preview_cannot_approve_new_choices(self):
        d=self.editor();d.name.setText('Draft');self.client.defer=True;d.preview();d.name.setText('Different draft');self.client.deliver()
        self.assertIsNone(d.preview_response);self.assertFalse(d.saved_id)
        self.assertIn('changed',d.message.text())
    def test_layout_retry_does_not_duplicate_a_saved_view(self):
        attempts=[]
        def persist(*args):
            attempts.append(args)
            if len(attempts)==1:raise OSError('simulated unavailable preference file')
        d=self.editor(persist_presentation=persist);d.name.setText('Retry this layout');d.preview();d.save()
        self.assertTrue(d.saved_id);self.assertIn('layout could not be saved',d.message.text())
        first=d.saved_id;d.save();self.assertEqual(d.saved_id,first);self.assertEqual(len(attempts),2)
        self.assertEqual(sum(op=='view.create' for op,_,_ in self.client.calls),1)
    def test_populated_preview_matches_real_records(self):
        source=self.root/'exports'
        for p in ('Mail/Inbox','Mail/Sent','Contacts/Profiles','Calendars','Documents'):(source/p).mkdir(parents=True)
        for index,subject in enumerate(('Budget discussion','Lunch plans')):
            raw={'schema_version':'em-raw-v1','mailbox_id':'alex@example.test','message_id':str(index),'source_folder':'Inbox','subject':subject,'from':{'address':'sam@example.test'},'to':[{'address':'alex@example.test'}],'captured_at_utc':ASOF,'received_at_utc':ASOF}
            (source/'Mail/Inbox'/f'{index}.json').write_text(json.dumps(raw))
        self.session.scan(source)
        d=self.editor();d.name.setText('Budget');d.add_condition({'field':'subject','operator':'contains','value':'Budget'});d.preview()
        self.assertEqual(d.preview_response['result']['total_count'],1)
        d.save();result=self.session.query('view.query',{'view_id':d.saved_id},as_of=ASOF)
        self.assertEqual(result['total_count'],1)
    def test_conflict_does_not_overwrite_or_discard_draft(self):
        d=self.editor();d.name.setText('Keep this draft');d.preview()
        self.mutate('configuration.save',{'week_start':'sunday'})
        d.save();self.assertFalse(d.saved_id);self.assertEqual(d.name.text(),'Keep this draft')
        self.assertIn('changed elsewhere',d.message.text());self.assertFalse(any(v.get('label')=='Keep this draft' for v in self.session.query('registry.views')['views']))
    def test_cancel_and_layout_reset_do_not_write(self):
        d=self.editor();d.name.setText('Unsaved');d.columns.reset()
        with patch('o3_gui.workspace_editor.confirm',return_value=True):d.reject()
        self.assertFalse(any(op in ('view.create','view.edit') for op,_,_ in self.client.calls))
    def test_identity_suggestions_require_confirmation_and_aliases_persist(self):
        source=self.root/'exports'
        for p in ('Mail/Inbox','Mail/Sent','Contacts/Profiles','Calendars','Documents'):(source/p).mkdir(parents=True)
        raw={'schema_version':'em-raw-v1','mailbox_id':'alex@example.test','message_id':'identity','source_folder':'Inbox','subject':'Hello','from':{'address':'sam@example.test'},'to':[{'address':'alex@example.test'}],'captured_at_utc':ASOF,'received_at_utc':ASOF}
        (source/'Mail/Inbox/identity.json').write_text(json.dumps(raw));self.session.scan(source)
        d=SharedSettings(self.client);self.widgets.append(d)
        self.assertTrue(d.save_button.isEnabled());self.assertEqual(d.details()['self_addresses'],[])
        self.assertTrue(d.suggestions);self.assertTrue(all(not check.isChecked() for check,_ in d.suggestions))
        d.aliases.setPlainText('alias@example.test');d.suggestions[0][0].setChecked(True);d.save()
        self.assertEqual(set(self.session.km.settings()['self_addresses']),{'alex@example.test','alias@example.test'})
    def test_saved_view_manager_and_custom_collection_layout_roundtrip(self):
        d=SavedViewsDialog(self.client,'Email');self.widgets.append(d)
        self.assertTrue(d.schema);self.assertTrue(d.items.count());self.assertTrue(d.new_button.isEnabled())
        kind='wsrt_'+'a'*32;layout=view_layout(kind);layout['density']='comfortable'
        raw={'views':{'view:user:example':layout}}
        self.assertEqual(validate_display_preferences(raw)['views']['view:user:example'],layout)
    def test_conflict_summary_hides_storage_identifiers(self):
        text=saved_changes_text({'settings':{'self_addresses':['a@example.test'],'week_start':'monday'},'views':[{'view_id':'view:user:secret','label':'Mail I saved','filter_expression':{'all':[]}}]})
        self.assertIn('Your email addresses: a@example.test',text);self.assertIn('Name: Mail I saved',text)
        self.assertNotIn('view:user:secret',text);self.assertNotIn('filter_expression',text)
    def test_settings_themes_and_collection_editor_are_plain_and_functional(self):
        host=SettingsHost(self.client);self.widgets.append(host);panel=SettingsPanel(host);self.widgets.append(panel)
        nav=panel.findChild(QListWidget,'settingsNav')
        self.assertEqual([nav.item(i).text() for i in range(nav.count())],['Appearance','Your details','Saved views','Data & backups','About'])
        theme=next(c for c in panel.findChildren(QComboBox) if c.accessibleName()=='Color theme')
        self.assertEqual(theme.count(),24);theme.setCurrentIndex(theme.findData('night'));self.assertEqual(host.applied,['night'])
        editor=WorkspaceTypeEditor(self.client);self.widgets.append(editor);editor.name.setText('Idea');editor.plural.setText('Ideas');editor.save()
        self.assertTrue(editor.saved,editor.message.text());self.assertFalse(editor.tabs.isTabVisible(1));self.assertFalse(editor.is_dirty())
    def test_appearance_preview_failure_and_cancel_preserve_saved_preferences(self):
        host=SettingsHost(self.client);self.widgets.append(host);panel=SettingsPanel(host);self.widgets.append(panel)
        original=deepcopy(host.persisted)
        panel.theme.setCurrentIndex(panel.theme.findData('night'));panel.scale_choice.setCurrentIndex(panel.scale_choice.findData(1.5))
        self.assertEqual(host.config,original);self.assertEqual(host.writes,0);self.assertEqual(host.preview_theme,'night')
        # Saving an unrelated setting must not accidentally save this preview.
        host.persist_preferences();self.assertEqual(host.persisted,original)
        host.fail_save=True;panel.save_appearance()
        self.assertTrue(panel.appearance_save_failed);self.assertEqual(host.config,original);self.assertEqual(host.persisted,original)
        self.assertEqual(host.preview_theme,'night');self.assertEqual(host.scale,1.5);self.assertEqual(panel.theme.currentData(),'night')
        panel.reject();self.assertEqual(host.scale,1.0);self.assertIsNone(host.preview_theme);self.assertEqual(host.config,original)
    def test_settings_navigation_grows_for_large_text_without_clipping_labels(self):
        host=SettingsHost(self.client);self.widgets.append(host);panel=SettingsPanel(host);self.widgets.append(panel)
        nav=panel.findChild(QListWidget,'settingsNav');nav.setStyleSheet('QListWidget { font-size:21px; }');font=QFont(nav.font());font.setPixelSize(21);nav.setFont(font)
        panel.show();APP.processEvents();font.setWeight(QFont.Weight.DemiBold);metrics=QFontMetrics(font)
        for i in range(nav.count()):
            nav.setCurrentRow(i);APP.processEvents()
            self.assertGreaterEqual(nav.viewport().width(),metrics.horizontalAdvance(nav.item(i).text())+24)
        self.assertFalse(nav.horizontalScrollBar().isVisible());panel.reject()
    def test_appearance_reset_is_a_preview_and_success_saves_once(self):
        host=SettingsHost(self.client);self.widgets.append(host);panel=SettingsPanel(host);self.widgets.append(panel)
        panel.theme.setCurrentIndex(panel.theme.findData('night'));panel.scale_choice.setCurrentIndex(panel.scale_choice.findData(1.5))
        reset=next(b for b in panel.findChildren(QPushButton) if b.text()=='Restore default appearance');reset.click()
        self.assertEqual(panel.theme.currentData(),'harbor');self.assertEqual(panel.scale_choice.currentData(),1.0);self.assertEqual(host.writes,0)
        panel.theme.setCurrentIndex(panel.theme.findData('sage'));panel.save_appearance()
        self.assertEqual(host.writes,1);self.assertEqual(host.persisted['alpha3']['theme'],'sage');self.assertIsNone(host.preview_theme)
        self.assertTrue(panel.appearance_committed)


if __name__=='__main__': unittest.main()
