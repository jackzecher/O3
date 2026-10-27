"""Everyday mail presentation. All reply decisions and writes belong to KM."""
from __future__ import annotations
import copy
import uuid
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QDialog, QComboBox, QCheckBox, QLineEdit, QMenu, QScrollArea, QFrame)
from .ui import text, btn, RecordDelegate

TASKS = {'unanswered': 'Unanswered', 'waiting': 'Waiting for replies', 'all': 'All mail'}
SUBTITLES = {'unanswered': 'Mail to you with no reply from you found.',
             'waiting': 'Mail you sent with no later reply found.',
             'all': 'Your saved conversations, together in one place.'}


class MailWorkspace(QWidget):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.task = 'unanswered'
        self.serial = 0
        self.rows = {}
        self.cursor = None
        self.previous = []
        self.next_cursor = None
        self.payload = {}
        self.undo_token = None
        self.ready = False
        self.options = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        heading.addWidget(text('Mail', 'title'), 1)
        self.check_button=btn('Check for updates',host.scan_sources,kind='secondary');heading.addWidget(self.check_button)
        layout.addLayout(heading)
        self.subtitle = text('', 'muted', True)
        layout.addWidget(self.subtitle)
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self.tabs = {}
        for task, label in TASKS.items():
            button = btn(label, lambda checked=False, value=task: host.open_mail(value), kind='secondary')
            button.setCheckable(True)
            self.tabs[task] = button
            tabs.addWidget(button)
        tabs.addStretch()
        layout.addLayout(tabs)
        options = QHBoxLayout()
        self.result_count = text('', 'small', True)
        options.addWidget(self.result_count, 1)
        self.personalize_button=btn('Personalize',self.customize,'sliders','link');options.addWidget(self.personalize_button)
        self.saved_button = btn('Saved views', self.saved_views, kind='link')
        options.addWidget(self.saved_button)
        layout.addLayout(options)
        self.setup = QWidget()
        setup_layout = QVBoxLayout(self.setup)
        setup_layout.setContentsMargins(18, 16, 18, 16)
        setup_layout.addWidget(text('Bring your mail into O3', 'section'))
        setup_layout.addWidget(text('Choose the folder containing your O3 mail export. Your original files stay as they are. O3 checks these saved files; it does not connect to your email account.', 'muted', True))
        setup_layout.addWidget(btn('Choose mail folder', host.choose_source, 'sources', 'primary'), 0, Qt.AlignLeft)
        layout.addWidget(self.setup)
        self.identity = QWidget()
        identity_layout = QVBoxLayout(self.identity)
        identity_layout.setContentsMargins(0, 0, 0, 0)
        self.identity_message = text('', 'muted', True)
        identity_layout.addWidget(self.identity_message)
        identity_layout.addWidget(btn('Your email addresses', host.setup_review, kind='link'), 0, Qt.AlignLeft)
        layout.addWidget(self.identity)
        self.listing = QListWidget()
        self.listing.setAccessibleName('Mail conversations. Use arrow keys to choose a conversation and Enter to read it.')
        self.listing.setItemDelegate(RecordDelegate(self.listing))
        self.listing.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.listing.setMouseTracking(True)
        self.listing.itemClicked.connect(self.open_item)
        self.listing.itemActivated.connect(self.open_item)
        self.listing.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.listing, 1)
        self.empty = text('', 'muted', True)
        layout.addWidget(self.empty)
        self.coverage = text('Based on the saved mail in O3. Newer mail may not be included.', 'small', True)
        layout.addWidget(self.coverage)
        bottom = QHBoxLayout()
        self.previous_button = btn('Previous', lambda: self.page_back(), kind='link')
        self.next_button = btn('Next', lambda: self.page_next(), kind='link')
        bottom.addWidget(self.previous_button)
        bottom.addWidget(self.next_button)
        bottom.addStretch()
        self.why_button = btn('Why is this here?', self.explain, kind='link')
        self.action_button = btn('No reply needed', self.dismiss, kind='secondary')
        bottom.addWidget(self.why_button)
        bottom.addWidget(self.action_button)
        layout.addLayout(bottom)
        undo = QHBoxLayout()
        self.action_notice = text('', 'small', True)
        undo.addWidget(self.action_notice, 1)
        self.undo_button = btn('Undo', self.undo, kind='link')
        self.undo_button.hide()
        undo.addWidget(self.undo_button)
        layout.addLayout(undo)
        self.selection_changed()
        self.update_journey()

    def update_journey(self):
        has_source=bool(self.host.config.get('source_root'))
        self.setup.setVisible(not has_source);self.check_button.setVisible(has_source)
        for button in self.tabs.values():button.setVisible(has_source)
        for widget in (self.result_count,self.personalize_button,self.saved_button,self.previous_button,self.next_button,self.why_button,self.coverage):widget.setVisible(has_source)
        self.action_button.setVisible(has_source and self.task!='all')
        self.action_notice.setVisible(has_source and bool(self.action_notice.text()))
        self.undo_button.setVisible(has_source and bool(self.undo_token))
        if not has_source:
            self.subtitle.setText('A clear place for your mail, people and projects.')
            self.identity.hide();self.empty.hide();self.listing.hide()

    def load(self, route, reset=True):
        self.task = route['view'].split(':', 1)[-1]
        if self.task not in TASKS:
            self.task = 'unanswered'
        self.options = copy.deepcopy(route.get('parameters') or {})
        if reset:
            self.cursor = None
            self.previous = []
        self.restore_page_index=route.get('page_index',0) if reset else len(self.previous)
        self.ready = False
        self.serial += 1
        serial, generation = self.serial, self.host.route_generation
        self.subtitle.setText(SUBTITLES[self.task])
        for task, button in self.tabs.items():
            button.setChecked(task == self.task)
        self.setup.setVisible(not bool(self.host.config.get('source_root')))
        self.result_count.setText('Checking your saved mail…')
        self.empty.hide()
        self.listing.clear()
        self.rows = {}
        self.selection_changed()
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.update_journey()
        params = {'task': self.task, 'include_cc': self.options.get('include_cc', False),
                  'sort': self.options.get('sort', 'newest' if self.task == 'all' else 'oldest'),
                  'page_size': 100}
        if route.get('search'):
            params['search'] = route['search']
        if self.cursor:
            params['cursor'] = self.cursor

        def loaded(response):
            if serial != self.serial or generation != self.host.route_generation or self.host.page != 'mail':
                return
            if not response.get('ok'):
                self.result_count.setText('Mail could not be checked')
                self.empty.setText('Your saved mail is still here. Try Check for updates, or open Your folders in Settings. ' + response.get('error', {}).get('message', ''))
                self.empty.show()
                return
            self.paint(response['result'], route)
        self.host.km.request('mail.tasks.query', params, loaded, owner=self)

    def paint(self, data, route):
        self.payload = data
        self.next_cursor = data.get('next_cursor')
        if self.next_cursor and len(self.previous)<getattr(self,'restore_page_index',0):
            self.previous.append(self.cursor);self.cursor=self.next_cursor
            target=self.restore_page_index;self.load(route,reset=False);self.restore_page_index=target;return
        self.listing.clear()
        self.rows = {}
        uncertain_heading = False
        for row in data.get('rows', []):
            if row.get('state') == 'uncertain' and not uncertain_heading:
                header = QListWidgetItem("Couldn't check")
                header.setData(Qt.UserRole+1,{'title':"Couldn't check",'person':'Some saved information is missing.','kind':'','capture_label':''});header.setFlags(Qt.ItemIsEnabled)
                self.listing.addItem(header)
                uncertain_heading = True
            record = row.get('record') or {}
            props = record.get('properties') or {}
            rid = row['display_record_id']
            self.rows[rid] = row
            self.host.record_kinds[rid] = 'Email'
            sender = props.get('from') or {}
            sender = sender.get('name') or sender.get('address', '') if isinstance(sender, dict) else str(sender)
            stamp = row.get('source_time')
            title = props.get('subject') or record.get('label') or 'Message without a subject'
            reason = row.get('reason') or ''
            if row.get('additional_anchor_count'):reason+=' · '+str(row['additional_anchor_count']+1)+' messages to consider'
            if row.get('time_warning'):reason+=' · Message date unavailable'
            item = QListWidgetItem(title + '. ' + sender + '. ' + reason)
            item.setData(Qt.UserRole, rid)
            item.setData(Qt.UserRole + 1, {'title': title, 'kind': 'Mail', 'person': sender,
                                         'capture_label': self.host.local_stamp(stamp, True),
                                         'reason': reason, 'state': row.get('state')})
            item.setToolTip(title + '\n' + sender + '\n' + self.host.local_stamp(stamp) + '\n' + reason)
            self.listing.addItem(item)
        identity = data.get('identity') or {}
        needs_identity = identity.get('state') == 'confirmation_required'
        self.identity.setVisible(needs_identity)
        self.identity_message.setText('Which email addresses are yours? Confirm them so O3 can check for replies. All mail remains available.')
        total, uncertain = data.get('total_count', len(self.rows)), data.get('uncertain_count', 0)
        unchecked=data.get('uncertain_anchor_count',0)
        self.result_count.setText(str(total) + (' conversation' if total == 1 else ' conversations') + (' · ' + str(uncertain) + " couldn't be checked" if uncertain else ' · Some messages could not be checked' if unchecked else ''))
        self.empty.setText('No conversations match these choices.' if self.rows == {} and self.options else
                           'No saved mail yet. Choose your mail folder to get started.' if self.task == 'all' else
                           'No matching conversations found in your saved mail.' + (' Confirm your email address above to check replies.' if needs_identity else ''))
        self.empty.setVisible(not self.rows)
        self.listing.setVisible(bool(self.rows))
        self.previous_button.setEnabled(bool(self.previous))
        self.next_button.setEnabled(bool(self.next_cursor))
        self.ready = True
        wanted = (route.get('preview') or {}).get('record_id')
        for i in range(self.listing.count()):
            if self.listing.item(i).data(Qt.UserRole) == wanted:
                self.listing.setCurrentRow(i)
                break
        serial = self.serial
        QTimer.singleShot(0, lambda: self.listing.verticalScrollBar().setValue(route.get('scroll', 0)) if serial == self.serial else None)
        self.selection_changed()
        self.update_journey()

    def selected_row(self):
        item = self.listing.currentItem()
        return self.rows.get(item.data(Qt.UserRole)) if item else None

    def selection_changed(self):
        row = self.selected_row()
        self.why_button.setEnabled(bool(row))
        self.action_button.setText('Stop waiting' if self.task == 'waiting' else 'No reply needed')
        self.action_button.setVisible(self.task != 'all')
        self.action_button.setEnabled(bool(row and row.get('state') == 'candidate' and row.get('action_supported',True)))
        self.action_button.setToolTip(row.get('action_unavailable_reason') or '' if row else '')

    def open_item(self, item):
        rid = item.data(Qt.UserRole) if item else None
        if rid:
            self.host.open_record(rid, 'Email')

    def explain(self, row=None):
        row = row or self.selected_row()
        if not row:
            return
        message = row.get('reason', '') + '\n\n'
        if row.get('action_unavailable_reason'):message+=row['action_unavailable_reason']+'\n\n'
        message += 'This check uses the saved mail in O3. It does not establish that anyone is obliged to reply, or that your live mailbox has no newer messages.'
        if row.get('additional_anchor_count'):message+='This conversation has '+str(row['additional_anchor_count']+1)+' messages to consider. No reply needed or Stop waiting applies to all of those messages.\n\n'
        message += '\n\n' + str(row.get('message_count', 1)) + ' saved messages in this conversation.'
        if row.get('uncertain_anchor_record_ids'):message += '\nSome other messages in this conversation could not be checked. This choice only applies to the messages whose reply status could be checked.'
        self.host.show_information('Why is this here?', message)

    def dismiss(self, row=None):
        row = row or self.selected_row()
        if not row or row.get('state') != 'candidate' or self.task == 'all' or not row.get('action_supported',True):
            return
        self.action_button.setEnabled(False)
        task=self.task;include_cc=self.options.get('include_cc',False)
        def done(response):
            if response.get('ok'):
                self.undo_token = response['result'].get('undo_token')
                self.action_notice.setText('Removed from '+TASKS[task]+'. Nothing was sent. A new message can bring it back.')
                row['state']='dismissed'
                self.undo_button.setVisible(bool(self.undo_token))
            else:
                self.action_notice.setText('Your choice was not saved. ' + response.get('error', {}).get('message', 'Please try again.'))
                self.selection_changed()
                if self.host.page!='mail':self.host.show_information('Choice not saved',self.action_notice.text(),warning=True)
        self.host.km.request('mail.tasks.action', {'task': task, 'action': 'dismiss',
                             'anchor_record_ids': row['anchor_record_ids'], 'include_cc': include_cc}, done,
                             expected=self.host.km.revision, owner=self)

    def undo(self):
        if not self.undo_token:
            return
        def done(response):
            if response.get('ok'):
                self.action_notice.setText('Your choice was undone.')
                self.undo_token = None
                self.undo_button.hide()
            else:
                self.action_notice.setText('Could not undo. ' + response.get('error', {}).get('message', 'Try again.'))
                if self.host.page!='mail':self.host.show_information('Could not undo',self.action_notice.text(),warning=True)
        self.host.km.request('mail.tasks.action', {'action': 'undo', 'undo_token': self.undo_token},
                             done, expected=self.host.km.revision, owner=self)

    def page_next(self):
        if self.next_cursor:
            self.previous.append(self.cursor)
            self.cursor = self.next_cursor
            self.load(self.host.navigation.current, reset=False)

    def page_back(self):
        if self.previous:
            self.cursor = self.previous.pop()
            self.load(self.host.navigation.current, reset=False)

    def customize(self):
        dialog = QDialog(self.host)
        dialog.setWindowTitle('Make this view yours')
        dialog.resize(600, 660)
        outer=QVBoxLayout(dialog);outer.setContentsMargins(24,24,24,20)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.NoFrame)
        content=QWidget();layout=QVBoxLayout(content);layout.setContentsMargins(0,0,0,0);scroll.setWidget(content);outer.addWidget(scroll,1)
        layout.addWidget(text('Make this view yours', 'title', True))
        layout.addWidget(text('Try your choices against the mail you already have. Your original files and the default views stay unchanged.', 'muted', True))
        include = QCheckBox("Include messages where I'm copied")
        include.setChecked(self.options.get('include_cc', False))
        include.setVisible(self.task == 'unanswered')
        layout.addWidget(include)
        layout.addWidget(text('Sort conversations', 'small'))
        sort = QComboBox();sort.setAccessibleName('Sort conversations')
        sort.addItem('Longest waiting first' if self.task != 'all' else 'Oldest first', 'oldest')
        sort.addItem('Newest first', 'newest')
        sort.setCurrentIndex(max(0, sort.findData(self.options.get('sort', 'newest' if self.task == 'all' else 'oldest'))))
        layout.addWidget(sort)
        saved_id=self.options.get('_saved_view_id')
        existing=next((v for v in self.host.config.get('alpha3',{}).get('mail_views',[]) if v.get('id')==saved_id),None) if saved_id else None
        name = QLineEdit(existing.get('name','') if existing else '')
        name.setPlaceholderText('Name your saved view (optional)')
        name.setAccessibleName('Name your saved view')
        layout.addWidget(name)
        preview = text('Preview to see how many conversations match.', 'muted', True)
        layout.addWidget(preview)
        def values():
            return {'include_cc': include.isChecked(), 'sort': sort.currentData()}
        previewed=[None];preview_serial=[0]
        def changed(*_):
            previewed[0]=None;preview_serial[0]+=1;preview.setText('Preview again to check these choices.');save_new.setEnabled(False);save_changes.setEnabled(False)
        include.toggled.connect(changed);sort.currentIndexChanged.connect(changed)
        def inspect():
            selected=values();preview_serial[0]+=1;ticket=preview_serial[0]
            params = {'task': self.task, **values(), 'page_size': 1}
            def result(response):
                if ticket!=preview_serial[0] or selected!=values():return
                if response.get('ok'):
                    previewed[0]=selected;save_new.setEnabled(True);save_changes.setEnabled(bool(existing))
                    data = response['result']
                    preview.setText(str(data.get('total_count', 0)) + ' conversations match. ' + str(data.get('uncertain_count', 0)) + " couldn't be checked.")
                else:
                    preview.setText('Preview unavailable. ' + response.get('error', {}).get('message', 'Please retry.'))
            self.host.km.request('mail.tasks.query', params, result, owner=dialog)
        def apply():
            self.host.open_mail(self.task, values())
            dialog.accept()
        def save(update=False):
            if previewed[0]!=values():
                preview.setText('Preview your current choices before saving.');return
            label = name.text().strip()
            if not label:
                preview.setText('Give this view a name so you can find it again.')
                name.setFocus()
                return
            saved = self.host.config.setdefault('alpha3', {}).setdefault('mail_views', [])
            if len(saved) >= 32 and not update:
                preview.setText('You already have 32 saved mail views. Remove an unused view first.')
                return
            before=copy.deepcopy(saved)
            view={'id':existing.get('id') if update and existing else uuid.uuid4().hex,'name':label[:80],'task':self.task,'options':values()}
            if update and existing:
                index=next((i for i,v in enumerate(saved) if v.get('id')==saved_id),None)
                if index is None:preview.setText('This saved view changed. Close and reopen it before saving.');return
                saved[index]=view
            else:saved.append(view)
            if not self.host.persist_preferences():
                self.host.config['alpha3']['mail_views']=before
                preview.setText('Could not save this view. Your choices are still here; try again.')
                return
            self.host.open_mail(self.task,{**values(),'_saved_view_id':view['id']});dialog.accept()
        def reset():
            include.setChecked(False)
            sort.setCurrentIndex(1 if self.task == 'all' else 0)
            preview.setText('Default choices restored here. Choose Apply to use them.')
        layout.addWidget(btn('Preview matching mail', inspect, kind='secondary'))
        layout.addWidget(btn('Restore default choices', reset, kind='link'))
        layout.addStretch()
        actions = QHBoxLayout()
        actions.addWidget(btn('Cancel', dialog.reject))
        actions.addStretch()
        actions.addWidget(btn('Apply', apply, kind='secondary'))
        save_new=btn('Save as new view',lambda:save(False),kind='primary');save_new.setEnabled(False);actions.addWidget(save_new)
        save_changes=btn('Save changes',lambda:save(True),kind='primary');save_changes.setVisible(bool(existing));save_changes.setEnabled(False);layout.addWidget(save_changes)
        outer.addLayout(actions)
        self.host.run_dialog(dialog)
        self.host.km.cancel_owner(dialog)

    def saved_views(self):
        menu = QMenu(self)
        views = self.host.config.get('alpha3', {}).get('mail_views', [])
        for view in views:
            if isinstance(view, dict) and view.get('task') in TASKS:
                menu.addAction(view.get('name', 'Saved mail view'), lambda checked=False, value=view: self.host.open_mail(value['task'], {**value.get('options', {}),'_saved_view_id':value.get('id')}))
        if not views:
            action = menu.addAction('No saved mail views yet')
            action.setEnabled(False)
        menu.addSeparator()
        if views:menu.addAction('Manage saved mail views',self.manage_saved_views)
        menu.addAction('Other saved views', self.host.perspectives)
        menu.exec(self.saved_button.mapToGlobal(self.saved_button.rect().bottomLeft()))


    def manage_saved_views(self):
        dialog=QDialog(self.host);dialog.setWindowTitle('Saved mail views');dialog.resize(520,420)
        layout=QVBoxLayout(dialog);layout.addWidget(text('Saved mail views','title'))
        layout.addWidget(text('Rename or remove a saved view. Your mail and the default views stay unchanged.','muted',True))
        listing=QListWidget();layout.addWidget(listing,1)
        name=QLineEdit();name.setAccessibleName('View name');layout.addWidget(name)
        message=text('','small',True);layout.addWidget(message)
        def populate():
            listing.clear()
            for i,view in enumerate(self.host.config.get('alpha3',{}).get('mail_views',[])):
                item=QListWidgetItem(view.get('name','Saved mail view'));item.setData(Qt.UserRole,i);listing.addItem(item)
        def selected():
            item=listing.currentItem()
            if item:name.setText(item.text())
        listing.itemSelectionChanged.connect(selected)
        def change(remove=False):
            item=listing.currentItem()
            if not item:return
            views=self.host.config.setdefault('alpha3',{}).setdefault('mail_views',[]);index=item.data(Qt.UserRole)
            if index>=len(views):populate();return
            if not remove and not name.text().strip():message.setText('Enter a name for this view.');return
            before=copy.deepcopy(views)
            if remove:views.pop(index)
            else:views[index]['name']=name.text().strip()[:80]
            if not self.host.persist_preferences():
                self.host.config['alpha3']['mail_views']=before;message.setText('Could not save. Your saved views are unchanged.');return
            message.setText('View removed. Your mail is unchanged.' if remove else 'Name saved.');populate()
        actions=QHBoxLayout();actions.addWidget(btn('Rename',lambda:change(False),kind='secondary'));actions.addWidget(btn('Remove view',lambda:change(True),kind='link'));actions.addStretch();actions.addWidget(btn('Close',dialog.accept));layout.addLayout(actions)
        populate();self.host.run_dialog(dialog)
