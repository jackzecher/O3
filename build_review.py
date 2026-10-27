"""Package a distinct application review without implying native launcher qualification."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parent


def main():
    files = []
    app = ROOT / 'O3/O3_PRODUCT/APP'
    for path in app.rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and 'tests' not in path.parts and path.suffix != '.pyc':
            files.append(path)
    for name in ('review_app.py', 'review_examples.py', 'Open O3 Review.cmd', 'READ_ME_FIRST.txt',
                 'AI_RUNTIME/seed.py', 'AI_RUNTIME/synthetic_examples.json'):
        files.append(ROOT / name)
    records = [{'path': str(path.relative_to(ROOT)).replace('\\', '/'),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}
               for path in sorted(files)]
    manifest = {'build': '3.0.0-alpha3.upgrade1-dev', 'baseline': '3.0.0-alpha3.candidate6',
                'baseline_source': '026a43087fdbe63c835a94bfb40efb5d867c962f',
                'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'scope': 'Application development review. Native launcher and approved runtime/runner qualification pending.',
                'files': records}
    manifest['baseline_zip_sha256'] = '3f47c9e78577463f83554bc0d4b0141c5800add54db3662cf0b6f0baf40e82c4'
    manifest_path = ROOT / 'BUILD_REVIEW_MANIFEST.json'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    destination = ROOT / 'dist/O3_Alpha_3_Upgrade_Review_1.zip'
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files + [manifest_path]:
            archive.write(path, str(path.relative_to(ROOT)))
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        for record in records:
            assert hashlib.sha256(archive.read(record['path'])).hexdigest() == record['sha256']
    print(json.dumps({'archive': str(destination), 'files': len(files), 'bytes': destination.stat().st_size,
                      'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
