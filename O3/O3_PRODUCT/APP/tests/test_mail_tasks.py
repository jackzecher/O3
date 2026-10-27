"""Headless semantic/recovery tests using real prepared files and Core ingestion.

Run from the APP directory with unittest discovery. Every writable state is a
fresh temporary directory; Candidate 6 evidence is copied before opening.
"""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from o3_gui.km_session import KMSession, SessionError
from o3_gui.logic import save_config, read_config
from o3_core.engine import Engine
from o3_km.catalog import CATALOG_FINGERPRINT
from o3_km.mail_tasks import PREFIX, MAX_ACTION_ANCHORS, _records

SELF='alex@example.test'
OTHER='sam@example.test'
ASOF='2026-10-27T16:00:00Z'
TEST_ROOT=Path(__file__).resolve().parents[4]/'test-artifacts'/'backend'


def temporary_workspace(prefix):
    TEST_ROOT.mkdir(parents=True,exist_ok=True)
    temporary=tempfile.TemporaryDirectory(prefix=prefix,dir=TEST_ROOT)
    assert Path(temporary.name).resolve().is_relative_to(TEST_ROOT.resolve())
    return temporary


class MailTasksTest(unittest.TestCase):
    def setUp(self):
        self.temp=temporary_workspace('mail-')
        temporary_patch=patch.object(tempfile,'tempdir',str(TEST_ROOT))
        temporary_patch.start();self.addCleanup(temporary_patch.stop)
        self.root=Path(self.temp.name); self.source=self.root/'source'; self.state=self.root/'state'
        for name in ('Mail/Inbox','Mail/Sent','Contacts/Profiles','Calendars','Documents'):
            (self.source/name).mkdir(parents=True)
        self.session=KMSession(self.state,actor='test:mail'); self.session.open()
        self.mutate('configuration.save',{'self_addresses':[SELF]})

    def tearDown(self):
        self.session.close(); self.temp.cleanup()

    def mutate(self,op,params,revision=None):
        return self.session.query(op,params,expected_workspace_revision=
            self.session.km.revision() if revision is None else revision,as_of=ASOF)

    def mail(self,id,*,out=False,sender=None,to=None,cc=(),conv=None,reply=None,box=SELF,stamp=None,**changes):
        folder='Sent' if out else 'Inbox'
        value={'schema_version':'em-raw-v1','mailbox_id':box,'message_id':id,
            'internet_message_id':'<'+id+'@example.test>','conversation_id':conv or id,
            'subject':'Subject '+id,'source_folder':folder,
            'from':{'address':sender or (SELF if out else OTHER)},
            'to':[{'address':x} for x in (to if to is not None else [OTHER if out else SELF])],
            'cc':[{'address':x} for x in cc],
            'captured_at_utc':'2026-10-27T15:59:00Z',
            'sent_at_utc' if out else 'received_at_utc':stamp or '2026-10-27T15:55:00Z',
            'body_text':'A captured message.'}
        if reply:value['in_reply_to']='<'+reply+'@example.test>'
        value.update(changes)
        path=self.source/'Mail'/folder/(id+'.json'); path.write_text(json.dumps(value),encoding='utf8')
        return path

    def scan(self):
        result=self.session.scan(self.source)
        self.assertFalse(result['errors'],result['errors'])
        return result

    def query(self,task='unanswered',**params):
        return self.session.query('mail.tasks.query',{'task':task,**params},as_of=ASOF)

    def ids(self,result):
        return {r['record']['properties']['message_id'] for r in result['rows']}

    def test_fresh_default_recent_multito_missing_cc(self):
        path=self.mail('recent',to=[SELF,'jo@example.test'])
        value=json.loads(path.read_text());value.pop('cc');path.write_text(json.dumps(value))
        self.scan(); result=self.query()
        self.assertEqual(self.ids(result),{'recent'}); self.assertEqual(result['candidate_count'],1)
        self.assertIn('saved mail',result['rows'][0]['reason'])
        self.assertEqual(self.session.km.db.execute('SELECT COUNT(*) FROM ws_definitions').fetchone()[0],0)

    def test_cc_only_is_explicit(self):
        self.mail('copy',to=['jo@example.test'],cc=[SELF]);self.scan()
        self.assertEqual(self.query()['total_count'],0)
        self.assertEqual(self.ids(self.query(include_cc=True)),{'copy'})
        self.assertEqual(self.ids(self.query('all')),{'copy'})

    def test_aliases_use_confirmed_config(self):
        self.mail('alias',to=['a.smith@example.test']);self.scan()
        self.assertEqual(self.query()['total_count'],0)
        self.mutate('configuration.save',{'self_addresses':[SELF,'A.Smith@example.test']})
        self.assertEqual(self.query()['candidate_count'],1)

    def test_identity_suggestions_are_not_ownership(self):
        self.mail('incoming');self.mail('outgoing',out=True);self.scan()
        self.mutate('configuration.save',{'self_addresses':[]})
        identity=self.session.query('mail.identity')
        self.assertEqual(identity['state'],'confirmation_required')
        self.assertEqual(identity['suggestions'][0]['address'],SELF)
        self.assertTrue(identity['suggestions'][0]['requires_confirmation'])
        self.assertEqual(self.query()['uncertain_count'],1)
        self.assertEqual(self.query('all')['total_count'],2)
        self.assertEqual(self.session.km.settings()['self_addresses'],[])

    def test_direct_self_reply_covers_incoming(self):
        self.mail('in',conv='chain');self.mail('reply',out=True,conv='chain',reply='in');self.scan()
        self.assertEqual(self.query()['total_count'],0)
        self.assertEqual(self.query('waiting')['candidate_count'],1)

    def test_transitive_self_reply_and_other_response(self):
        self.mail('in',conv='chain');self.mail('other',sender='jo@example.test',conv='chain',reply='in')
        self.mail('mine',out=True,conv='chain',reply='other');self.scan()
        self.assertEqual(self.query()['total_count'],0)
        self.mail('reply',conv='chain',reply='mine');self.scan()
        self.assertEqual(self.query('waiting')['total_count'],0)
        self.assertEqual(self.ids(self.query()),{'reply'})

    def test_other_recipient_does_not_prove_self_replied(self):
        self.mail('in',conv='chain',to=[SELF,'jo@example.test'])
        self.mail('other',sender='jo@example.test',conv='chain',reply='in');self.scan()
        row=self.query()['rows'][0]
        self.assertEqual(len(row['anchor_record_ids']),2)

    def test_branch_preservation(self):
        self.mail('a',conv='branches');self.mail('b',conv='branches')
        self.mail('reply',out=True,conv='branches',reply='a');self.scan()
        result=self.query();self.assertEqual(self.ids(result),{'b'})
        self.assertEqual(len(result['rows'][0]['anchor_record_ids']),1)

    def test_later_message_without_link_is_not_reply(self):
        self.mail('in',conv='same',stamp='2026-10-26T12:00:00Z')
        self.mail('later',out=True,conv='same');self.scan()
        self.assertEqual(self.query()['candidate_count'],1)
        self.assertEqual(self.query('waiting')['candidate_count'],1)

    def test_one_response_satisfies_multi_recipient_wait(self):
        self.mail('sent',out=True,conv='same',to=[OTHER,'jo@example.test'])
        self.mail('reply',conv='same',reply='sent');self.scan()
        self.assertEqual(self.query('waiting')['total_count'],0)

    def test_self_to_self_not_waiting(self):
        self.mail('self',out=True,to=[SELF]);self.scan()
        self.assertEqual(self.query('waiting')['total_count'],0)

    def test_missing_sent_is_uncertain_but_all_available(self):
        (self.source/'Mail'/'Sent').rmdir();self.mail('in');self.scan()
        result=self.query();self.assertEqual(result['uncertain_count'],1)
        self.assertEqual(result['rows'][0]['reason_codes'],['sent_unavailable'])
        self.assertEqual(self.query('all')['total_count'],1)

    def test_empty_available_sent_only_bounded_absence(self):
        self.mail('in');self.scan();result=self.query()
        self.assertEqual(result['candidate_count'],1)
        self.assertEqual(result['remote_freshness'],'unknown')
        self.assertIn('do not establish complete',result['coverage_scope'])
        self.assertNotIn('have not replied',result['rows'][0]['reason'])

    def test_missing_reference_and_partial_results(self):
        self.mail('good');self.mail('gap',reply='missing');self.scan()
        result=self.query();self.assertEqual(result['candidate_count'],1);self.assertEqual(result['uncertain_count'],1)
        self.assertEqual(result['rows'][1]['reason_codes'],['thread_gap'])

    def test_same_conversation_two_mailboxes_remains_distinct(self):
        self.mail('first',conv='shared');self.mail('second',conv='shared',box='other@example.test');self.scan()
        self.assertEqual(self.query('all')['total_count'],2)
        self.assertEqual(self.query()['uncertain_count'],2)

    def test_cross_mailbox_reply_does_not_close(self):
        self.mail('in',conv='same');self.mail('out',out=True,conv='same',reply='in',box='other@example.test');self.scan()
        self.assertEqual(self.query()['total_count'],1)
        self.assertEqual(self.query()['rows'][0]['state'],'uncertain')

    def test_missing_conversation_keeps_mail_visible(self):
        self.mail('noid',conversation_id=None);self.scan()
        row=self.query('all')['rows'][0]
        self.assertEqual(row['conversation_key']['standalone_record_id'],row['display_record_id'])

    def test_sender_folder_conflict(self):
        self.mail('conflict',out=True,sender=OTHER);self.scan()
        self.assertEqual(self.query('waiting')['rows'][0]['reason_codes'],['direction_conflict'])

    def test_dismiss_undo_new_anchor_and_stale_write(self):
        self.mail('old',conv='same');self.scan();row=self.query()['rows'][0]
        rev=self.session.km.revision()
        result=self.mutate('mail.tasks.action',{'action':'dismiss','task':'unanswered','anchor_record_ids':row['anchor_record_ids']})
        self.assertEqual(self.query()['total_count'],0);self.assertEqual(self.query('all')['total_count'],1)
        self.mail('new',conv='same',reply='old');self.scan()
        self.assertEqual(self.ids(self.query()),{'new'})
        with self.assertRaises(SessionError):self.mutate('mail.tasks.action',{'action':'undo','undo_token':result['undo_token']},revision=rev)
        self.mutate('mail.tasks.action',{'action':'undo','undo_token':result['undo_token']})
        self.assertEqual(len(self.query()['rows'][0]['anchor_record_ids']),2)
        with self.assertRaises(SessionError):self.mutate('mail.tasks.action',{'action':'undo','undo_token':result['undo_token']})

    def test_stop_waiting_and_membership_validation(self):
        self.mail('sent',out=True);self.mail('in');self.scan()
        sent=self.query('waiting')['rows'][0]['anchor_record_ids']
        with self.assertRaises(SessionError):self.mutate('mail.tasks.action',{'action':'dismiss','task':'unanswered','anchor_record_ids':sent})
        result=self.mutate('mail.tasks.action',{'action':'dismiss','task':'waiting','anchor_record_ids':sent})
        self.assertEqual(result['action_label'],'Stop waiting');self.assertEqual(self.query('waiting')['total_count'],0)
        self.mutate('mail.tasks.action',{'action':'undo','undo_token':result['undo_token']})
        self.assertEqual(self.query('waiting')['candidate_count'],1)

    def test_unknown_action_cannot_suppress_evidence(self):
        self.mail('gap',reply='missing');self.scan()
        with self.assertRaises(SessionError):self.mutate('mail.tasks.action',{'action':'dismiss','task':'unanswered','anchor_record_ids':self.query()['rows'][0]['anchor_record_ids']})

    def test_reply_cycle_is_uncertain_not_observed_response(self):
        self.mail('cycle_in',conv='cycle',reply='cycle_out')
        self.mail('cycle_out',out=True,conv='cycle',reply='cycle_in');self.scan()
        self.assertEqual(self.query()['uncertain_count'],1)
        self.assertEqual(self.query('waiting')['uncertain_count'],1)

    def test_duplicate_reply_target_does_not_invent_link(self):
        self.mail('first',conv='same',internet_message_id='<duplicate@example.test>')
        self.mail('second',conv='same',internet_message_id='<duplicate@example.test>')
        self.mail('response',out=True,conv='same',reply='duplicate');self.scan()
        self.assertEqual(self.query()['uncertain_count'],1)
        self.assertEqual(len(self.query()['rows'][0]['anchor_record_ids']),2)

    def test_mixed_supported_and_unknown_in_one_conversation(self):
        self.mail('good',conv='same')
        self.mail('unknown',conv='same',**{'from':{'name':'Unknown sender'}});self.scan()
        result=self.query();row=result['rows'][0]
        self.assertEqual(result['candidate_count'],1)
        self.assertEqual(row['state'],'candidate')
        self.assertEqual(len(row['uncertain_anchor_record_ids']),1)
        self.assertEqual(result['uncertain_anchor_count'],1)

    def test_disposition_must_match_audit_on_reopen(self):
        self.mail('in');self.scan();rid=self.query()['rows'][0]['display_record_id']
        self.mutate('mail.tasks.action',{'action':'dismiss','task':'unanswered','anchor_record_ids':[rid]})
        key=PREFIX+'unanswered:'+rid
        value=json.loads(self.session.km._meta(key));value['actor']='tampered:actor'
        with self.session.km.db:
            self.session.km._setmeta(key,json.dumps(value,sort_keys=True,separators=(',',':')))
        self.assertFalse(self.session.query('system.audit')['workspace']['ok'])
        self.session.close()
        with self.assertRaises(Exception):self.session.open()

    def test_large_conversation_dismiss_and_undo_are_single_atomic_audits(self):
        for index in range(225):self.mail('large-'+str(index),conv='large')
        self.scan();row=self.query()['rows'][0]
        self.assertEqual(len(row['anchor_record_ids']),225)
        self.assertTrue(row['action_supported']);self.assertEqual(row['action_limit'],5000)
        revision=self.session.km.revision()
        result=self.mutate('mail.tasks.action',{'task':'unanswered','action':'dismiss','anchor_record_ids':row['anchor_record_ids']})
        self.assertEqual(self.session.km.revision(),revision+1)
        self.assertEqual(self.query()['total_count'],0)
        self.session.close();self.session.open()  # Audited receipt validation at scale.
        self.assertEqual(self.query()['total_count'],0)
        self.mutate('mail.tasks.action',{'action':'undo','undo_token':result['undo_token']})
        self.assertEqual(self.session.km.revision(),revision+2)
        self.assertEqual(len(self.query()['rows'][0]['anchor_record_ids']),225)
        before=self.session.km.revision()
        with self.assertRaises(SessionError):
            self.mutate('mail.tasks.action',{'task':'unanswered','action':'dismiss',
                'anchor_record_ids':row['anchor_record_ids']+['missing-record']})
        self.assertEqual(self.session.km.revision(),before)
        self.assertEqual(len(self.query()['rows'][0]['anchor_record_ids']),225)

    def test_action_envelope_limit_rejects_without_any_write(self):
        revision=self.session.km.revision()
        with self.assertRaises(SessionError) as raised:
            self.mutate('mail.tasks.action',{'task':'unanswered','action':'dismiss',
                'anchor_record_ids':['bounded-'+str(i) for i in range(MAX_ACTION_ANCHORS+1)]})
        self.assertIn('5,000',str(raised.exception))
        self.assertEqual(self.session.km.revision(),revision)
        self.assertFalse(self.session.km.db.execute('SELECT 1 FROM engine_meta WHERE key GLOB ?',(PREFIX+'*',)).fetchone())

    def test_oversized_conversation_query_discloses_unsupported_action(self):
        self.mail('template');self.scan()
        template=next(iter(_records(self.session.km).values()))
        # A query-boundary fixture tests the advertised action limit without
        # manufacturing thousands of Core evidence/archive files. Real intake,
        # audited writes and Undo are covered by the 225-message case above.
        records={}
        for index in range(MAX_ACTION_ANCHORS+1):
            rid='test_bound_'+str(index)
            records[rid]={**template,'record_id':rid,'properties':{**template['properties'],
                'message_id':rid,'conversation_id':'over-limit'}}
        with patch('o3_km.mail_tasks._records',return_value=records):
            row=self.query()['rows'][0]
        self.assertFalse(row['action_supported'])
        self.assertEqual(row['action_limit'],5000)
        self.assertIn('5,001',row['action_unavailable_reason'])
        self.assertIn('5,000',row['action_unavailable_reason'])

    def test_sort_paging_snapshot_and_validation(self):
        self.mail('new',stamp='2026-10-27T12:00:00Z');self.mail('old',stamp='2026-10-20T12:00:00Z');self.scan()
        page=self.query(page_size=1);self.assertEqual(self.ids(page),{'old'})
        self.assertEqual(self.ids(self.query(page_size=1,cursor=page['next_cursor'])),{'new'})
        self.assertEqual(self.query('all',page_size=1)['rows'][0]['record']['properties']['message_id'],'new')
        self.assertEqual(self.ids(self.query(sort='newest',page_size=1)),{'new'})
        self.mutate('configuration.save',{'week_start':'sunday'})
        with self.assertRaises(SessionError):self.query(page_size=1,cursor=page['next_cursor'])
        for value in (None,'random',1):
            with self.assertRaises(SessionError):self.query(sort=value)
        with self.assertRaises(SessionError):self.query(include_cc='yes')

    def test_search_and_source_time(self):
        self.mail('dated',stamp='2020-01-02T12:00:00Z');self.mail('undated',received_at_utc=None);self.scan()
        row=self.query(search='dated')['rows'][0]
        self.assertEqual(row['source_time'],'2020-01-02T12:00:00+00:00')
        rows=self.query()['rows'];self.assertIsNone(rows[-1]['source_time']);self.assertTrue(rows[-1]['time_warning'])

    def test_persistence_backup_restore_and_source_immutability(self):
        path=self.mail('in');self.scan();original=hashlib.sha256(path.read_bytes()).hexdigest()
        row=self.query()['rows'][0]
        result=self.mutate('mail.tasks.action',{'action':'dismiss','task':'unanswered','anchor_record_ids':row['anchor_record_ids']})
        self.session.close();self.session.open();self.assertEqual(self.query()['total_count'],0)
        self.session.backup(self.root/'backup.zip',self.source,approved=True)
        self.mutate('mail.tasks.action',{'action':'undo','undo_token':result['undo_token']})
        self.session.restore(self.root/'backup.zip',self.source,confirmed=True);self.session.open()
        self.assertEqual(self.query()['total_count'],0)
        self.assertEqual(self.session.km._meta('km_schema_contract'),CATALOG_FINGERPRINT)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),original)
        self.assertTrue(self.session.query('system.audit')['workspace']['ok'])

    def test_new_project_reconciles_retained_mail_when_paused(self):
        self.mail('project',subject='Project [HBR]: Harbor renewal');self.scan()
        save_config(self.state,{'source_root':str(self.source),'paused':True})
        epoch=self.session.km.epoch()
        result=self.mutate('loe.create',{'fields':{'name':'Harbor renewal','kind':'project','reference_code':'HBR'}})
        self.assertEqual(result['project_reconciliation']['state'],'complete')
        self.assertGreater(self.session.km.epoch(),epoch)
        rid=result['loe_id']
        edges=self.session.query('relations.for_record',{'record_type':'LineOfEffort','record_id':rid})['edges']
        self.assertTrue(any(e['predicate']=='associated_with' for e in edges))
        self.assertTrue(read_config(self.state)['paused'])

    def test_project_reconcile_failure_is_retryable(self):
        with patch('o3_km.core_bridge.loes',side_effect=RuntimeError('simulated failure')):
            result=self.mutate('loe.create',{'fields':{'name':'Saved project','kind':'project'}})
        self.assertEqual(result['project_reconciliation']['state'],'pending')
        self.assertEqual(self.session.summary()['project_reconciliation']['state'],'pending')
        retry=self.mutate('loe.reconcile',{})
        self.assertEqual(retry['project_reconciliation']['state'],'complete')

    def test_project_edit_reconciles_and_archive_removes_active_edges(self):
        self.mail('project',subject='Project [HBR]: Harbor renewal');self.scan()
        result=self.mutate('loe.create',{'fields':{'name':'Harbor renewal','kind':'project'}})
        rid=result['loe_id']
        self.mutate('loe.edit',{'record_id':rid,'changes':{'reference_code':'HBR'}})
        self.assertTrue(self.session.query('relations.for_record',{'record_type':'LineOfEffort','record_id':rid})['edges'])
        self.mutate('loe.archive',{'record_id':rid})
        self.assertFalse(self.session.km.db.execute('SELECT 1 FROM relationships WHERE target_id=?',(rid,)).fetchone())

    def test_snapshot_cursor_reused_without_explicit_asof(self):
        self.mail('first');self.mail('second');self.scan()
        result=self.session.query('mail.tasks.query',{'task':'all','page_size':1})
        second=self.session.query('mail.tasks.query',{'task':'all','page_size':1,'cursor':result['next_cursor']})
        self.assertEqual(second['snapshot'],result['snapshot'])


