#!/usr/bin/env python3
"""Check downloaded official model bytes without network access or inference."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent / 'coco-ssd-lite'
manifest = json.loads((root / 'manifest.json').read_text())
model = json.loads((root / 'model.json').read_text())
required = ['model.json'] + [p for group in model['weightsManifest'] for p in group['paths']]
recorded = {row['path']: row for row in manifest['files']}
assert set(recorded) == set(required), 'Missing or unrecorded model shards'
for name in required:
    row = recorded[name]
    data = (root / name).read_bytes()
    assert len(data) == row['bytes'], f'Wrong size: {name}'
    assert hashlib.sha256(data).hexdigest() == row['sha256'], f'Wrong hash: {name}'
assert sum(row['bytes'] for row in recorded.values()) == manifest['totalBytes']
classes = json.loads((root.parent / 'coco-classes.json').read_text())
assert len(classes) == 80 and len({c['id'] for c in classes}) == 80
assert all(c['label'] not in ['water', 'sky', 'cloud', 'hair'] for c in classes)
print(f"Model verified: {len(required)} files, {manifest['totalBytes']:,} bytes, 80 classes")
