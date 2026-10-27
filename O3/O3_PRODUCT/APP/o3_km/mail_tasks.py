"""Evidence-scoped mail tasks, independent of optional legacy rule recipes.

Read computations belong to KM. Dispositions use audited, versioned metadata in
the existing database: no catalog/settings fingerprint change, no Core rewrite,
and no state outside the established backup/restore authority.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import uuid

from o3_core.store import encode, now
from .catalog import email_address
from .evaluation import KMInvalid

TASKS = ('unanswered', 'waiting', 'all')
PREFIX = 'mail_task_disposition_v1:'
MAX_CHAIN = 256
MAX_ACTION_ANCHORS = 5000
REASONS = {
    'to_self_no_reply_found': 'Sent to you. No reply from you was found in the saved mail.',
    'cc_self_no_reply_found': 'You were copied. No reply from you was found in the saved mail.',
    'sent_to_external_no_reply_found': 'You sent this. No later reply was found in the saved mail.',
    'identity_ambiguous': 'Confirm your email addresses so O3 can check for replies.',
    'direction_conflict': 'The saved sender and mail folder disagree about who sent this.',
    'sender_unknown': 'The saved message does not identify its sender clearly.',
    'recipients_unknown': 'The saved message does not identify its recipients clearly.',
    'direction_unknown': 'The saved message does not identify its mail folder clearly.',
    'mailbox_unknown': 'The saved message does not identify its mailbox.',
    'sent_unavailable': 'Your saved Sent mail is unavailable or could not be checked.',
    'inbox_unavailable': 'Your saved Inbox mail is unavailable or could not be checked.',
    'mailbox_coverage_unknown': 'The available folders do not establish coverage for this mailbox.',
    'thread_gap': 'Some reply links are missing or ambiguous in the saved conversation.',
    'thread_limit': 'This reply chain could not be checked completely.',
    'source_time_unknown': 'The original message time is unavailable.',
    'all_saved_mail': 'Based on the saved mail in O3.',
}
FIELDS = ('mailbox_id', 'message_id', 'internet_message_id', 'conversation_id',
          'in_reply_to', 'subject', 'from', 'to', 'cc', 'source_folder',
          'sent_at_utc', 'received_at_utc', 'captured_at_utc', 'importance',
          'has_attachments', 'attachments')


def _address(value):
    if isinstance(value, dict): value = value.get('address')
    try: return email_address(value)
    except (ValueError, TypeError): return None


def _recipients(value):
    if not isinstance(value, list): return set(), False
    parsed = [_address(v) for v in value]
    return set(x for x in parsed if x), all(x is not None for x in parsed)


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (AttributeError, ValueError, TypeError): return None


def _records(service):
    records = {}
    for raw in service.db.execute("SELECT * FROM records WHERE record_type='Email' AND active=1 ORDER BY record_id"):
        p = json.loads(raw['properties_json'])
        p = {k: p[k] for k in FIELDS if k in p}
        a = json.loads(raw['added_json'])
        records[raw['record_id']] = {
            'record_id': raw['record_id'], 'record_type': 'Email', 'scope': raw['scope'],
            'identity_basis': raw['identity_basis'], 'active': True,
            'properties': p, 'additional': a, 'updated_at': raw['updated_at'], 'authority': 'core'}
    return records


def identity(service, records=None):
    records = _records(service) if records is None else records
    settings = service.settings()
    suggestions = {}
    for rid, row in records.items():
        p = row['properties']; mailbox = _text(p.get('mailbox_id'))
        for address, reason in ((_address(mailbox), 'captured_mailbox_address'),
            (_address(p.get('from')) if row['additional'].get('direction') == 'Outgoing' else None,
             'captured_sent_sender')):
            if not address: continue
            item = suggestions.setdefault(address, {'address': address, 'mailbox_ids': set(),
                'evidence_record_ids': [], 'reason': reason, 'requires_confirmation': True})
            if mailbox: item['mailbox_ids'].add(mailbox)
            if len(item['evidence_record_ids']) < 5 and rid not in item['evidence_record_ids']:
                item['evidence_record_ids'].append(rid)
    own = settings['self_addresses']
    return {'configured_addresses': own, 'group_addresses': settings['group_addresses'],
        'suggestions': [{**v, 'mailbox_ids': sorted(v['mailbox_ids'])} for _, v in sorted(suggestions.items())],
        'state': 'ready' if own else 'confirmation_required',
        'message': 'Based on your confirmed email addresses.' if own else
            'Which email addresses are yours? All mail is available while you decide.'}


def validate_dispositions(service):
    """Absent extension metadata is a valid populated Candidate 6 workspace."""
    receipts = {}
    for row in service.db.execute('SELECT key,value FROM engine_meta WHERE key GLOB ?', (PREFIX + '*',)):
        try:
            value = json.loads(row['value'])
            task, rid = row['key'][len(PREFIX):].split(':', 1)
            target = service.engine.store.row(rid)
            if (task not in TASKS[:2] or not target or target['record_type'] != 'Email'
                or set(value) != {'version', 'task', 'anchor_record_id', 'action_id', 'at_utc', 'actor'}
                or type(value['version']) is not int or value['version'] != 1 or value['task'] != task or value['anchor_record_id'] != rid
                or not isinstance(value['action_id'], str) or len(value['action_id']) != 32
                or _stamp(value['at_utc']) is None or not isinstance(value['actor'], str)):
                raise ValueError()
            token = value['action_id']
            if token not in receipts:
                audit = service.db.execute("SELECT after_json FROM ws_audit WHERE operation='mail.tasks.dismiss' AND subject_id=?",
                                           (token,)).fetchone()
                receipts[token] = json.loads(audit[0]) if audit else {}
            if receipts[token].get(row['key']) != value: raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise KMInvalid('INTEGRITY_FAILED', 'Invalid saved mail action') from None


class MailTasks:
    def __init__(self, service):
        self.s = service
        self.records = _records(service)
        self.selves = set(service.settings()['self_addresses'])
        self.coverage = service.coverage()
        self.groups = defaultdict(list)
        self.group_for = {}
        self.parents = defaultdict(set)
        self.edges = {}
        self.gaps = set()
        self.limits = set()
        self.responses = defaultdict(dict)
        self.mailboxes = set()
        for rid, row in self.records.items():
            p = row['properties']; mailbox = _text(p.get('mailbox_id'))
            if mailbox: self.mailboxes.add(mailbox)
            conversation = _text(p.get('conversation_id'))
            # Missing IDs remain independent; grouping never invents a source ID.
            key = (mailbox, conversation, '' if mailbox and conversation else rid)
            self.group_for[rid] = key; self.groups[key].append(rid)
        for edge in service.db.execute("SELECT source_id,target_id,owner,evidence_json FROM relationships WHERE predicate='replies_to'"):
            child, parent = edge['source_id'], edge['target_id']
            if child not in self.records or parent not in self.records: continue
            cm = _text(self.records[child]['properties'].get('mailbox_id'))
            pm = _text(self.records[parent]['properties'].get('mailbox_id'))
            if not cm or cm.casefold() != pm.casefold():
                self.gaps.add(child); continue
            self.parents[child].add(parent)
            self.edges[(child, parent)] = {'source_id': child, 'predicate': 'replies_to',
                'target_id': parent, 'authority': 'core', 'owner': edge['owner']}
        for rid, row in self.records.items():
            if _text(row['properties'].get('in_reply_to')) and not self.parents[rid]: self.gaps.add(rid)
            if len(self.parents[rid]) > 1: self.gaps.add(rid)
        # One-parent ancestry is bounded. A later date alone never closes a task.
        for child, row in self.records.items():
            actor, _ = self.actor(row)
            seen = {child}; node = child; path = []; valid = True
            for _ in range(MAX_CHAIN):
                parents = self.parents[node]
                if not parents: break
                if len(parents) != 1:
                    self.gaps.update(seen); valid = False; break
                parent = next(iter(parents))
                if parent in seen:
                    self.gaps.update(seen); valid = False; break
                seen.add(parent); path.append(self.edges[(node, parent)])
                node = parent
            else: self.limits.update(seen); valid = False
            if valid and actor in ('self', 'external'):
                for depth, edge in enumerate(path):
                    self.responses[edge['target_id']].setdefault(actor,
                        {'record_id': child, 'actor': actor, 'ancestry_length': depth + 1})
        self.group_gaps = {self.group_for[rid] for rid in self.gaps}
        self.group_limits = {self.group_for[rid] for rid in self.limits}

    def actor(self, row):
        if not self.selves: return None, 'identity_ambiguous'
        direction = row['additional'].get('direction')
        sender = _address(row['properties'].get('from'))
        if not sender: return None, 'sender_unknown'
        if direction not in ('Incoming', 'Outgoing'): return None, 'direction_unknown'
        own = sender in self.selves
        if (direction == 'Incoming' and own) or (direction == 'Outgoing' and not own):
            return None, 'direction_conflict'
        return ('self' if own else 'external'), None

    def classify(self, rid, task, include_cc):
        row = self.records[rid]; p = row['properties']; direction = row['additional'].get('direction')
        if task == 'unanswered' and direction == 'Outgoing': return None
        if task == 'waiting' and direction == 'Incoming': return None
        actor, failure = self.actor(row)
        to, to_valid = _recipients(p.get('to')); cc, cc_valid = _recipients(p.get('cc'))
        reason = 'to_self_no_reply_found' if task == 'unanswered' else 'sent_to_external_no_reply_found'
        if failure: return ('uncertain', failure, [])
        if task == 'unanswered':
            if actor != 'external': return None
            if to & self.selves: pass
            elif include_cc and cc & self.selves: reason = 'cc_self_no_reply_found'
            elif not to_valid or (include_cc and not cc_valid): return ('uncertain', 'recipients_unknown', [])
            else: return None
        else:
            if actor != 'self': return None
            if (to | cc) - self.selves: pass
            elif not to_valid or not cc_valid: return ('uncertain', 'recipients_unknown', [])
            else: return None
        expected_actor = 'self' if task == 'unanswered' else 'external'
        if expected_actor in self.responses[rid]: return None
        key = self.group_for[rid]
        if not key[0]: return ('uncertain', 'mailbox_unknown', [])
        if key in self.group_gaps: return ('uncertain', 'thread_gap', [])
        if key in self.group_limits: return ('uncertain', 'thread_limit', [])
        family = 'MailSent' if task == 'unanswered' else 'MailInbox'
        if self.coverage.get(family) != 'complete':
            return ('uncertain', 'sent_unavailable' if task == 'unanswered' else 'inbox_unavailable', [])
        # Coverage is family-wide, not a per-mailbox or remote-history claim.
        if len(self.mailboxes) > 1: return ('uncertain', 'mailbox_coverage_unknown', [])
        return ('candidate', reason, [])

    def time(self, rid):
        row = self.records[rid]; p = row['properties']
        field = 'sent_at_utc' if row['additional'].get('direction') == 'Outgoing' else 'received_at_utc'
        return _stamp(p.get(field))

    def rows(self, task, include_cc=False, include_dismissed=False):
        grouped = defaultdict(list)
        for rid in self.records:
            result = ('all', 'all_saved_mail', []) if task == 'all' else self.classify(rid, task, include_cc)
            if result is None: continue
            if task != 'all' and not include_dismissed and self.s._meta(PREFIX + task + ':' + rid): continue
            grouped[self.group_for[rid]].append((rid, *result))
        rows = []
        for key, anchors in grouped.items():
            supported = [a for a in anchors if a[1] != 'uncertain']
            # Mixed conversations stay useful, and retain an explicit uncertain subset.
            chosen = supported or anchors
            ordered = sorted(chosen, key=lambda x: (self.time(x[0]) or datetime.min.replace(tzinfo=timezone.utc), x[0]))
            display = ordered[-1][0]
            reasons = list(dict.fromkeys(a[2] for a in chosen))
            uncertain = [a[0] for a in anchors if a[1] == 'uncertain']
            anchor_ids = [a[0] for a in chosen]
            task_key = hashlib.sha256(encode([task, key]).encode()).hexdigest()
            rows.append({'task_key': task_key, 'task': task,
                'conversation_key': {'mailbox_id': key[0] or None, 'conversation_id': key[1] or None,
                    'standalone_record_id': key[2] or None},
                'anchor_record_ids': anchor_ids, 'uncertain_anchor_record_ids': uncertain,
                'display_record_id': display, 'record': self.records[display],
                'state': 'all' if task == 'all' else 'candidate' if supported else 'uncertain',
                'reason_codes': reasons, 'reason': REASONS[reasons[0]],
                'evidence': [{'record_id': rid, 'authority': 'core', 'fields': ['from', 'to', 'cc'],
                    'reply_query': 'verified_mailbox_scoped_ancestry'} for rid in anchor_ids],
                'message_count': len(self.groups[key]), 'additional_anchor_count': len(anchor_ids) - 1,
                'action_limit': MAX_ACTION_ANCHORS,
                'action_supported': bool(task != 'all' and supported and len(anchor_ids) <= MAX_ACTION_ANCHORS),
                'action_unavailable_reason': (f'This conversation has {len(anchor_ids):,} unresolved messages. '
                    f'One choice can cover up to {MAX_ACTION_ANCHORS:,} messages at once.')
                    if task != 'all' and len(anchor_ids) > MAX_ACTION_ANCHORS else None,
                'source_time': self.time(display).isoformat() if self.time(display) else None,
                'time_warning': None if self.time(display) else REASONS['source_time_unknown']})
        return rows


def query(service, params, as_of):
    allowed = {'task', 'include_cc', 'page_size', 'cursor', 'search', 'mailbox_id', 'conversation_id', 'sort'}
    if set(params) - allowed: raise KMInvalid('INVALID_VALUE', 'Unsupported mail view option')
    task = params.get('task', 'unanswered')
    if task not in TASKS: raise KMInvalid('INVALID_VALUE', 'Unknown mail view')
    include_cc = params.get('include_cc', False)
    if type(include_cc) is not bool: raise KMInvalid('INVALID_TYPE', 'Include copied messages must be Boolean')
    sort = params.get('sort', 'newest' if task == 'all' else 'oldest')
    if sort not in ('oldest', 'newest'): raise KMInvalid('INVALID_VALUE', 'Choose oldest or newest first')
    for field in ('search', 'mailbox_id', 'conversation_id'):
        if field in params and (not isinstance(params[field], str) or len(params[field]) > 500):
            raise KMInvalid('INVALID_VALUE', 'Invalid mail filter')
    service._page_request(params, as_of, 'mail.tasks.query', sort)
    model = MailTasks(service)
    rows = model.rows(task, include_cc)
    search = params.get('search', '').strip().casefold()
    filtered = []
    for row in rows:
        key = row['conversation_key']
        if any(params.get(field) and key[field] != params[field] for field in ('mailbox_id', 'conversation_id')): continue
        if search and not any(search in encode(model.records[rid]['properties']).casefold()
                              for rid in model.groups[model.group_for[row['display_record_id']]]): continue
        filtered.append(row)
    # Unknown time is explicit and sorts after dated rows, not as capture time.
    dated = [r for r in filtered if r['source_time']]
    undated = [r for r in filtered if not r['source_time']]
    dated.sort(key=lambda r: (r['source_time'], r['task_key']), reverse=sort == 'newest')
    ordered = dated + sorted(undated, key=lambda r: r['task_key'])
    ordered.sort(key=lambda r: r['state'] == 'uncertain')
    page = service._page(ordered, params, as_of, 'mail.tasks.query', sort)
    uncertain_count = sum(r['state'] == 'uncertain' for r in filtered)
    return {'kind': 'mail_tasks', 'task': task, 'state': 'available', **page,
        'candidate_count': sum(r['state'] == 'candidate' for r in filtered),
        'uncertain_count': uncertain_count,
        'uncertain_anchor_count': sum(len(r['uncertain_anchor_record_ids']) for r in filtered),
        'identity': identity(service, model.records), 'coverage': service.coverage(),
        'remote_freshness': 'unknown', 'as_of': as_of.isoformat(),
        'freshness': 'Based on the saved mail in O3. Newer mail may not be included.',
        'coverage_scope': 'Local input folders only; available folders do not establish complete mailbox history.'}


def action(service, params, expected, as_of):
    operation = params.get('action')
    if operation == 'undo':
        if set(params) != {'action', 'undo_token'}: raise KMInvalid('INVALID_VALUE', 'Undo requires its action token')
        token = params['undo_token']
        if not isinstance(token, str) or len(token) != 32: raise KMInvalid('INVALID_VALUE', 'Invalid undo token')
        audit = service.db.execute("SELECT before_json,after_json FROM ws_audit WHERE operation='mail.tasks.dismiss' AND subject_id=?", (token,)).fetchone()
        if not audit: raise KMInvalid('UNKNOWN_RECORD', 'This mail action was not found')
        before, after = json.loads(audit['before_json']), json.loads(audit['after_json'])
        def undo():
            for key, value in after.items():
                if service._meta(key) != encode(value):
                    raise KMInvalid('REVISION_CONFLICT', 'This mail action has already changed')
            for key, value in before.items():
                if value is None: service.db.execute('DELETE FROM engine_meta WHERE key=?', (key,))
                else: service._setmeta(key, encode(value))
            return after, before, {'core_ids': [v['anchor_record_id'] for v in after.values()], 'undo_token': None}
        return service._commit('mail.tasks.undo', 'mail_task', token, expected, undo)
    if operation != 'dismiss' or set(params) - {'action', 'task', 'anchor_record_ids', 'include_cc'}:
        raise KMInvalid('INVALID_VALUE', 'Unknown mail action')
    task = params.get('task'); ids = params.get('anchor_record_ids'); include_cc = params.get('include_cc', False)
    if task not in TASKS[:2] or type(include_cc) is not bool:
        raise KMInvalid('INVALID_VALUE', 'Select an unanswered or waiting mail view')
    if (not isinstance(ids, list) or not 1 <= len(ids) <= MAX_ACTION_ANCHORS or
        any(not isinstance(rid, str) or not 1 <= len(rid) <= 512 for rid in ids) or len(set(ids)) != len(ids)):
        raise KMInvalid('INVALID_VALUE', f'Select 1 to {MAX_ACTION_ANCHORS:,} distinct mail items')
    token = uuid.uuid4().hex
    def dismiss():
        model = MailTasks(service)
        eligible = {rid for row in model.rows(task, include_cc) for rid in row['anchor_record_ids']
                    if row['state'] == 'candidate'}
        if set(ids) - eligible:
            raise KMInvalid('REVISION_CONFLICT', 'Mail changed or could not be checked; refresh before applying this action')
        before = {}; after = {}
        for rid in ids:
            key = PREFIX + task + ':' + rid
            raw = service._meta(key); before[key] = json.loads(raw) if raw else None
            after[key] = {'version': 1, 'task': task, 'anchor_record_id': rid,
                          'action_id': token, 'at_utc': now(), 'actor': service.actor}
            service._setmeta(key, encode(after[key]))
        return before, after, {'core_ids': ids, 'undo_token': token, 'task': task,
            'action_label': 'No reply needed' if task == 'unanswered' else 'Stop waiting'}
    return service._commit('mail.tasks.dismiss', 'mail_task', token, expected, dismiss)
