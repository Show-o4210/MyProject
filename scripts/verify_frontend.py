"""Verify committed local executable dependencies and stylesheet before deploy."""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
manifest = json.loads((ROOT / 'static/vendor/manifest.json').read_text())
for path, expected in manifest['sha256'].items():
    actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f'Unexpected frontend dependency digest: {path}')
for path in (ROOT / 'templates').glob('*.html'):
    if re.search(r'<script\b[^>]*\bsrc\s*=\s*[\"\']https?://', path.read_text(), re.I):
        raise SystemExit(f'Remote executable script in {path.name}')
print('Local frontend dependency digests verified')
