#!/usr/bin/env python3
"""Remove older marked source sets from a dedicated local cache."""
import argparse
import fcntl
import os
from pathlib import Path
import re
import shutil
import sys

VERSION = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
MARKER = 'rustdesk-obs-source-set-v1\n'


def candidates(root):
    result = []
    for child in root.iterdir():
        match = VERSION.fullmatch(child.name)
        if not match or child.is_symlink() or not child.is_dir():
            continue
        marker = child / '.rustdesk-source-set'
        if marker.is_symlink() or not marker.is_file():
            continue
        if marker.read_text(encoding='utf-8') != MARKER:
            continue
        result.append((tuple(map(int, match.groups())), child))
    return [path for _, path in sorted(result, reverse=True)]


def prune(root, apply=False):
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('Cache must be an existing absolute directory, not a symlink')
    lock_path = root / '.retention.lock'
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old = candidates(root)[2:]
        if apply:
            for path in old:
                shutil.rmtree(path)
        return old


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('--apply', action='store_true', help='delete eligible old sets')
    args = parser.parse_args()
    try:
        for path in prune(args.cache, args.apply):
            print(('removed ' if args.apply else 'would remove ') + str(path))
    except (OSError, ValueError) as exc:
        print(f'Retention failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
