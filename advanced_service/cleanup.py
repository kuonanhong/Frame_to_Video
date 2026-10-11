#!/usr/bin/env python3
"""Remove retained expert job data only, after stopping the local server."""
import argparse
from pathlib import Path
import re
import shutil
from registry import RUNTIME

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delete',action='store_true',help='Delete local uploads, outputs and logs from previous expert jobs')
    args = parser.parse_args()
    root = RUNTIME/'jobs'
    jobs = [path for path in root.iterdir() if path.is_dir() and not path.is_symlink() and
        re.fullmatch('[a-f0-9]{32}',path.name)] if root.exists() else []
    if not args.delete:
        print(f'{len(jobs)} job directories found. Stop the server, then pass --delete to remove their data.')
        return
    for path in jobs:
        shutil.rmtree(path)
    print(f'Deleted {len(jobs)} job directories. Installed models and environments were retained.')

if __name__ == '__main__':
    main()
