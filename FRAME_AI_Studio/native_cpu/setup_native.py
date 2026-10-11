#!/usr/bin/env python3
"""Create an isolated, pinned CPU environment; optionally download and launch.

Run with Python 3.11. All subprocess arguments are arrays; no shell activation is
required, including Windows paths containing spaces.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent


def torch_install(system=None, machine=None):
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == 'Darwin' and machine in {'x86_64', 'amd64'}:
        return ['torch==2.2.2']
    if system == 'Darwin' and machine in {'arm64', 'aarch64'}:
        return ['torch==2.6.0']
    if system in {'Linux', 'Windows'} and machine in {'x86_64', 'amd64'}:
        return ['torch==2.6.0', '--index-url', 'https://download.pytorch.org/whl/cpu']
    raise RuntimeError(f'No verified wheel selection for {system}/{machine}. See README_ZH.md.')


def execute(args, **kwargs):
    print('+ ' + subprocess.list2cmdline([str(arg) for arg in args]), flush=True)
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-dir', type=Path, default=PROJECT / '.venv-native')
    parser.add_argument('--model-dir', type=Path, default=ROOT / 'models')
    parser.add_argument('--model', choices=['sd-turbo', 'instruct-pix2pix', 'sd-inpaint'], action='append', default=[])
    parser.add_argument('--repair', action='store_true', help='Reinstall/check pinned packages in an existing environment')
    parser.add_argument('--launch', action='store_true', help='Launch the loopback web UI after installation')
    parser.add_argument('--port', type=int, default=8787)
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 11):
        parser.error('Use Python 3.11: macOS/Linux python3.11; Windows py -3.11.')
    if not 1024 <= args.port <= 65535:
        parser.error('--port must be 1024–65535')
    torch_args = torch_install()
    environment = args.env_dir.expanduser().resolve()
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    marker = environment / 'FRAME_SETUP.json'
    expected = {'schema': 1, 'python': '3.11', 'system': platform.system(),
                'machine': platform.machine(), 'torch_install': torch_args,
                'requirements': (ROOT / 'requirements.txt').read_text('utf-8')}
    try:
        current = json.loads(marker.read_text('utf-8'))
    except (OSError, ValueError):
        current = None
    if not python.is_file():
        print(f'Creating isolated environment: {environment}', flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    if args.repair or current != expected:
        execute([python, '-m', 'pip', 'install', '--upgrade', 'pip'])
        execute([python, '-m', 'pip', 'install', *torch_args])
        execute([python, '-m', 'pip', 'install', '-r', ROOT / 'requirements.txt'])
        execute([python, ROOT / 'check_runtime.py'])
        marker.write_text(json.dumps(expected, indent=2), 'utf-8')
    else:
        execute([python, ROOT / 'check_runtime.py'])
    child_env = os.environ.copy()
    child_env['FRAME_NATIVE_MODEL_DIR'] = str(args.model_dir.expanduser().resolve())
    for model in args.model:
        execute([python, ROOT / 'fetch_models.py', '--model', model, '--skip-installed'], env=child_env)
    if args.launch:
        execute([python, ROOT / 'server.py', '--port', str(args.port)], cwd=PROJECT, env=child_env)
    else:
        print(f'Ready. Launch: {subprocess.list2cmdline([str(python), str(ROOT / "server.py")])}', flush=True)
        if args.model_dir != ROOT / 'models':
            print(f'Keep FRAME_NATIVE_MODEL_DIR set to {child_env["FRAME_NATIVE_MODEL_DIR"]} when launching manually.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Setup failed: {exc}', file=sys.stderr)
        sys.exit(1)
