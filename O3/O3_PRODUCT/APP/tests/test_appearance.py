"""Appearance contracts: readability, staged persistence, real rendering, startup."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import unittest
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QWidget, QStyleOptionViewItem
from o3_gui.appearance import (THEMES, DEFAULTS, normalize_appearance, appearance_from_config,
    store_appearance, saved_looks, contrast)
from o3_gui.presentation import theme_tokens
from o3_gui.panels import SettingsPanel
from o3_gui.startup import WelcomeScreen, ReviewStartup
from o3_gui.ui import RecordDelegate
from test_human_customization import SettingsHost
import test_mail_integration as fixture

APP=QApplication.instance() or QApplication([])


class AppearanceContractsTest(unittest.TestCase):
    def test_twenty_four_unique_balanced_palettes(self):
        self.assertEqual(len(THEMES),24)
        self.assertEqual(sum(v[1]=='light' for v in THEMES.values()),12)
        self.assertEqual(sum(v[1]=='dark' for v in THEMES.values()),12)
        self.assertEqual(len({v[2:] for v in THEMES.values()}),24)

    def test_all_palettes_and_extreme_accents_keep_text_and_buttons_readable(self):
        for key in THEMES:
            for stronger in (False,True):
                for accent in (None,'#ffffff','#000000','#ffff00','#ff0099','#00ffff'):
                    with self.subTest(theme=key,stronger=stronger,accent=accent):
                        c=theme_tokens(key,{'accent':accent,'contrast':stronger})
                        for fg in ('body','muted','accent'):
                            for bg in ('canvas','rail','surface','control','selection','hover'):
                                self.assertGreaterEqual(contrast(c[fg],c[bg]),7 if stronger else 4.5)
                        for bg in ('accent','accent_hover'):
                            self.assertGreaterEqual(contrast(c['on_accent'],c[bg]),4.5)
                        if stronger:self.assertGreaterEqual(contrast(c['border'],c['control']),3)

    def test_malformed_settings_are_bounded_and_unknown_extensions_survive(self):
        bad={key:[] for key in DEFAULTS};bad.update(accent='red; font-size:1px',text_scale=True,show_splash=1)
        self.assertEqual(normalize_appearance(bad),DEFAULTS)
        config={'future':'keep','alpha3':{'theme':'night','text_scale':1.25,'future':{'x':1},'appearance':{'future_appearance':[1,2]}}}
        old=deepcopy(config);a=appearance_from_config(config)
        self.assertEqual((a['theme'],a['text_scale']),('night',1.25))
        store_appearance(config,{**a,'accent':'#fFaa88','reader_font':'book'})
        self.assertEqual(config['future'],'keep');self.assertEqual(config['alpha3']['future'],old['alpha3']['future'])
        self.assertEqual(config['alpha3']['appearance']['future_appearance'],[1,2])
        self.assertEqual(appearance_from_config(config)['accent'],'#ffaa88')

    def test_saved_looks_validate_names_ids_and_choices(self):
        result=saved_looks([{'id':'good','name':' Evenings ','appearance':{'theme':'forest','text_scale':1.4}},
            {'id':'good','name':'Duplicate'}, {'id':'bad','name':'\n'}, {'id':{},'name':'Malformed'}])
        self.assertEqual(len(result),1);self.assertEqual(result[0]['name'],'Evenings');self.assertEqual(result[0]['appearance']['theme'],'forest')
        result[0]['appearance']['theme']='night';self.assertEqual(DEFAULTS['theme'],'harbor')

    def test_full_editor_cancel_and_failed_save_never_leak_into_other_writes(self):
        host=SettingsHost(None);panel=SettingsPanel(host);before=deepcopy(host.config)
        try:
            editor=panel.appearance_editor
            editor.set_value({**DEFAULTS,'theme':'plum','text_scale':1.4,'accent':'#ffaaaa','font':'soft',
                'reader_font':'book','reader_scale':1.25,'density':'comfortable','reading_width':'narrow','navigation':'focus','contrast':True,'show_splash':False})
            editor.look_name.setText('Evening reading');editor.add_look()
            host.persist_preferences();self.assertEqual(host.persisted,before)
            host.fail_save=True;panel.save_appearance();self.assertTrue(panel.appearance_save_failed)
            self.assertEqual(host.config,before);self.assertEqual(host.persisted,before)
            self.assertEqual(editor.looks[0]['name'],'Evening reading')
            self.assertEqual(host.appearance['density'],'comfortable')
            panel.reject();self.assertEqual(host.config,before);self.assertEqual(host.appearance,appearance_from_config(before))
        finally:panel.deleteLater();host.deleteLater();APP.processEvents()

    def test_save_reopen_look_library_and_restore_defaults_are_independent(self):
        host=SettingsHost(None);panel=SettingsPanel(host)
        try:
            e=panel.appearance_editor;e.set_value({**DEFAULTS,'theme':'forest','reader_font':'book','density':'comfortable'})
            e.look_name.setText('My reading room');e.add_look();panel.save_appearance()
            self.assertEqual(host.writes,1);self.assertEqual(host.persisted['alpha3']['saved_looks'][0]['name'],'My reading room')
            self.assertEqual(appearance_from_config(host.persisted)['theme'],'forest')
            reopened=SettingsPanel(host)
            try:
                e=reopened.appearance_editor;e.set_value(DEFAULTS)
                self.assertEqual(len(e.looks),1);self.assertEqual(host.persisted['alpha3']['theme'],'forest')
                e.look_list.setCurrentRow(0);e.use_look();self.assertEqual(e.get_value()['reader_font'],'book')
                e.remove_look();self.assertEqual(len(e.looks),0);reopened.reject()
                self.assertEqual(len(host.persisted['alpha3']['saved_looks']),1)
            finally:reopened.deleteLater()
        finally:panel.deleteLater();host.deleteLater();APP.processEvents()

    def test_gallery_filter_keeps_all_themes_available_and_selected(self):
        host=SettingsHost(None);panel=SettingsPanel(host)
        try:
            e=panel.appearance_editor;e.filter.setCurrentIndex(e.filter.findData('dark'))
            self.assertEqual(sum(not c.isHidden() for c in e.gallery.cards.values()),12)
            e.gallery.cards['moss'].click();self.assertEqual(e.get_value()['theme'],'moss')
            e.filter.setCurrentIndex(e.filter.findData('light'));self.assertEqual(e.get_value()['theme'],'moss')
            self.assertEqual(sum(not c.isHidden() for c in e.gallery.cards.values()),12)
        finally:panel.reject();panel.deleteLater();host.deleteLater();APP.processEvents()

    def test_startup_handoff_has_no_timer_and_distinguishes_failure(self):
        class Window(QWidget):
            startup_finished=Signal(bool)
            initialized=False
        for success in (True,False):
            w=Window();s=WelcomeScreen({'theme':'night'});controller=ReviewStartup(w,s)
            try:
                self.assertFalse(w.isVisible());self.assertFalse(controller.finished)
                w.startup_finished.emit(success)
                self.assertTrue(w.isVisible());self.assertFalse(s.isVisible());self.assertEqual(controller.succeeded,success)
                w.startup_finished.emit(not success);self.assertEqual(controller.succeeded,success)
            finally:s.deleteLater();w.deleteLater();APP.processEvents()


class AppearanceIntegrationTest(unittest.TestCase):
    setUpClass=fixture.MailIntegrationTest.__dict__['setUpClass']
    wait_for=fixture.MailIntegrationTest.__dict__['wait_for']
    cleanup_workspace=fixture.MailIntegrationTest.__dict__['cleanup_workspace']
    setUp=fixture.MailIntegrationTest.setUp
    backend_query=fixture.MailIntegrationTest.backend_query

    def test_real_window_preview_changes_density_layout_and_reader_without_saving(self):
        w=self.window;before=deepcopy(w.config.get('alpha3',{}));w.resize(1600,900)
        w.open_mail('unanswered');self.wait_for(lambda:w.mail_workspace.ready,'mail')
        item=w.mail_workspace.listing.item(0);self.assertIsNotNone(item)
        w.mail_workspace.listing.setCurrentItem(item)
        record=item.data(Qt.UserRole+1);delegate=w.mail_workspace.listing.itemDelegate();option=QStyleOptionViewItem();option.font=w.font()
        w.apply_appearance({**DEFAULTS,'density':'compact'},preview=True);compact=delegate.layout_for(option,record)['height']
        w.apply_appearance({**DEFAULTS,'theme':'deep-ocean','density':'comfortable','navigation':'focus','reading_width':'narrow','reader_font':'book','line_spacing':1.7},preview=True)
        self.assertGreater(delegate.layout_for(option,record)['height'],compact)
        self.assertFalse(w.sidebar.isVisible());self.assertTrue(w.workspace_menu.isVisible());self.assertEqual(w.reading.maximumWidth(),640)
        self.assertIn('Georgia',w.body_html('A paragraph.'));self.assertIn('170%',w.body_html('A paragraph.'))
        self.assertEqual(w.config.get('alpha3',{}),before)
        self.assertIs(w.mail_workspace.listing.currentItem(),item)
        self.assertTrue(w.persist_preferences())
        from o3_gui.logic import read_config
        self.assertEqual(read_config(w.state).get('alpha3',{}),before)
        w.apply_appearance(appearance_from_config(w.config))


if __name__=='__main__':unittest.main()
