"""Rebuild O3's derived PNG/ICO assets from editable SVG source; no GUI window."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import struct
from pathlib import Path
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QFontDatabase
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'O3' / 'O3_PRODUCT' / 'APP' / 'o3_gui' / 'assets'

def render(source, width, height):
    renderer = QSvgRenderer(str(ASSETS / source))
    if not renderer.isValid(): raise ValueError('Invalid SVG: ' + source)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image); renderer.render(painter); painter.end()
    buffer = QBuffer(); buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG'): raise RuntimeError('PNG encoding failed')
    return bytes(buffer.data())

def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    # Offscreen Qt does not discover Windows fonts automatically. Register
    # installed fonts for the design-reference PNG; no font is redistributed.
    if os.name == 'nt':
        font_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('segoeui.ttf', 'seguisb.ttf'):
            path = font_dir / name
            if path.is_file() and QFontDatabase.addApplicationFont(str(path)) < 0:
                raise RuntimeError('Cannot load installed font: ' + str(path))
    sizes = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
    images = []
    for size in sizes:
        data = render('o3-mark-small.svg' if size <= 32 else 'o3-mark.svg', size, size)
        (ASSETS / f'o3-{size}.png').write_bytes(data); images.append(data)
    offset = 6 + 16 * len(sizes)
    headers = []
    for size, data in zip(sizes, images):
        headers.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    (ASSETS / 'o3.ico').write_bytes(struct.pack('<HHH', 0, 1, len(sizes)) + b''.join(headers) + b''.join(images))
    (ASSETS / 'o3-startup-design.png').write_bytes(render('o3-startup-design.svg', 900, 540))
    print('Built 10 PNG sizes, PNG-compressed Windows ICO, and startup design reference.')

if __name__ == '__main__': main()
