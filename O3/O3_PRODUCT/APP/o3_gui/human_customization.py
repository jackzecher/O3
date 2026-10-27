"""Ordinary saved-view choices over the existing KM preview and save contracts.

This module serializes choices only. It never evaluates records. A selection
that cannot be faithfully represented is retained verbatim and is not editable
through the small everyday form.
"""
from copy import deepcopy
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox, QListWidget, QListWidgetItem, QLineEdit, QScrollArea, QFrame
from .workspace_editor import (ViewEditor, ManagedDialog, TypedValue, button, label,
                               signature, ROLE, confirm)

SECTION_NAMES = {'Email':'Mail', 'Person':'People', 'Document':'Documents',
                 'Event':'Calendar', 'LineOfEffort':'Projects', 'Organization':'Organizations'}
SIMPLE_OPERATORS = {'equals':'is', 'not_equals':'is not', 'contains':'contains',
                    'starts_with':'starts with', 'ends_with':'ends with',
                    'is_present':'has a value', 'local_date_age_gt':'is older than this many days',
                    'local_date_age_lte':'is within the last number of days',
                    'email_matches':'is this email address', 'email_list_contains':'includes this address'}
SIMPLE_VALUES = {'none', 'text', 'enum', 'integer', 'boolean', 'date', 'email_pattern'}
QUERY_KEYS = ('filters', 'filter_expression', 'sort', 'sort_direction', 'sorts',
              'group_by', 'group_direction', 'include_inactive', 'search', 'parameters')
FIELD_NAMES = {'subject':'Subject','from':'Sender','to':'To','cc':'Cc','has_attachments':'Attachments',
    'importance':'Importance','received_at_utc':'Received','sent_at_utc':'Sent','updated_at':'Updated in O3',
    'displayName':'Name','mail':'Email address','companyName':'Organization','department':'Department',
    'jobTitle':'Job title','officeLocation':'Office','title':'Title','all_day':'All-day event','location':'Location',
    'organizer':'Organizer','start_utc':'Start','end_utc':'End','summary':'Event name','status':'Status',
    'name':'Name','objective':'Objective','reference_code':'Reference','kind':'Type'}


def human_field(info):
    key=info.get('field_id','')
    return {**info,'label':FIELD_NAMES.get(key,info.get('label','Additional detail'))}


def scroll_page(body):
    scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QFrame.Shape.NoFrame);scroll.setWidget(body)
    return scroll


def simple_fields(schema):
    """Expose only actual advertised, human-editable operands."""
    result = {}
    for info in schema.get('fields', []):
        if info['field_id'] not in FIELD_NAMES and not info['field_id'].startswith('ws:'): continue
        info=human_field(info)
        ops = {op: info.get('operator_specs', {}).get(op, {'value_type':'none'})
               for op in info.get('operators', []) if op in SIMPLE_OPERATORS}
        ops = {op: spec for op, spec in ops.items() if spec.get('value_type') in SIMPLE_VALUES}
        if ops and info.get('label'):
            result[info['field_id']] = {**info, 'simple_operators':ops}
    return result


def readable_selection(definition, schema):
    """Return a faithful flat AND/OR form, or None; never simplify a query."""
    d = definition or {}
    expression = d.get('filter_expression')
    if expression is None:
        expression = {'all':d.get('filters', [])}
    if not isinstance(expression, dict) or len(expression) != 1:
        return None
    mode = next(iter(expression))
    if mode not in ('all', 'any') or not isinstance(expression[mode], list):
        return None
    rows = expression[mode]
    limit = min(8, schema.get('rule_limits', {}).get('max_leaves', 8),
                schema.get('rule_limits', {}).get('max_group_children', 8))
    fields = simple_fields(schema)
    if len(rows) > limit:
        return None
    for row in rows:
        if not isinstance(row, dict) or set(row) - {'field','operator','value'}:
            return None
        field = fields.get(row.get('field'))
        if not field or row.get('operator') not in field['simple_operators']:
            return None
    return mode, deepcopy(rows)


