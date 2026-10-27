"""Complete synthetic review example. All addresses use reserved example.test."""
from pathlib import Path
import json


def create_example(base):
    from seed import seed
    from o3_gui.km_session import KMSession
    from o3_gui.logic import read_config, save_config
    base = Path(base)
    state = seed(base)
    source = base / 'O3Data'
    sent = source / 'Mail/Sent'
    sent.mkdir(exist_ok=True)
    first = json.loads(next((source / 'Mail/Inbox').glob('*.json')).read_text())
    own = {'name': 'Alex Morgan', 'address': 'alex.morgan@example.test'}
    other = {'name': 'Maya Chen', 'address': 'maya.chen@example.test'}
    outgoing = {'schema_version': 'em-raw-v1', 'mailbox_id': 'synthetic-alex',
        'message_id': 'review-waiting', 'internet_message_id': '<review-waiting@example.test>',
        'conversation_id': 'review-next-steps', 'subject': 'Harbor Readiness · next steps for Thursday',
        'source_folder': 'Sent', 'from': own, 'to': [other], 'cc': [],
        'sent_at_utc': '2026-10-26T15:00:00Z', 'captured_at_utc': '2026-10-27T12:00:00Z',
        'body_text': 'Hi Maya,\n\nCould you confirm the next steps for our Harbor Readiness review?\n\nThanks,\nAlex'}
    (sent / 'review-waiting.json').write_text(json.dumps(outgoing), encoding='utf-8')
    reply = {**outgoing, 'message_id': 'review-reply',
        'internet_message_id': '<review-reply@example.test>',
        'conversation_id': first['conversation_id'], 'in_reply_to': first['internet_message_id'],
        'subject': 'Re: ' + first['subject'], 'to': [first['from']],
        'body_text': 'Thanks for sending this through. I have added my notes to the Harbor Readiness review.\n\nAlex'}
    (sent / 'review-reply.json').write_text(json.dumps(reply), encoding='utf-8')
    session = KMSession(state, actor='synthetic:upgrade-review')
    try:
        session.open()
        result = session.scan(source)
    finally:
        session.close()
    config = read_config(state)
    config['last_capture_check'] = result['checked_utc']
    config['last_capture_result'] = {key: result.get(key) for key in ('complete', 'coverage', 'errors', 'pending_removals')}
    config['synthetic_qualification'] = True
    save_config(state, config)
    return state
