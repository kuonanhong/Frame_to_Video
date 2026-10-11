#!/usr/bin/env python3
"""Explicit model downloader; generation NEVER calls this script."""
import argparse
import datetime
import json
from pathlib import Path
import re
import sys
from catalog import CATALOG, MODEL_ROOT, model_status, sha256

COMPONENTS = {'feature_extractor', 'safety_checker', 'scheduler', 'text_encoder', 'tokenizer', 'unet', 'vae'}


def wanted(name):
    path = Path(name)
    if len(path.parts) == 1:
        return name == 'model_index.json' or name.lower().startswith(('license', 'readme', 'notice'))
    if path.parts[0] not in COMPONENTS:
        return False
    if name.endswith('.safetensors'):
        return name.endswith('.fp16.safetensors')
    return path.suffix in {'.json', '.txt', '.model'}


def main():
    parser = argparse.ArgumentParser(description='Download a fixed, public model snapshot for local CPU image editing. Several GB per model. Review each model license first.')
    parser.add_argument('--model', choices=CATALOG, required=True)
    parser.add_argument('--revision', help='Optional immutable 40-character upstream commit SHA; default resolves main ONCE and records it')
    parser.add_argument('--skip-installed', action='store_true', help='Reuse a complete local installation without network access')
    parser.add_argument('--verify', action='store_true', help='Offline SHA-256 integrity check, without download')
    args = parser.parse_args()
    if args.revision and not re.fullmatch('[a-fA-F0-9]{40}', args.revision):
        parser.error('--revision must be a full 40-character commit SHA')
    state = model_status(args.model)
    if (args.skip_installed and not args.verify and state['installed']
            and (not args.revision or state.get('revision') == args.revision.lower())):
        print(f'{args.model}: complete local installation already present; no network request.')
        return 0
    if args.verify:
        state = model_status(args.model, verify_hashes=True)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0 if state['installed'] else 1
    try:
        from huggingface_hub import HfApi, snapshot_download
    except ImportError:
        print('Install native_cpu/requirements.txt first.', file=sys.stderr)
        return 1
    spec = CATALOG[args.model]
    print(f"Source: {spec['source']}\nLicense: {spec['license']}\nNo cloud inference is used. Download may require several GB of disk space.")
    info = HfApi().model_info(spec['repo'], revision=args.revision or 'main', files_metadata=True, token=False)
    revision = info.sha
    files = [s.rfilename for s in info.siblings if wanted(s.rfilename)]
    required = {'model_index.json', 'unet/diffusion_pytorch_model.fp16.safetensors',
                'vae/diffusion_pytorch_model.fp16.safetensors', 'text_encoder/model.fp16.safetensors'}
    if not required.issubset(files):
        raise RuntimeError('Upstream layout changed; required Safetensors variant absent. No pickle fallback will be used.')
    path = MODEL_ROOT / args.model
    path.mkdir(parents=True, exist_ok=True)
    (path / 'FRAME_INSTALL.json').unlink(missing_ok=True)
    total = sum(s.size or 0 for s in info.siblings if s.rfilename in files)
    print(f'Revision: {revision}\nSelected files: {len(files)}; upstream reported bytes: {total:,}')
    snapshot_download(repo_id=spec['repo'], revision=revision, local_dir=str(path),
                      allow_patterns=files, max_workers=2, token=False)
    inventory = [{'path': name, 'bytes': (path / name).stat().st_size, 'sha256': sha256(path / name)} for name in files]
    record = {'schema': 1, 'repo': spec['repo'], 'revision': revision, 'variant': 'fp16',
              'runtime_dtype': 'float32', 'downloaded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'files': inventory}
    temporary = path / 'FRAME_INSTALL.json.tmp'
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), 'utf-8')
    temporary.replace(path / 'FRAME_INSTALL.json')
    print('Download and SHA-256 recording complete. Inference has NOT been tested by this download command.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(f'Download failed ({type(exc).__name__}). Check network, disk space, model access and license; rerun to resume.', file=sys.stderr)
        sys.exit(1)