class SimpleCondition(QWidget):
    changed = Signal()
    removed = Signal(object)
    def __init__(self, client, fields, value=None, parent=None):
        super().__init__(parent)
        self.client, self.fields, self.operand = client, fields, None
        self.row = QHBoxLayout(self); self.row.setContentsMargins(0,0,0,0)
        self.field = QComboBox(); self.field.setAccessibleName('What to include')
        for key, info in fields.items(): self.field.addItem(info['label'], key)
        self.operator = QComboBox(); self.operator.setAccessibleName('How to match')
        self.value_host = QWidget(); self.values = QVBoxLayout(self.value_host); self.values.setContentsMargins(0,0,0,0)
        self.row.addWidget(self.field, 2); self.row.addWidget(self.operator, 2); self.row.addWidget(self.value_host, 3)
        self.row.addWidget(button('Remove', lambda:self.removed.emit(self)))
        if value: self.field.setCurrentIndex(self.field.findData(value['field']))
        self.change_field()
        if value:
            self.operator.setCurrentIndex(self.operator.findData(value['operator']))
            self.change_operator(value.get('value'))
        self.field.currentIndexChanged.connect(self.change_field)
        self.operator.currentIndexChanged.connect(lambda _:self.change_operator())
    def change_field(self, *_):
        self.operator.blockSignals(True); self.operator.clear()
        for op in self.fields.get(self.field.currentData(), {}).get('simple_operators', {}):
            self.operator.addItem(SIMPLE_OPERATORS[op], op)
        self.operator.blockSignals(False); self.change_operator()
    def change_operator(self, value=None):
        if self.operand:
            self.values.removeWidget(self.operand); self.operand.deleteLater()
        spec = self.fields.get(self.field.currentData(), {}).get('simple_operators', {}).get(self.operator.currentData(), {'value_type':'none'})
        self.operand = TypedValue(self.client, spec, value); self.values.addWidget(self.operand)
        self.operand.control.setAccessibleName('Value for '+self.field.currentText())
        if self.operand.kind == 'boolean':
            self.operand.control.setItemText(1,'Yes');self.operand.control.setItemText(2,'No')
        elif self.operand.kind == 'email_pattern':
            self.operand.control.setPlaceholderText('person@example.com')
        self.operand.changed.connect(self.changed); self.changed.emit()
    def value(self):
        if not self.field.currentData() or not self.operator.currentData():
            raise ValueError('Choose what to include, or remove the empty row.')
        value = {'field':self.field.currentData(), 'operator':self.operator.currentData()}
        if self.operand.kind != 'none':
            operand = self.operand.value()
            if operand is None: raise ValueError('Finish each choice before previewing.')
            value['value'] = operand
        return value


