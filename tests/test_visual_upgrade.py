"""Isolated offscreen visual regressions; no source data, desktop or native launcher."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import Qt, QRect, QSize
from PySide6.QtGui import QFont, QFontMetrics, QColor, QPalette, QImage, QPainter, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QStyleOptionViewItem
from PySide6.QtTest import QTest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'O3' / 'O3_PRODUCT' / 'APP'))
from o3_gui.presentation import THEME_CHOICES, theme_tokens, native_palette, stylesheet_for, application_icon
from o3_gui.ui import RecordDelegate, icon
from o3_gui.spatial import Neighborhood
from o3_gui.relationship_evidence import RelationshipEvidence, context_summary
APP = QApplication.instance() or QApplication([])
if os.name == 'nt':
    for name in ('segoeui.ttf', 'seguisb.ttf'):
        path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
        if path.is_file(): QFontDatabase.addApplicationFont(str(path))


def luminance(color):
    values = [getattr(QColor(color), component)() / 255 for component in ('red', 'green', 'blue')]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(a * b for a, b in zip(values, (.2126, .7152, .0722)))


def contrast(a, b):
    light, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (light + .05) / (dark + .05)


def fixture():
    kinds = ['Email', 'Person', 'Document', 'Event', 'LineOfEffort', 'Organization']
    records = {f'r{i}': {'id': f'r{i}', 'title': ('A very long message title about the upcoming ' * 5 if i == 0 else f'Connected item {i}: planning and next steps'), 'kind': kind, 'target_kind': kind} for i, kind in enumerate(kinds)}
    edges = []
    for i in range(1, 9):
        edge = {'source': 'r0', 'target': f'r{i}', 'predicate': 'references', 'label': 'mentions',
                'authority': 'user' if i == 4 else 'core', 'other': f'r{i}',
                'other_label': records.get(f'r{i}', {}).get('title', f'Additional item {i}'),
                'other_type': records.get(f'r{i}', {}).get('kind', 'Document'), 'other_target_kind': 'Document'}
        edges.append(edge)
    context = {'source': 'r1', 'target': 'r5', 'predicate': 'affiliated_with', 'label': 'works at',
               'authority': 'core', 'other': 'r5', 'other_label': records['r5']['title'], 'other_type': 'Organization'}
    records['r0']['relationships'] = edges
    return {'seed': 'r0', 'nodes': records, 'edges': edges[:4] + [context], 'direct_total': 8}


def workspace(scale=1, route=None):
    opened, explained = [], []
    names = {'Email': 'Mail', 'Person': 'Person', 'Document': 'Document', 'Event': 'Event', 'LineOfEffort': 'Project', 'Organization': 'Organization'}
    return SimpleNamespace(scale=scale, navigation=SimpleNamespace(current=route or {}),
            type_name=lambda kind: names.get(kind, kind), open_record=opened.append,
            show_connection=lambda *args: explained.append(args), opened=opened, explained=explained)


def make_map(width=900, height=700, scale=1, theme='harbor', route=None):
    APP.setStyleSheet(stylesheet_for(scale=scale, theme=theme)); APP.setPalette(native_palette(theme))
    ws = workspace(scale, route)
    widget = Neighborhood(ws); widget.resize(width, height); widget.show(); widget.load(fixture())
    APP.processEvents(); APP.processEvents(); widget.canvas.arrange(); APP.processEvents()
    return widget, ws


class VisualUpgradeTests(unittest.TestCase):
    def tearDown(self):
        for window in APP.topLevelWidgets(): window.close(); window.deleteLater()
        APP.processEvents()

    def test_palette_contrast_and_compatibility(self):
        for theme, label in THEME_CHOICES:
            c = theme_tokens(theme)
            for surface in ('canvas', 'rail', 'surface', 'selection', 'control'):
                for text in ('body', 'muted'):
                    with self.subTest(theme=theme, text=text, surface=surface):
                        self.assertGreaterEqual(contrast(c[text], c[surface]), 4.5)
            for status in ('success', 'warn', 'error', 'accent'):
                self.assertGreaterEqual(contrast(c[status], c['canvas']), 4.5, (theme, status))
            self.assertGreaterEqual(contrast(c['accent'], c['on_accent']), 4.5)
            self.assertGreaterEqual(contrast(c['focus'], c['canvas']), 3)
            self.assertGreaterEqual(contrast(c['edge'], c['canvas']), 3)
            self.assertEqual(native_palette(theme).color(QPalette.Text).name(), c['body'])
        self.assertEqual(theme_tokens('unknown'), theme_tokens('harbor'))
        changed = theme_tokens(); changed['body'] = 'bad'
        self.assertNotEqual(theme_tokens()['body'], 'bad')
        self.assertTrue(stylesheet_for())
        self.assertEqual(len(THEME_CHOICES), 24)

    def test_full_date_measurement_and_reason_reflow(self):
        rows = QListWidget(); rows.resize(700, 600)
        delegate = RecordDelegate(rows)
        for scale in (1, 1.25, 1.5):
            font = QFont('Segoe UI'); font.setPixelSize(round(15 * scale))
            option = QStyleOptionViewItem(); option.font = font
            for width in (280, 420, 760):
                option.rect = QRect(0, 0, width, 160)
                for month in ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'):
                    record = {'title': 'Quarterly planning', 'kind': 'Mail', 'person': 'Morgan',
                        'capture_label': f'{month} 28, 2026', 'state': 'unknown',
                        'reason': 'No reply could be checked because this conversation is missing part of its saved history.'}
                    result = delegate.layout_for(option, record, width)
                    self.assertGreaterEqual(result['date_width'], QFontMetrics(result['small']).horizontalAdvance(record['capture_label']))
                    self.assertGreater(result['title_width'], 0)
                    self.assertGreaterEqual(result['height'], result['reason_y'] + result['reason_lines'] * QFontMetrics(result['small']).height())
                    self.assertTrue(result['reason'].startswith("Couldn't check"))
                    self.assertGreaterEqual(result['reason_lines'], 1)
                    item = QListWidgetItem(rows); item.setData(Qt.UserRole + 1, record)
                    image = QImage(width, result['height'], QImage.Format_ARGB32); image.fill(Qt.white)
                    painter = QPainter(image)
                    option.rect.setHeight(result['height']); option.palette = native_palette('night')
                    delegate.paint(painter, option, rows.model().index(rows.count() - 1, 0)); painter.end()

    def test_focal_visible_and_no_horizontal_plane_all_scales(self):
        for scale in (1, 1.25, 1.5):
            for width, height in ((900, 700), (1360, 780), (420, 650)):
                with self.subTest(scale=scale, width=width):
                    widget, ws = make_map(width, height, scale)
                    self.assertEqual(widget.width(), width, 'Controls must not force a wider window')
                    focal = widget.nodes[widget.seed].geometry()
                    viewport = widget.scroll.viewport().rect()
                    self.assertEqual(widget.scroll.horizontalScrollBar().maximum(), 0)
                    self.assertGreaterEqual(focal.left(), 0)
                    self.assertLessEqual(focal.right(), viewport.width())
                    self.assertLessEqual(focal.bottom(), viewport.height())
                    if width >= 900:
                        first_neighbor = next(card for key, card in widget.nodes.items() if key != widget.seed)
                        self.assertLessEqual(first_neighbor.geometry().bottom(), viewport.height())
                    for card in widget.nodes.values():
                        self.assertGreater(card.width(), 0)
                        self.assertGreaterEqual(card.geometry().left(), 0)
                        self.assertLessEqual(card.geometry().right(), viewport.width())
                    widget.close(); widget.deleteLater(); APP.processEvents()

    def test_list_complete_counts_authority_and_direction(self):
        widget, ws = make_map()
        self.assertIn('4 of 8', widget.subtitle.text())
        self.assertIn('1 related context', widget.subtitle.text())
        self.assertEqual(len(widget.edges), 9)
        widget.set_mode('list'); APP.processEvents()
        self.assertIn('8 of 8', widget.subtitle.text())
        self.assertEqual(sum(button.isVisible() for button in widget.edge_buttons), 9)
        self.assertIn('Added by you', widget._description(widget.edges[3]))
        context = widget.edges[4]
        self.assertEqual((context['source'], context['target']), ('r1', 'r5'))
        widget.inspect(8); widget.open_active()
        self.assertEqual(ws.opened[-1], 'r8')
        widget.show_evidence(); self.assertEqual(ws.explained[-1][0]['target'], 'r8')

    def test_keyboard_center_and_return_state(self):
        widget, ws = make_map(route={'map_mode': 'list', 'map_y': 30, 'map_edge': ['r0', 'references', 'r4']})
        self.assertEqual(widget.mode, 'list'); self.assertEqual(widget.active, 3)
        first = widget.edge_buttons[0]; first.setFocus()
        QTest.keyClick(first, Qt.Key_Down)
        self.assertTrue(widget.edge_buttons[1].hasFocus())
        QTest.keyClick(widget.edge_buttons[1], Qt.Key_Return)
        self.assertEqual(widget.active, 1)
        widget.center_on_seed(); APP.processEvents()
        self.assertEqual(widget.mode, 'map'); self.assertTrue(widget.nodes['r0'].hasFocus())
        self.assertEqual(widget.scroll.verticalScrollBar().value(), 0)
        self.assertEqual(widget.view_state()['map_mode'], 'map')
        QTest.keyClick(widget.nodes['r0'], Qt.Key_Right)
        self.assertTrue(widget.nodes['r1'].hasFocus())

    def test_live_theme_and_brand_assets(self):
        for theme, _ in THEME_CHOICES:
            widget, ws = make_map(theme=theme)
            self.assertEqual(widget.canvas.palette().color(QPalette.Mid), native_palette(theme).color(QPalette.Mid))
            self.assertFalse(icon('mail').pixmap(QSize(20, 20)).isNull())
            widget.close(); widget.deleteLater(); APP.processEvents()
        brand = application_icon()
        self.assertFalse(brand.isNull())
        for size in (16, 20, 24, 32, 40, 48, 64, 96, 128, 256):
            self.assertFalse(brand.pixmap(size, size).isNull())

    def test_connection_explanation_preserves_payload_without_machine_ui(self):
        payload = {'source':'r0', 'target':'r1', 'predicate':'sent_by', 'authority':'workspace_manual',
                   'claims':[{'evidence':{'field':'Person.companyName','source_record':'r1'}}], 'opaque_hash':'retain-me'}
        before = json.dumps(payload, sort_keys=True)
        labels = {'r0':{'label':'Planning message'}, 'r1':{'label':'Morgan'}}
        dialog = RelationshipEvidence('Connection', payload, labels)
        rendered = dialog.summary.toPlainText()
        self.assertIn('Added by you', rendered)
        self.assertIn('does not change the original material', rendered)
        self.assertNotIn('opaque_hash', rendered)
        self.assertNotIn('Technical evidence', rendered)
        self.assertIs(dialog.evidence, payload)
        self.assertEqual(json.dumps(payload, sort_keys=True), before)


if __name__ == '__main__': unittest.main()

