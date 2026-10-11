"""Platform-independent weight download plans; no Torch or other ML imports."""
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import time

from registry import expert_dir, EXPERTS

SHA = re.compile(r'^[a-f0-9]{40}$')

def atomic_json(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
    temporary.replace(path)

def safe_path(home, name):
    """Reject unsafe repository names and symlinks that leave the expert home."""
    relative = PurePosixPath(name)
    if not name or relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise ValueError(f'Unsafe model path: {name}')
    result = (home / name).resolve()
    if not result.is_relative_to(home.resolve()):
        raise ValueError(f'Model path leaves expert directory: {name}')
    return result

def validate_plan(expert, plan):
    if plan.get('schema') != 1 or plan.get('expert') != expert:
        raise ValueError('Wrong download plan schema/expert; use --refresh-plan')
    expected = {s['name']: s['repo'] for s in EXPERTS[expert]['repos']}
    models = plan.get('models', [])
    if len(models) != len(expected) or {m['name'] for m in models} != set(expected):
        raise ValueError('Incomplete download plan; use --refresh-plan')
    for model in models:
        if model['repo'] != expected[model['name']] or not SHA.fullmatch(model['revision']):
            raise ValueError('Unexpected model repository/revision in download plan')
        if not model['files']:
            raise ValueError('Empty download plan')
        for item in model['files']:
            safe_path(expert_dir(expert), 'models/' + model['name'] + '/' + item['path'])
            if not isinstance(item['bytes'], int) or item['bytes'] < 0:
                raise ValueError('Unknown file size in download plan')
            if item.get('sha256') and not re.fullmatch('[a-f0-9]{64}', item['sha256']):
                raise ValueError('Invalid upstream SHA-256 in download plan')
    return plan

def build_plan(expert, revisions, refresh=False, api=None, selector=None):
    """Persist exact commits before transfer. Retry reuses them unless explicitly refreshed."""
    home = expert_dir(expert)
    home.mkdir(parents=True, exist_ok=True)
    path = home / 'download-plan.json'
    requested = {k:v for k,v in revisions.items() if k != 'source'}
    if path.is_file() and not refresh:
        cached = validate_plan(expert, json.loads(path.read_text(encoding='utf-8')))
        if all(next(m['revision'] for m in cached['models'] if m['name'] == k) == v for k,v in requested.items()):
            print('Reusing pinned download-plan.json (no change to upstream revisions).', flush=True)
            return cached
    if api is None:
        from huggingface_hub import HfApi
        api = HfApi(token=False)
    if selector is None:
        from install import selected_files
        selector = selected_files
    models = []
    for spec in EXPERTS[expert]['repos']:
        info = api.model_info(spec['repo'], revision=requested.get(spec['name'], 'main'),
                              files_metadata=True, token=False)
        files = selector(expert, spec, [s.rfilename for s in info.siblings])
        metadata = {s.rfilename:s for s in info.siblings}
        rows = []
        for name in files:
            item = metadata[name]
            lfs = getattr(item, 'lfs', None)
            checksum = lfs.get('sha256') if isinstance(lfs, dict) else getattr(lfs, 'sha256', None)
            rows.append(dict(path=name, bytes=item.size, sha256=checksum))
        models.append(dict(name=spec['name'], repo=spec['repo'], revision=info.sha, files=rows))
    plan = validate_plan(expert, dict(schema=1, expert=expert, created=time.time(), models=models))
    atomic_json(path, plan)
    return plan

def show_plan(expert, plan, check_space=False):
    home = expert_dir(expert)
    total = remaining = count = 0
    for model in plan['models']:
        print(f'{model["repo"]}@{model["revision"]}', flush=True)
        for item in model['files']:
            path = safe_path(home, 'models/' + model['name'] + '/' + item['path'])
            total += item['bytes']
            count += 1
            if not path.is_file() or path.stat().st_size != item['bytes']:
                remaining += item['bytes']
    free = shutil.disk_usage(home).free
    print(f'{count} selected files; total {total / 1e9:.3f} GB ({total / 2**30:.3f} GiB).\n'
          f'Estimated remaining: {remaining / 1e9:.3f} GB; free disk: {free / 1e9:.3f} GB.\n'
          f'Destination: {home / "models"}', flush=True)
    if check_space and remaining + 256*1024*1024 > free:
        raise RuntimeError('Insufficient free disk. Free space or set FRAME_EXPERT_HOME to another drive. '
                           'This conservative check does not subtract incomplete cache files.')
    return dict(files=count, total_bytes=total, remaining_bytes=remaining, free_bytes=free)