class HumanViewEditor(ViewEditor):
    """Compatible ViewEditor entrypoint with four plain, bounded steps."""
    def __init__(self, client, owner, schema, definition=None, parent=None, **kwargs):
        self._human_ready = False
        self.original_selection = {k:deepcopy(definition[k]) for k in QUERY_KEYS if definition and k in definition}
        self.simple_selection = readable_selection(definition, schema)
        self.selection_locked = self.simple_selection is None or bool((definition or {}).get('search') or (definition or {}).get('parameters'))
        self.condition_rows = []
        schema=deepcopy(schema)
        for key in ('ordering_fields','grouping_fields','column_fields'):
            schema['view_options'][key]=[human_field(info) for info in schema['view_options'].get(key,[])
                if info['field_id'] in FIELD_NAMES or info['field_id'].startswith('ws:')]
        super().__init__(client, owner, schema, definition, parent, **kwargs)
        self.resize(980, 720)
        self.setWindowTitle('New saved view' if not self.definition else 'Change saved view')
        for heading in self.findChildren(type(self.preview_note)):
            if heading.objectName() == 'heading': heading.setText(self.windowTitle())
        # Keep legacy widgets alive for compatibility, but outside the visible
        # tab tree. Existing serialization and preview widgets are reused.
        self._old_pages = [self.editor_body.widget(i) for i in range(3)]
        for _ in range(3): self.editor_body.removeTab(0)
        for page in self._old_pages: page.setParent(self); page.hide()
        general = QWidget(); gl = QVBoxLayout(general); form = QFormLayout(); gl.addLayout(form)
        form.addRow('Name', self.name); self.name.setPlaceholderText('For example: Recent messages')
        form.addRow('Description (optional)', self.description)
        self.visible.setText('Show this view in '+SECTION_NAMES.get(owner, 'this collection'))
        gl.addWidget(self.visible); self.include.setText('Include older items kept in O3'); gl.addWidget(self.include)
        gl.addWidget(label('Your usual views are ready to use. Save a view only when you want a different way to see your work.'))
        gl.addStretch(); self.editor_body.insertTab(0, scroll_page(general), 'Name')
        conditions = QWidget(); cl = QVBoxLayout(conditions)
        self.conditions_note = label('Include everything, or narrow this view with a few choices.'); cl.addWidget(self.conditions_note)
        self.match = QComboBox(); self.match.addItem('Match all of these choices', 'all'); self.match.addItem('Match any of these choices', 'any')
        cl.addWidget(self.match); self.conditions_box = QVBoxLayout(); cl.addLayout(self.conditions_box)
        self.add_choice = button('Add a choice', self.add_condition); cl.addWidget(self.add_choice); cl.addStretch()
        self.editor_body.insertTab(1, scroll_page(conditions), 'Include')
        arrangement = QWidget(); al = QVBoxLayout(arrangement); sf = QFormLayout(); al.addLayout(sf)
        for i, (combo, direction) in enumerate(self.sort_controls):
            for n in range(combo.count()): combo.setItemText(n, combo.itemText(n).replace(' · Workspace',''))
            direction.setItemText(0, 'First to last'); direction.setItemText(1, 'Last to first')
            host = QWidget(); row = QHBoxLayout(host); row.setContentsMargins(0,0,0,0); row.addWidget(combo, 1); row.addWidget(direction)
            sf.addRow('Sort by' if i == 0 else 'Then by (optional)', host)
        for n in range(self.group.count()): self.group.setItemText(n, self.group.itemText(n).replace(' · Workspace','').replace(' · calendar day',''))
        sf.addRow('Group by', self.group); self.group_direction.setItemText(0,'First to last'); self.group_direction.setItemText(1,'Last to first'); sf.addRow('Group order',self.group_direction)
        al.addWidget(self.columns, 1); self.editor_body.insertTab(2, scroll_page(arrangement), 'Layout'); self.editor_body.setTabText(3, 'Preview')
        self.preview_note.setText('Preview uses your saved information. Nothing changes until you save.')
        self.preview_button.setText('Preview'); self.save_button.setText('Save changes' if self.definition else 'Save as new view')
        self.match.currentIndexChanged.connect(self.changed)
        if self.simple_selection:
            mode, rows = self.simple_selection; self.match.setCurrentIndex(self.match.findData(mode))
            for value in rows: self.add_condition(value)
        if self.selection_locked or self.builtin:
            self.conditions_note.setText('This view keeps its existing selection. You can change its name and layout here without changing which items it includes.')
            self.match.hide(); self.add_choice.hide()
            for row in self.condition_rows: row.hide()
            self.include.setEnabled(False)
            for combo, direction in self.sort_controls: combo.setEnabled(False); direction.setEnabled(False)
            self.group.setEnabled(False); self.group_direction.setEnabled(False)
        self._human_ready = True; self._initial_choices = signature(self._selection_from_controls())
        if self.definition and not self.builtin:
            self.save_new_button = button('Save as new view', self.save_as_new)
            self.layout_box.itemAt(self.layout_box.count()-1).layout().insertWidget(1, self.save_new_button)
        self.arm_draft(self.draft); self.editor_body.setCurrentIndex(0)
    def add_condition(self, value=None):
        if isinstance(value, bool): value = None
        fields = simple_fields(self.schema)
        limit = min(8, self.schema.get('rule_limits', {}).get('max_leaves',8), self.schema.get('rule_limits', {}).get('max_group_children',8))
        if not fields: self.message.setText('There are no extra choices for this collection yet.'); return
        if len(self.condition_rows) >= limit: self.message.setText('Use up to '+str(limit)+' choices in this view.'); return
        row = SimpleCondition(self.client, fields, value); self.condition_rows.append(row); self.conditions_box.addWidget(row)
        row.changed.connect(self.changed); row.removed.connect(self.remove_condition); self.changed()
    def remove_condition(self, row):
        self.condition_rows.remove(row); self.conditions_box.removeWidget(row); row.deleteLater(); self.changed()
    def _selection_from_controls(self):
        if self.selection_locked or self.builtin: return deepcopy(self.original_selection)
        sorts = [{'field':c.selected_value(),'direction':d.currentData()} for c,d in self.sort_controls if c.selected_value() is not None]
        return {'filters':[], 'filter_expression':{self.match.currentData():[r.value() for r in self.condition_rows]} if self.condition_rows else None,
                'sorts':sorts, 'group_by':self.group.selected_value(), 'group_direction':self.group_direction.currentData(), 'include_inactive':self.include.isChecked()}
    def spec(self):
        if not self._human_ready: return super().spec()
        data = {'label':self.name.text().strip(),'visible':self.visible.isChecked(),'order':self.order.value()}
        if self.builtin: return data
        query = self._selection_from_controls()
        # Merely opening/renaming/rearranging an older view must never migrate
        # its filters, null handling, ordering or tie-break behavior.
        if self.original_selection and (self.selection_locked or signature(query) == self._initial_choices): query = deepcopy(self.original_selection)
        return {**data, 'record_type':self.owner, 'description':self.description.text().strip(), **query}
    def changed(self, *_):
        if not self._human_ready: return
        super().changed()
        if self.preview_response is None: self.preview_note.setText('Your choices changed. Preview them before saving.')
    def render_preview(self, response):
        super().render_preview(response)
        data = response['result']
        if data.get('state','available') == 'available':
            count = data.get('total_count',len(data.get('rows',[])))
            message = f'{count:,} matching items · preview only' if count else 'No items match these choices. You can change them or save this view for later.'
            if data.get('unknown_count'): message += ' Some items could not be checked.'
            self.preview_note.setText(message)
    def save(self):
        if not self.name.text().strip(): self.message.setText('Give this view a name.'); self.name.setFocus(); return
        try: current=signature(self.spec())
        except (ValueError,TypeError,KeyError) as error: self.message.setText(str(error)); return
        if not self.preview_response or self.preview_semantics != current:
            self.message.setText('Preview your choices, then choose Save.'); self.preview(); return
        super().save()
    def save_as_new(self):
        if self.busy or self.pending_save: return
        try: current=signature(self.spec())
        except (ValueError,TypeError,KeyError) as error: self.message.setText(str(error)); return
        if not self.preview_response or self.preview_semantics != current:
            self.message.setText('Preview your choices, then choose Save as new view.'); self.preview(); return
        self.definition = None; self.saved_id = None; self.query_committed = None
        self.save_button.setText('Save as new view'); self.save()


