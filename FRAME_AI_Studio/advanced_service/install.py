#!/usr/bin/env python3
"""Explicit CLI-only installation. No downloads or pip operations are exposed over HTTP."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import venv

from registry import BASE, RUNTIME, EXPERTS, expert_dir, python_path
from download_support import atomic_json, build_plan, show_plan, safe_path

COMPONENTS = {'text_encoder','text_encoder_2','text_encoder_3','tokenizer','tokenizer_2',
    'tokenizer_3','unet','vae','scheduler','transformer','safety_checker','feature_extractor'}

def selected_files(expert, spec, files):
    if expert == 'qwen-text':
        result = [name for name in files if name in spec['files']]
    elif expert == 'liveportrait':
        result = [name for name in files if name.startswith(('liveportrait/','insightface/'))
            and name.endswith(('.pth','.onnx','.json','.pkl'))]
    else:
        result = []
        for name in files:
            parts = name.split('/')
            if any(token in name.lower() for token in ('.fp16.','.bf16.','.fp32.')):
                continue
            if len(parts) == 1:
                if name in {'model_index.json','config.json'} or (spec['name'] == 'controlnet' and name == 'diffusion_pytorch_model.safetensors'):
                    result.append(name)
            elif parts[0] in COMPONENTS and name.endswith(('.json','.txt','.model','.safetensors','.tiktoken','.jinja')):
                result.append(name)
    # Keep upstream licensing and model cards alongside the weights.
    result += [name for name in files if '/' not in name and
        (name.lower().startswith(('license','notice')) or name.lower() == 'readme.md')]
    if not any(name.endswith(('.safetensors','.gguf','.pth','.onnx')) for name in result):
        raise RuntimeError(f'No usable model weights selected from {spec["repo"]}')
    return sorted(set(result))

def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda:file.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()

def download(expert, revision_overrides, weights_only=False, refresh=False, plan_only=False):
    from huggingface_hub import snapshot_download
    home = expert_dir(expert)
    plan = build_plan(expert, revision_overrides, refresh=refresh, selector=selected_files)
    show_plan(expert, plan, check_space=not plan_only)
    if plan_only:
        print('Plan only: no model weights downloaded.', flush=True)
        return
    records = []
    for model in plan['models']:
        target = home/'models'/model['name']
        files = [item['path'] for item in model['files']]
        print(f'Downloading {model["repo"]}@{model["revision"]}: {len(files)} selected files', flush=True)
        # local_dir keeps HF resume metadata under .cache. Repeating this command
        # reuses completed files and resumes interrupted HTTP transfers.
        snapshot_download(repo_id=model['repo'], revision=model['revision'], allow_patterns=files,
            local_dir=str(target), token=False, max_workers=2)
        for item in model['files']:
            path = safe_path(home, 'models/'+model['name']+'/'+item['path'])
            if not path.is_file() or path.stat().st_size != item['bytes']:
                raise RuntimeError(f'Missing or wrong-size model file: {item["path"]}')
            actual = sha256(path)
            if item.get('sha256') and actual != item['sha256']:
                raise RuntimeError(f'Upstream SHA-256 mismatch: {item["path"]}. '
                    'Remove this damaged file and its matching .cache/huggingface/download metadata, then retry.')
        records.append(dict(name=model['name'], repo=model['repo'], revision=model['revision'], files=files))
    source_record = None
    if expert == 'liveportrait' and not weights_only:
        source = home/'source'
        repo = EXPERTS[expert]['source']
        revision = revision_overrides.get('source')
        if not revision:
            output = subprocess.check_output(['git','ls-remote',repo,'HEAD'],text=True)
            revision = output.split()[0]
        if not re.fullmatch('[a-f0-9]{40}',revision):
            raise RuntimeError('LivePortrait source must be pinned to a commit SHA')
        if not (source/'.git').exists():
            source.mkdir(parents=True,exist_ok=True)
            subprocess.run(['git','init',str(source)],check=True)
            subprocess.run(['git','-C',str(source),'remote','add','origin',repo],check=True)
        subprocess.run(['git','-C',str(source),'fetch','--depth','1','origin',revision],check=True)
        subprocess.run(['git','-C',str(source),'checkout','--detach',revision],check=True)
        weights = source/'pretrained_weights'
        # Real directory also works on Windows without symlink privileges. Hard links
        # avoid duplicating weight bytes on a single volume; copy is a safe fallback.
        for path in (home/'models'/'pretrained_weights').rglob('*'):
            if not path.is_file() or '.cache' in path.parts:
                continue
            target = weights/path.relative_to(home/'models'/'pretrained_weights')
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                target.unlink()
            try:
                os.link(path,target)
            except OSError:
                shutil.copy2(path,target)
        source_record = dict(repo=repo,revision=revision)
    files = []
    for model in records:
        for name in model['files']:
            path = home/'models'/model['name']/name
            files.append(dict(path=str(path.relative_to(home)),bytes=path.stat().st_size,sha256=sha256(path)))
    if source_record:
        paths = subprocess.check_output(['git','-C',str(home/'source'),'ls-files','-z']).split(b'\0')
        for name in filter(None,paths):
            path = home/'source'/os.fsdecode(name)
            if path.is_file():
                files.append(dict(path=str(path.relative_to(home)),bytes=path.stat().st_size,sha256=sha256(path)))
        for path in (home/'source'/'pretrained_weights').rglob('*'):
            if path.is_file() and '.cache' not in path.parts:
                files.append(dict(path=str(path.relative_to(home)),bytes=path.stat().st_size,sha256=sha256(path)))
    manifest = dict(schema=1,expert=expert,created=time.time(),models=records,source=source_record,
        install_mode="weights-only" if weights_only else "runtime",
        files=files,python=sys.version,platform=platform.platform(),requirements_sha256=sha256(BASE/'requirements'/EXPERTS[expert]['requirements']))
    # A download-only pass must not downgrade an already-working runtime manifest.
    destination = home/('weights-manifest.json' if weights_only else 'install-manifest.json')
    atomic_json(destination, manifest)
    print('Wrote immutable model revisions and SHA-256 file manifest.',flush=True)

def verify(expert):
    home = expert_dir(expert)
    path = home/'weights-manifest.json'
    if not path.is_file():
        path = home/'install-manifest.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('expert') != expert or not manifest.get('files'):
        raise RuntimeError('Incomplete verification manifest')
    for item in manifest['files']:
        path = safe_path(home, item['path'])
        if not path.is_relative_to(home) or not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
            raise RuntimeError(f'Missing or modified installed file: {item["path"]}')
    print(f'Verified SHA-256 for {len(manifest["files"])} files.',flush=True)

def runtime_block_reason(expert):
    profile = EXPERTS[expert]['requirements']
    if profile in {'modern.txt','liveportrait.txt'} and platform.system() == 'Darwin' and platform.machine().lower() in {'x86_64','amd64'}:
        return ('Intel macOS has no official torch 2.6 wheel for this pinned runtime. '
                'Weights can be downloaded here; running this v5 profile requires a separate compatible host.')
    return None

def downloader_python():
    folder = RUNTIME/'_downloader'/'venv'
    python = folder/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(folder)
    probe = subprocess.run([str(python), '-c',
        'import importlib.metadata as m; assert m.version("huggingface-hub") == "0.36.0"'],
        capture_output=True)
    if probe.returncode:
        subprocess.run([str(python), '-m', 'pip', 'install', '--disable-pip-version-check',
            'huggingface-hub==0.36.0'], check=True)
    return python

def download_environment():
    env = os.environ.copy()
    env.update(HF_HUB_DISABLE_XET='1', HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
        HF_HUB_DOWNLOAD_TIMEOUT='120', HF_HUB_ETAG_TIMEOUT='30')
    return env

def worker_command(python, args, revisions):
    command = [str(python), str(BASE/'install.py'), args.expert, '--download-worker']
    for name in ('weights_only', 'plan', 'refresh_plan'):
        if getattr(args, name):
            command.append('--'+name.replace('_','-'))
    for key, value in revisions.items():
        command += ['--revision', key+'='+value]
    return command

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('expert',choices=list(EXPERTS))
    parser.add_argument('--download',action='store_true',help='Install runtime + weights; unsupported Intel Mac automatically downloads weights only')
    parser.add_argument('--weights-only',action='store_true',help='Download weights without Torch or the inference runtime; may be used alone')
    parser.add_argument('--plan',action='store_true',help='Query model metadata and disk estimate only (may install the small download client)')
    parser.add_argument('--refresh-plan',action='store_true',help='Explicitly resolve upstream revisions again instead of resuming the saved plan')
    parser.add_argument('--verify',action='store_true',help='Rehash downloaded weights offline; does not download')
    parser.add_argument('--revision',action='append',default=[],metavar='COMPONENT=SHA',help='Pin model component or source to an exact upstream commit')
    parser.add_argument('--download-worker',action='store_true',help=argparse.SUPPRESS)
    args = parser.parse_args()
    revisions = {}
    for item in args.revision:
        key,sep,value = item.partition('=')
        allowed = {x['name'] for x in EXPERTS[args.expert]['repos']} | {'source'}
        if not sep or key not in allowed or not re.fullmatch('[a-f0-9]{40}',value):
            parser.error('--revision requires a known COMPONENT=40-character-commit-SHA')
        revisions[key] = value
    if args.verify:
        if args.download or args.weights_only or args.plan or args.refresh_plan:
            parser.error('--verify must be used alone')
        verify(args.expert)
        return
    if args.download_worker:
        download(args.expert,revisions,weights_only=args.weights_only,refresh=args.refresh_plan,plan_only=args.plan)
        return
    if not (args.download or args.weights_only or args.plan):
        parser.error('No changes made. Pass --plan for sizes, --weights-only for weights, or --download to install.')
    if not (3,10) <= sys.version_info[:2] <= (3,12):
        parser.error('Use Python 3.10–3.12. Python 3.11 is recommended for these pinned profiles.')
    profile = EXPERTS[args.expert]['requirements']
    blocked = runtime_block_reason(args.expert)
    if blocked and args.download and not args.plan:
        args.weights_only = True
        print('DOWNLOAD-ONLY / 僅下載權重：'+blocked, flush=True)
    if args.weights_only or args.plan:
        python = downloader_python()
        subprocess.run(worker_command(python, args, revisions), check=True, env=download_environment())
        if not args.plan:
            print('WEIGHTS READY / 權重下載完成。Inference runtime was not installed or tested.\n'
                  'Download completion alone does not enable generation on this computer.\n'
                  f'Offline verification: python3.11 advanced_service/install.py {args.expert} --verify', flush=True)
        return
    home = expert_dir(args.expert)
    home.mkdir(parents=True,exist_ok=True)
    python = python_path(args.expert)
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(home/'venv')
    env = os.environ.copy()
    if args.expert == 'qwen-text':
        env['CMAKE_ARGS'] = '-DGGML_CUDA=OFF -DGGML_METAL=OFF -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF'
        env['CMAKE_BUILD_PARALLEL_LEVEL'] = '2'
    requirements = BASE/'requirements'/profile
    if args.expert != 'qwen-text' and platform.system() in {'Linux','Windows'}:
        # Explicit CPU wheels avoid downloading NVIDIA runtime packages on CPU-only hosts.
        torch_packages = [line for line in requirements.read_text().splitlines()
            if line.startswith(('torch==','torchvision=='))]
        subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check',
            '--index-url','https://download.pytorch.org/whl/cpu',*torch_packages],check=True,env=env)
    subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(requirements)],check=True,env=env)
    subprocess.run(worker_command(python, args, revisions),check=True,env=download_environment())
    result = subprocess.run([str(python),str(BASE/'worker.py'),'--check',args.expert],capture_output=True,text=True)
    report = json.loads(result.stdout) if result.returncode == 0 else dict(ready=False,missing=['Worker import check failed'])
    (home/'runtime-check.json').write_text(json.dumps(report,indent=2))
    frozen = subprocess.check_output([str(python),'-m','pip','freeze'],text=True)
    (home/'requirements-resolved.txt').write_text(frozen)
    print(json.dumps(report,indent=2))
    if not report.get('ready'):
        raise SystemExit('Weights downloaded, but dependencies are blocked. Resolve the reported issue before running.')
    print(f'Installed {args.expert}. Start advanced_service/server.py and open its loopback URL.')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('Download interrupted. Keep the model/cache folders and repeat the same command to resume.')
    except (OSError,RuntimeError,ValueError,KeyError,TypeError,subprocess.CalledProcessError) as exc:
        raise SystemExit(f'Installation stopped: {exc}')
