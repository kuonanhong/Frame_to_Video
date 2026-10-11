"""Verify local CPU model fragments and required static resources, offline."""
from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parent.parent
manifest=json.loads((root/'story/models/manifest.json').read_text())
failed=[];count=0
for item in manifest['assets']:
 digest=hashlib.sha256();size=0;parent=Path(item['path']).parent
 parts=item.get('pieces') or [{'name':Path(item['path']).name,'bytes':item['bytes'],'sha256':item['sha256']}]
 for row in parts:
  path=root/'story/models'/parent/row['name'];count+=1
  if not path.is_file():failed.append(str(path.relative_to(root))+' MISSING');continue
  data=path.read_bytes();digest.update(data);size+=len(data)
  if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:failed.append(str(path.relative_to(root))+' HASH/SIZE MISMATCH')
 if size!=item['bytes'] or digest.hexdigest()!=item['sha256']:failed.append(item['path']+' REASSEMBLED MISMATCH')
index=json.loads((root/'offline-files.json').read_text())
for row in index['files']:
 path=root/row['path']
 if not path.is_file() or path.stat().st_size!=row['bytes']:failed.append(row['path']+' MISSING/SIZE MISMATCH')
print(f'Model fragments checked: {count}; static paths: {len(index["files"])}')
if failed:
 print('\n'.join(failed));raise SystemExit(1)
print('PASS: all required local resources and reassembled model hashes match.')
