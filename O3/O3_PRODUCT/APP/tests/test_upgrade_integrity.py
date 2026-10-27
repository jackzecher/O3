"""Independent integrity gaps: review boundary, legacy preferences and recovery UI.

Backend reply, stale-write and backup round trips are intentionally covered by
test_mail_tasks instead. Appearance transactions live in test_human_customization.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_mail_integration as fixture
from o3_gui.km_client import WorkspaceLock
from o3_gui.logic import read_config, save_config
from PySide6.QtWidgets import QPushButton

BUILD=Path(__file__).resolve().parents[4]
WORKSPACE=Path(__file__).resolve().parents[6]
ARTIFACTS=BUILD/'test-artifacts'/'integrity'


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def hashes(root):
    return {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class IntegrityBoundariesTest(unittest.TestCase):
    def setUp(self):
        ARTIFACTS.mkdir(parents=True,exist_ok=True)
        self.temporary=tempfile.TemporaryDirectory(prefix='run-',dir=ARTIFACTS)
        self.root=Path(self.temporary.name)
        assert self.root.resolve().is_relative_to(ARTIFACTS.resolve())
        self.addCleanup(self.temporary.cleanup)

    def test_review_entry_requires_explicit_choice_before_startup(self):
        review=load_module('isolated_review_entry',BUILD/'review_app.py')
        with patch.object(sys,'argv',['review_app.py']),contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:review.main()
        self.assertEqual(raised.exception.code,2)

    def test_review_entry_uses_exact_explicit_state_and_lock(self):
        review=load_module('isolated_review_explicit',BUILD/'review_app.py')
        state=self.root/'explicit-state'
        with patch.object(sys,'argv',['review_app.py','--workspace',str(state),'--no-splash']),patch.object(sys,'path',list(sys.path)), \
             patch('PySide6.QtWidgets.QApplication') as app,patch('o3_gui.app.O3Window') as window, \
             patch('o3_gui.km_client.WorkspaceLock') as lock,patch('o3_gui.logic.read_config',return_value={}):
            lock.return_value.tryLock.return_value=True;app.return_value.exec.return_value=0
            self.assertEqual(review.main(),0)
            self.assertEqual(lock.call_args.args[0],state.resolve())
            self.assertEqual(window.call_args.args[0],state.resolve())
            self.assertIs(window.call_args.args[2],lock.return_value)
            lock.return_value.tryLock.assert_called_once_with(0)

    def test_original_candidate6_manifest_still_verifies(self):
        path=WORKSPACE/'review/candidate6-run/package/AI_RUNTIME/run.py'
        if not path.exists():self.skipTest('Original Candidate 6 local evidence unavailable')
        verifier=load_module('candidate6_readonly_verifier',path)
        manifest=verifier.verify_package()
        self.assertEqual(manifest['schema'],2)
        self.assertEqual(manifest['mode'],'OFFLINE_SYNTHETIC_QT_ONLY')

    def test_legacy_extensions_survive_read_save_without_replaying_cursor(self):
        original={'future_root':{'keep':[1,2]},'display':{'future_display':{'keep':True}},
            'navigation':{'future_nav':{'keep':'yes'},'last':{'section':'Email','kind':'Email',
                'view':'all','future_route':{'keep':'also'},'cursor':'do-not-replay','as_of':'stale'},
                'cursor':'do-not-persist','snapshot':{'obsolete':True}}}
        (self.root/'workspace.json').write_text(json.dumps(original),encoding='utf8')
        loaded=read_config(self.root);save_config(self.root,loaded)
        saved=json.loads((self.root/'workspace.json').read_text())
        self.assertEqual(saved['future_root'],original['future_root'])
        self.assertEqual(saved['display']['future_display'],original['display']['future_display'])
        self.assertEqual(saved['navigation']['future_nav'],original['navigation']['future_nav'])
        self.assertEqual(saved['navigation']['last']['future_route'],original['navigation']['last']['future_route'])
        self.assertNotIn('cursor',saved['navigation']);self.assertNotIn('snapshot',saved['navigation'])
        self.assertNotIn('cursor',saved['navigation']['last']);self.assertNotIn('as_of',saved['navigation']['last'])


class UpgradeIntegrityUITest(unittest.TestCase):
    # Reuse only the isolated window fixture, not its already-passing test cases.
    setUpClass=fixture.MailIntegrationTest.__dict__['setUpClass']
    wait_for=fixture.MailIntegrationTest.__dict__['wait_for']
    cleanup_workspace=fixture.MailIntegrationTest.__dict__['cleanup_workspace']
    setUp=fixture.MailIntegrationTest.setUp
    backend_query=fixture.MailIntegrationTest.backend_query

    def test_live_navigation_save_preserves_passive_extensions(self):
        w=self.window;w.preference_timer.stop()
        raw=json.loads((w.state/'workspace.json').read_text())
        raw.setdefault('navigation',{}).update({'future_nav':{'keep':'alive'}})
        raw['navigation'].setdefault('last',{}).update({'future_route':{'keep':42}})
        (w.state/'workspace.json').write_text(json.dumps(raw),encoding='utf8')
        w.config['navigation']=read_config(w.state)['navigation']
        self.assertTrue(w.persist_preferences())
        saved=json.loads((w.state/'workspace.json').read_text())
        self.assertEqual(saved['navigation']['future_nav'],{'keep':'alive'})
        self.assertEqual(saved['navigation']['last']['future_route'],{'keep':42})

    def test_source_and_save_failures_resolve_independently(self):
        w=self.window;w.source_failure='Synthetic unavailable source'
        with patch('o3_gui.app.save_config',side_effect=OSError('Synthetic preference failure')):
            self.assertFalse(w.persist_preferences())
            w.open_mail('unanswered')
            self.wait_for(lambda:w.mail_workspace.ready,'unrelated mail read')
            self.assertTrue(w.health_notice.isVisible());self.assertTrue(w.save_notice.isVisible())
            w.preference_timer.stop()
        self.assertTrue(w.persist_preferences())
        self.assertTrue(w.health_notice.isVisible());self.assertFalse(w.save_notice.isVisible())
        w.source_failure=None;w.config['last_capture_result']={'errors':[]};w.update_notices()
        self.assertFalse(w.health_notice.isVisible())

    def test_pending_project_connections_banner_retry_and_source_bytes(self):
        w=self.window;before=hashes(self.source);responses=[]
        with patch('o3_km.core_bridge.loes',side_effect=RuntimeError('Synthetic reconciliation failure')):
            w.km.request('loe.create',{'fields':{'name':'Retry integration project','kind':'project'}},
                responses.append,expected=w.km.revision,owner=w)
            self.wait_for(lambda:responses and w.project_notice.isVisible(),'persistent project retry banner')
        self.assertTrue(responses[0]['ok'])
        self.assertEqual(responses[0]['result']['project_reconciliation']['state'],'pending')
        w.open_mail('waiting');self.wait_for(lambda:w.mail_workspace.ready,'unrelated navigation')
        self.assertTrue(w.project_notice.isVisible())
        retry=next(b for b in w.project_notice.findChildren(QPushButton) if b.text()=='Retry project update')
        retry.click()
        self.wait_for(lambda:not w.project_notice.isVisible() and not w.km.pending,'successful project retry')
        self.assertEqual(w.summary_data['project_reconciliation']['state'],'complete')
        self.assertTrue(w.config['paused']);self.assertEqual(hashes(self.source),before)

    def test_reader_disposition_failure_is_visible_and_preserves_candidate(self):
        w=self.window;w.open_mail('unanswered')
        self.wait_for(lambda:w.mail_workspace.ready,'unanswered selection')
        row=next(r for r in w.mail_workspace.rows.values() if r['state']=='candidate')
        rid=row['display_record_id'];w.open_record(rid,'Email')
        self.wait_for(lambda:w.page=='reader' and w.current_detail and w.current_detail['id']==rid,'reader')
        with patch.object(w,'show_information') as notice:
            w.km.revision-=1  # A genuinely stale optimistic revision reaches KM.
            w.mail_workspace.dismiss(row)
            self.wait_for(lambda:not w.km.pending,'rejected stale disposition')
            self.assertTrue(notice.called,'Reader-originated failures must be visible outside hidden Mail')
            self.assertIn('not saved',w.mail_workspace.action_notice.text())
            self.assertEqual(row['state'],'candidate')
            self.assertIsNone(w.mail_workspace.undo_token)

    def test_stable_workspace_lock_blocks_second_owner_during_restore_gap(self):
        contender=WorkspaceLock(self.state)
        self.assertFalse(contender.tryLock(0))
        self.lock.release_legacy()
        try:self.assertFalse(contender.tryLock(0),'Stable lock must outlive the replaceable state directory')
        finally:self.assertTrue(self.lock.reacquire_legacy())
        self.assertTrue(self.lock.isLocked())


if __name__=='__main__':unittest.main()