class Candidate6CompatibilityTest(unittest.TestCase):
    def test_windows_and_posix_missing_folder_coverage(self):
        for path,family in [('Mail/Inbox','MailInbox'),('Mail/Sent','MailSent'),
                ('Contacts/Profiles','ContactsProfiles'),('Calendars','CalendarICS'),('Documents','DocumentCorpus')]:
            self.assertEqual(Engine._missing_source_family(path),family)
            self.assertEqual(Engine._missing_source_family(path.replace('/','\\')),family)

    def test_populated_candidate6_copy_unchanged_on_open(self):
        # Locate immutable local evidence, copying before any Engine opens it.
        workspace=Path(__file__).resolve().parents[6]
        baseline=workspace/'review'/'candidate6-full-qc'/'populated_state'
        if not baseline.is_dir():self.skipTest('Populated Candidate 6 evidence is not present')
        original=hashlib.sha256((baseline/'o3.sqlite').read_bytes()).hexdigest()
        with temporary_workspace('c6-compat-') as temporary:
            copied=Path(temporary)/'state';shutil.copytree(baseline,copied)
            with closing(sqlite3.connect(copied/'o3.sqlite')) as db:
                before={table:db.execute('SELECT * FROM '+table+' ORDER BY 1').fetchall()
                    for table in ('ws_definitions','ws_values','ws_audit','engine_meta')}
            session=KMSession(copied,actor='test:compat')
            try:
                session.open();session.query('mail.tasks.query',{'task':'all'});session.query('mail.identity')
                self.assertEqual(session.km._meta('km_schema_contract'),CATALOG_FINGERPRINT)
                for table,rows in before.items():
                    self.assertEqual([tuple(r) for r in session.km.db.execute('SELECT * FROM '+table+' ORDER BY 1')],rows)
                self.assertEqual(session.km.db.execute('PRAGMA user_version').fetchone()[0],4)
            finally:session.close()
        self.assertEqual(hashlib.sha256((baseline/'o3.sqlite').read_bytes()).hexdigest(),original)


if __name__=='__main__':unittest.main()