class SavedViewsDialog(ManagedDialog):
    """Manage personal views without exposing registry/rule authoring."""
    def __init__(self, client, owner='Email', parent=None, *, get_presentation=None, persist_presentation=None, display_name=None):
        super().__init__(client, 'Saved views', parent); self.resize(740, 570)
        self.owner = owner; self.get_presentation = get_presentation; self.persist_presentation = persist_presentation
        host = parent
        while host is not None:
            if hasattr(host,'get_view_layout') and hasattr(host,'persist_view_layout'):
                if self.get_presentation is None: self.get_presentation = lambda vid,kind:host.get_view_layout(kind,vid)
                if self.persist_presentation is None: self.persist_presentation = lambda vid,kind,value:host.persist_view_layout(kind,vid,value)
                break
            host = host.parentWidget()
        self.schema = None; self.views = []; self.child_dialog = None
        self.layout_box.addWidget(label('Keep the views you use most. Standard views are already set up.'))
        self.search = QLineEdit(); self.search.setPlaceholderText('Find a view…'); self.search.setClearButtonEnabled(True); self.layout_box.addWidget(self.search)
        self.items = QListWidget(); self.items.setAccessibleName('Saved views'); self.layout_box.addWidget(self.items, 1)
        self.empty = label(''); self.layout_box.addWidget(self.empty)
        row = QHBoxLayout()
        self.new_button = button('New view', lambda:self.edit(new=True)); self.edit_button = button('Change view', self.edit)
        self.copy_button = button('Make a copy', self.duplicate); self.hide_button = button('Hide view', self.toggle_view)
        for item in (self.new_button,self.edit_button,self.copy_button,self.hide_button): row.addWidget(item)
        self.layout_box.addLayout(row); self.buttons(); self.items.itemActivated.connect(lambda _:self.edit()); self.items.currentItemChanged.connect(self.update_actions); self.search.textChanged.connect(self.filter)
        self.reload()
    def selected(self):
        item = self.items.currentItem(); return item.data(ROLE) if item else None
    def update_actions(self, *_):
        selected = self.selected(); owned = bool(selected and selected['view_id'].startswith('view:user:'))
        self.new_button.setEnabled(bool(self.schema) and not self.busy); self.edit_button.setEnabled(bool(selected) and not self.busy)
        self.copy_button.setEnabled(owned and not self.busy); self.hide_button.setEnabled(owned and not self.busy)
        self.hide_button.setText('Show view' if selected and selected.get('state') == 'disabled' else 'Hide view')
    def reload(self):
        self.items.clear(); self.schema = None; self.update_actions()
        def schema_loaded(response):
            self.schema = response['result']; self.revision = response['workspace_revision']
            self.request('registry.views', {'record_type':self.owner}, views_loaded)
        def views_loaded(response):
            if response['workspace_revision'] != self.revision:
                self.message.setText('Your saved views changed while loading. Close and reopen Saved views.'); self.schema = None; self.update_actions(); return
            self.views = [v for v in response['result'].get('views',[]) if v.get('record_type',v.get('owner_type')) == self.owner and v.get('state') != 'retired'
                          and (v['view_id'].startswith('view:user:') or not v.get('parameter_schema'))]
            for v in self.views:
                name = v.get('display_label') or v.get('label') or v.get('name') or 'Saved view'
                suffix = ' · hidden' if v.get('state') == 'disabled' else (' · standard' if not v['view_id'].startswith('view:user:') else '')
                item = QListWidgetItem(name+suffix); item.setData(ROLE,v); self.items.addItem(item)
            self.empty.setText('No saved views yet. Your normal collection is ready to use.' if not self.views else '')
            self.items.setCurrentRow(0); self.filter(); self.update_actions()
        self.request('builder.schema', {'record_type':self.owner}, schema_loaded)
    def filter(self, *_):
        query = self.search.text().strip().casefold()
        for i in range(self.items.count()): self.items.item(i).setHidden(query not in self.items.item(i).text().casefold())
    def edit(self, *_ , new=False, duplicate=False):
        if not self.schema or self.busy: return
        if self.child_dialog: self.child_dialog.raise_(); return
        definition = None if new else self.selected()
        if not new and not definition: return
        layout = self.get_presentation((definition or {}).get('view_id'),self.owner) if self.get_presentation else None
        dialog = HumanViewEditor(self.client,self.owner,self.schema,definition,self,presentation=layout,persist_presentation=self.persist_presentation,duplicate=duplicate)
        dialog.revision = self.revision; self.child_dialog = dialog
        def finished(result):
            self.child_dialog = None
            if result: self.reload()
            dialog.deleteLater()
        dialog.finished.connect(finished); dialog.open()
    def duplicate(self): self.edit(duplicate=True)
    def toggle_view(self):
        selected = self.selected()
        if not selected or not selected['view_id'].startswith('view:user:'): return
        operation = 'enable' if selected.get('state') == 'disabled' else 'disable'
        self.request('view.'+operation, {'view_id':selected['view_id']}, lambda _:self.reload(), mutation=True)
