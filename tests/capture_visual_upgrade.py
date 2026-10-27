"""Repeatable offscreen component captures, always in a new evidence directory."""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_visual_upgrade as fixture
from o3_gui.relationship_evidence import RelationshipEvidence

output = fixture.ROOT / 'verification' / 'runs' / ('visual-components-' + uuid4().hex[:8])
output.mkdir(parents=True, exist_ok=False)
for name, width, height, scale, theme, mode in [
    ('connections', 1100, 700, 1, 'harbor', 'map'),
    ('connections-compact-150', 837, 500, 1.5, 'harbor', 'map'),
    ('connections-night', 1100, 700, 1, 'night', 'map'),
    ('connections-list-150', 837, 600, 1.5, 'harbor', 'list'),
]:
    widget, ws = fixture.make_map(width, height, scale, theme)
    widget.set_mode(mode); fixture.APP.processEvents(); widget.canvas.arrange(); fixture.APP.processEvents()
    widget.grab().save(str(output / (name + '.png')))
    widget.close(); widget.deleteLater(); fixture.APP.processEvents()
dialog = RelationshipEvidence('Mail from Morgan', {'source':'a','target':'b','predicate':'sent_by',
    'authority':'core','claims':[{'evidence':{'field':'sender','source_record':'a'}}]},
    {'a':{'label':'Next week’s planning'},'b':{'label':'Morgan'}})
dialog.show(); fixture.APP.processEvents(); dialog.grab().save(str(output / 'supporting-details.png'))
dialog.close()
(output / 'QUALIFICATION.txt').write_text('Offscreen Qt component captures using explicitly loaded installed Segoe UI. Native Windows integration, launcher, and runtime are not qualified by this capture.\n', encoding='utf-8')
print(str(output))
