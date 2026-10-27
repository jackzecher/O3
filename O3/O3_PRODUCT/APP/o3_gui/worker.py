"""One Qt worker owns one Core Engine and KMService; no UI-thread database work."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot
from o3_gui.km_session import KMSession
from o3_km import verify_backup


class EngineWorker(QObject):
    ready = Signal(object)
    maintenance_required = Signal(object)
    result = Signal(str, object)
    failed = Signal(str, str)
    closed = Signal()

    def __init__(self, state: Path):
        super().__init__()
        self.state = Path(state)
        self.session = None

    @property
    def engine(self):
        return self.session.engine if self.session is not None else None

    @Slot()
    def initialize(self):
        try:
            # Created here, never on the Qt main thread.
            self.session = KMSession(self.state)
            data = self.session.open()
            if data.get('maintenance_required'): self.maintenance_required.emit(data)
            else: self.ready.emit(data)
        except Exception as exc:
            self.failed.emit('initialize', str(exc))

    @Slot(str, object)
    def run(self, op: str, payload: object):
        args = payload if isinstance(payload, dict) else {}
        try:
            if self.session is None: raise RuntimeError('STATE_NOT_READY: session is not initialized')
            if op == 'km':
                try: response = self.session.call(args['request'])
                except Exception as exc:
                    response = {'ok': False, 'error': {'code': getattr(exc, 'code', 'STATE_NOT_READY'),
                                'message': 'Workspace request could not run; inspect Sources & Health'}}
                self.result.emit('km', {'token': args['token'], 'response': response})
                return
            if op == 'scan': data = self.session.scan(Path(args['source']))
            elif op == 'list': data = self.session.listing(args)
            elif op == 'detail': data = self.session.detail(args['id'], args.get('kind'))
            elif op == 'content': data = self.session.content(args['id'])
            elif op == 'reading': data = self.session.reading(args['id'], args.get('kind'))
            elif op == 'home': data = self.session.home(args)
            elif op == 'neighborhood': data = self.session.neighborhood(args)
            elif op == 'overview': data = self.session.summary()
            elif op == 'preview': data = self.session.preview(args['id'], args.get('source_sha'))
            elif op == 'audit':
                audit = self.session.query('system.audit')
                data = {'rdf': audit['rdf'], 'provenance': audit['core_provenance'],
                        'workspace': audit['workspace'], 'sqlite_quick_check': audit['sqlite_quick_check']}
            elif op == 'rules': data = self.session.query('registry.rules')['core_rules']
            elif op == 'backup':
                data = self.session.backup(Path(args['destination']), Path(args['source']), approved=args.get('approved') is True)
            elif op == 'verify_backup': data = verify_backup(Path(args['path']))
            elif op == 'export_rdf':
                data = self.session.export(Path(args['path']), Path(args['source']) if args.get('source') else None)
            elif op == 'migrate':
                data = self.session.migrate(Path(args['source']), Path(args['backup']),
                           approved=args.get('approved') is True, confirmed=args.get('confirmed') is True)
            elif op == 'restore':
                data = self.session.restore(Path(args['backup']), Path(args['source']), confirmed=args.get('confirmed') is True)
            elif op == 'reopen': data = self.session.open()
            else: raise ValueError('Unknown worker operation')
            if op in ('detail', 'content', 'preview', 'reading', 'home', 'neighborhood') and 'request_id' in args:
                data = {**data, 'request_id': args['request_id']}
            self.result.emit(op, data)
        except Exception as exc:
            if 'request_id' in args and op in ('list', 'detail', 'content', 'preview', 'reading', 'home', 'neighborhood'):
                self.result.emit(op, {'request_id': args['request_id'], 'id': args.get('id'),
                                     'read_error': str(exc), 'error_code': getattr(exc, 'code', 'READ_FAILED')})
            else:
                self.failed.emit(op, str(exc))

    @Slot()
    def close_engine(self):
        try:
            if self.session: self.session.close()
        finally:
            self.closed.emit()
