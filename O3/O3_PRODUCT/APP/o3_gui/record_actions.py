"""Native, revision-checked commands. Forms never mutate Core or SQLite directly."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QFileDialog,QFormLayout,
    QHBoxLayout,QLineEdit,QListWidget,QListWidgetItem,QPlainTextEdit,QTableWidget,
    QTableWidgetItem,QHeaderView,QAbstractItemView,QWidget,QVBoxLayout)
from .workspace_editor import (ManagedDialog,RecordPicker,TypedValue,WorkspaceConfiguration,
                              button,label,choices,confirm,text_lines,ROLE)


class ManualValues(ManagedDialog):
    def __init__(self,client,kind,rid,parent=None):
        super().__init__(client,'Edit details',parent)
        self.kind,self.rid=kind,rid;self.definition=None;self.control=None;self.generation=0
        self.layout_box.addWidget(label('Add your own details here. Information found in your files stays unchanged.'))
        row=QHBoxLayout();self.properties=QComboBox();row.addWidget(self.properties,1)
        row.addWidget(button('Refresh',self.reload));self.layout_box.addLayout(row)
        self.value_host=QWidget();self.value_layout=QVBoxLayout(self.value_host);self.layout_box.addWidget(self.value_host)
        self.result=QPlainTextEdit();self.result.setReadOnly(True);self.layout_box.addWidget(self.result,1)
        row=QHBoxLayout();self.set_button=button('Set value',self.save);self.clear_button=button('Clear value',self.clear)
        row.addWidget(self.set_button);row.addWidget(self.clear_button);row.addWidget(button('Explain',self.explain));row.addStretch();row.addWidget(button('Close',self.accept));self.layout_box.addLayout(row)
        self.properties.currentIndexChanged.connect(self.select_property);self.reload()

    def configure(self):
        WorkspaceConfiguration(self.client,self.kind,self).exec();self.reload()

    def reload(self):
        def done(response):
            self.revision=response['workspace_revision'];self.properties.blockSignals(True);self.properties.clear()
            for definition in response['result']['workspace_properties']:
                if definition.get('state')!='retired':self.properties.addItem(definition.get('label',definition['property_id']),definition)
            self.properties.blockSignals(False);self.select_property()
        self.request('registry.properties',{'record_type':self.kind},done)

    def select_property(self,*_):
        self.generation+=1;generation=self.generation;self.definition=self.properties.currentData()
        self.set_button.setEnabled(False);self.clear_button.setEnabled(False)
        while self.value_layout.count():
            w=self.value_layout.takeAt(0).widget()
            if w:w.deleteLater()
        self.control=None
        if not self.definition:self.result.setPlainText('There are no editable details for this item yet.');return
        d=self.definition
        def done(response):
            if generation!=self.generation:return
            if not response['ok']:self.message.setText(response['error']['code']+': '+response['error']['message']);return
            result=response['result'];self.revision=response['workspace_revision']
            value=result.get('value')
            from .record_content import display_value
            rendered='Linked record selection' if isinstance(value,(dict,list)) else display_value(value)
            self.result.setPlainText(d.get('label',d['property_id'])+'\n\n'+rendered+'\n\n'+
                result.get('state','unavailable').replace('_',' ').capitalize()+' · '+
                ('Entered by you' if d['mode']=='manual' else 'Found from your saved information')+
                ('\n'+str(result['reason']) if result.get('reason') else ''))
            manual=d['mode']=='manual' and d.get('state')=='enabled'
            if manual:
                self.control=TypedValue(self.client,d,result.get('value'));self.value_layout.addWidget(self.control)
            self.set_button.setEnabled(manual);self.clear_button.setEnabled(manual)
        self.client.request('property.value',{'record_type':self.kind,'record_id':self.rid,'property_id':d['property_id']},done,owner=self)

    def params(self):return {'record_type':self.kind,'record_id':self.rid,'property_id':self.definition['property_id']}
    def save(self):
        if not self.control:return
        try:value=self.control.value()
        except ValueError as exc:self.message.setText(str(exc));return
        if value is None:self.message.setText('Choose a value, or use Clear value to remove the assignment.');return
        self.request('property.set',{**self.params(),'value':value},lambda r:self.select_property(),mutation=True)
    def clear(self):
        if self.definition and confirm(self,'Clear assignment','Clear this manual value? Its previous value remains in history.'):
            self.request('property.clear',self.params(),lambda r:self.select_property(),mutation=True)
    def explain(self):
        if self.definition:self.result.appendPlainText('\nYou can edit details you entered. Information found from your files is read-only here, so its source remains clear.')


class LOEEditor(ManagedDialog):
    def __init__(self,client,record=None,*,adopt=False,parent=None):
        super().__init__(client,'Keep this project' if adopt else 'Edit project' if record else 'Create a project',parent)
        self.record,self.adopt=record,adopt;self.created_id=None
        self.layout_box.addWidget(label('Give your project a recognizable name. O3 uses its name and other names to find related mail and documents you already have.'))
        p=record.get('properties',{}) if record else {};form=QFormLayout();self.layout_box.addLayout(form)
        self.name=QLineEdit(p.get('name',''));self.name.setMaxLength(120)
        self.kind=choices(['loe','project','program','initiative','workstream'],p.get('kind','project'))
        self.objective=QPlainTextEdit(p.get('objective') or '');self.objective.setMaximumHeight(160)
        self.code=QLineEdit(p.get('reference_code') or '');self.code.setMaxLength(32)
        self.aliases=QPlainTextEdit('\n'.join(p.get('aliases',[])));self.aliases.setMaximumHeight(100)
        for title,w in [('Name',self.name),('Type',self.kind),('Objective',self.objective),('Reference code',self.code),('Other names, one per line',self.aliases)]:form.addRow(title,w)
        self.buttons(self.save)
    def save(self):
        fields={'name':self.name.text().strip(),'kind':self.kind.currentData(),'objective':self.objective.toPlainText().strip() or None,
                'reference_code':self.code.text().strip() or None,'aliases':text_lines(self.aliases.toPlainText())}
        if self.adopt and not confirm(self,'Keep this project','Keep this project in O3 so you can edit its details? Its original source and history will be preserved.'):return
        op='loe.adopt' if self.adopt else 'loe.edit' if self.record else 'loe.create'
        params={'changes' if op=='loe.edit' else 'fields':fields}
        if self.record:params['record_id']=self.record['record_id']
        def saved(response):
            result=response['result'];self.created_id=result.get('loe_id') or result.get('record_id') or (result.get('affected_core_ids') or [None])[0];self.accept()
        self.request(op,params,saved,mutation=True)


class OrganizationEditor(ManagedDialog):
    def __init__(self,client,record=None,parent=None):
        super().__init__(client,'Company details',parent)
        self.record=record;self.wsid=(record.get('record_id') if record.get('effective_kind')=='workspace_overlay' else record.get('assigned_ws_org_id')) if record else None
        self.seed=record if record and not self.wsid else None;self.members=[];self.member_generation=0
        self.layout_box.addWidget(label('Choose which saved company entries belong together. Their original names and sources stay unchanged.'))
        self.name=QLineEdit(record.get('display_name',record.get('properties',{}).get('name','')) if record else '');self.name.setMaxLength(160)
        form=QFormLayout();form.addRow('Display name',self.name);self.layout_box.addLayout(form)
        self.members_list=QListWidget();self.layout_box.addWidget(self.members_list,1)
        row=QHBoxLayout()
        for title,handler in [('Choose / add…',self.add),('Remove',self.remove),('Move…',self.move),('Refresh',self.reload)]:row.addWidget(button(title,handler))
        self.layout_box.addLayout(row)
        row=QHBoxLayout()
        row.addWidget(button('Your details…',self.properties));row.addWidget(button('Archive / restore',self.lifecycle));row.addWidget(button('Undo last membership edit',self.undo));self.layout_box.addLayout(row)
        self.buttons(self.save)
        if self.wsid:self.reload()
        elif self.seed:self.members=[self.seed['record_id']];self.paint_members()

    def reload(self):
        if not self.wsid:self.paint_members();return
        def done(response):
            self.revision=response['workspace_revision'];self.record=response['result']['organization']
            self.name.setText(self.record.get('display_name',''));self.members=list(self.record.get('core_org_ids',[]));self.paint_members()
        self.request('organization.effective',{'record_id':self.wsid},done)

    def paint_members(self):
        self.member_generation+=1
        self.members_list.clear()
        for rid in self.members:
            item=QListWidgetItem('Loading company…');item.setData(ROLE,rid);self.members_list.addItem(item)
            def loaded(response,item=item):
                if response.get('ok'):
                    from .km_session import display_row
                    item.setText(display_row(response['result']['record'])['label'])
            # The list may be replaced before the response; generation is checked.
            generation=self.member_generation
            def safe(response,item=item,generation=generation,loaded=loaded):
                if generation==self.member_generation:loaded(response)
            self.client.request('records.get',{'record_type':'Organization','record_id':rid},safe,owner=self)

    def add(self):
        picker=RecordPicker(self.client,['Organization'],multiple=not bool(self.wsid),parent=self)
        if picker.exec()!=QDialog.DialogCode.Accepted:return
        ids=[r['record_id'] for r in picker.selected_records]
        if not ids:return
        if self.wsid:
            self.request('organization.add_member',{'ws_org_id':self.wsid,'core_org_id':ids[0]},lambda r:self.reload(),mutation=True)
        else:self.members=list(dict.fromkeys(self.members+ids));self.paint_members()
    def selected_member(self):
        item=self.members_list.currentItem();return item.data(ROLE) if item else None
    def remove(self):
        rid=self.selected_member()
        if not rid:return
        if self.wsid:
            if confirm(self,'Separate entry','Show this company entry separately again? Its original information will be preserved.'):
                self.request('organization.remove_member',{'ws_org_id':self.wsid,'core_org_id':rid},lambda r:self.reload(),mutation=True)
        else:self.members.remove(rid);self.paint_members()
    def move(self):
        rid=self.selected_member()
        if not self.wsid or not rid:return
        picker=RecordPicker(self.client,['WorkspaceOrganization'],multiple=False,parent=self)
        if picker.exec()!=QDialog.DialogCode.Accepted or not picker.selected_records:return
        empty=len(self.members)==1
        if not confirm(self,'Move entry','Group this company entry with the selected company?'+(' The previous empty group will be archived.' if empty else '')):return
        self.request('organization.move_member',{'ws_org_id':self.wsid,'core_org_id':rid,'target_ws_org_id':picker.selected_records[0]['record_id'],
            'confirmed':True,'archive_empty_source':empty},lambda r:self.reload(),mutation=True)
    def properties(self):
        if self.wsid:
            ManualValues(self.client,'WorkspaceOrganization',self.wsid,self).exec();self.reload()
        else:self.message.setText('Save this company group before adding your own details.')
    def lifecycle(self):
        if not self.wsid:return
        archived=bool(self.record.get('archived',not self.record.get('active',True)))
        if not confirm(self,'Restore' if archived else 'Archive','Restore the entries that have not since been grouped elsewhere?' if archived else 'Archive this company group and show its entries separately? History is retained. O3 will explain if another saved view needs it.'):return
        self.request('organization.restore' if archived else 'organization.archive',{'ws_org_id':self.wsid,'confirmed':True,'membership_disposition':'release'},lambda r:self.reload(),mutation=True)
    def undo(self):
        if self.wsid and confirm(self,'Undo membership edit','Undo the last entry you added or removed? Other changes will remain as they are.'):
            self.request('organization.undo',{'ws_org_id':self.wsid},lambda r:self.reload(),mutation=True)
    def save(self):
        params={'display_name':self.name.text().strip()}
        if self.wsid:params['ws_org_id']=self.wsid;op='organization.rename'
        elif self.seed:
            op='organization.absorb';params.update(base_core_org_id=self.seed['record_id'],core_org_ids=self.members,confirm_explicit_membership=True)
        else:op='organization.create';params['core_org_ids']=self.members
        if not self.wsid and not confirm(self,'Save company group','Group these selected entries as one company in O3? Original information will be preserved.'):return
        def saved(response):
            self.created_id=response['result'].get('ws_org_id',self.wsid);self.accept()
        self.request(op,params,saved,mutation=True)


class CalendarSources(ManagedDialog):
    def __init__(self,client,source_root,parent=None):
        super().__init__(client,'Calendar sources',parent);self.source_root=source_root;self.sources=[];self.settings={}
        self.table=QTableWidget(0,3);self.table.setHorizontalHeaderLabels(['CALENDAR','SOURCE','STATE']);self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.layout_box.addWidget(self.table,1)
        self.name=QLineEdit();form=QFormLayout();form.addRow('Display name',self.name);self.layout_box.addLayout(form)
        row=QHBoxLayout();row.addWidget(button('Save display name',self.rename));row.addWidget(button('Relink moved source…',self.relink));row.addWidget(button('Refresh',self.reload));row.addWidget(button('Close',self.accept));self.layout_box.addLayout(row)
        self.table.itemSelectionChanged.connect(self.select);self.reload()
    def reload(self):
        def configured(response):
            self.settings=response['result']['settings'];self.revision=response['workspace_revision']
            self.request('calendar.sources',{},loaded)
        def loaded(response):
            if response['workspace_revision']!=self.revision:self.message.setText('Configuration changed. Refresh before editing.');return
            raw=response['result']['sources'];self.sources=list(raw.values()) if isinstance(raw,dict) else raw
            self.table.setRowCount(len(self.sources))
            for i,row in enumerate(self.sources):
                for j,key in enumerate(('display_name','path','state')):self.table.setItem(i,j,QTableWidgetItem(str(row.get(key,''))))
            if self.sources:self.table.selectRow(0)
        self.request('configuration.get',{},configured)
    def selected(self):
        i=self.table.currentRow();return self.sources[i] if 0<=i<len(self.sources) else None
    def select(self):
        row=self.selected();self.name.setText(row.get('display_name','') if row else '')
    def rename(self):
        row=self.selected()
        if not row:return
        names=dict(self.settings.get('calendar_display_names',{}));names[row['scope']]=self.name.text().strip()
        self.request('configuration.save',{'calendar_display_names':names},lambda r:self.reload(),mutation=True)
    def relink(self):
        row=self.selected()
        if not row or not self.source_root:self.message.setText('Choose your export folder first.');return
        path,_=QFileDialog.getOpenFileName(self,'Select relocated calendar',str(Path(self.source_root)/'Calendars'),'Calendar (*.ics)')
        if not path:return
        p=Path(path);root=Path(self.source_root)/'Calendars'
        if p.parent.resolve()!=root.resolve():self.message.setText('Choose a calendar file directly inside your selected Calendars folder.');return
        if not confirm(self,'Relink calendar','Use this file for the existing calendar while keeping its saved events? The original file must no longer be in use.'):return
        self.request('calendar.relink',{'calendar_scope':row['scope'],'new_path':p.name,'source_root':str(self.source_root),'confirmed':True},lambda r:self.reload(),mutation=True)
