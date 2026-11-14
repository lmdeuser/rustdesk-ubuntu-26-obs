#!/usr/bin/env python3
"""Fetch lockfile-pinned public Git dependencies without building them."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

try:
    import yaml
except ImportError:
    sys.exit('Install the Python 3 YAML parser to read the upstream lockfile.')

NAME = re.compile(r'^[_a-zA-Z][_a-zA-Z0-9]*$')
URL = re.compile(r'^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')


def records(lock):
    result = []
    for name, entry in yaml.safe_load(lock)['packages'].items():
        if entry['source'] != 'git':
            continue
        info = entry['description']
        url, commit = info['url'], info['resolved-ref']
        if not NAME.fullmatch(name) or not URL.fullmatch(url) or not COMMIT.fullmatch(commit):
            raise ValueError('Invalid Git dependency: ' + str(name))
        result.append((name, url, commit))
    return result


def run(*args):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_CONFIG_GLOBAL='/dev/null', GIT_CONFIG_SYSTEM='/dev/null')
    return subprocess.run(['git', *args], env=env, check=True, timeout=120,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def fetch(cache, entry):
    name, url, commit = entry
    target = cache / f'{name}-{commit}.git'
    if target.is_symlink():
        raise ValueError('Refusing symlink in Git dependency cache')
    if target.exists():
        actual = run('--git-dir', str(target), 'rev-parse', '--verify', f'{commit}^{{commit}}')
        if actual != commit:
            raise ValueError('Cached Git dependency does not match its commit')
        run('--git-dir', str(target), 'update-ref', 'refs/heads/locked', commit)
        return
    temporary = cache / (target.name + '.part')
    temporary.mkdir(mode=0o755)
    try:
        temporary.chmod(0o755)
        run('init', '--bare', str(temporary))
        run('--git-dir', str(temporary), 'fetch', '--no-tags', '--depth=1', url, commit)
        actual = run('--git-dir', str(temporary), 'rev-parse', '--verify', 'FETCH_HEAD^{commit}')
        if actual != commit:
            raise ValueError('Fetched Git dependency does not match its commit')
        run('--git-dir', str(temporary), 'update-ref', 'refs/heads/locked', commit)
        temporary.rename(target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lockfile', type=Path)
    parser.add_argument('cache', type=Path)
    args = parser.parse_args()
    try:
        if not args.cache.is_absolute() or not args.cache.is_dir() or args.cache.resolve() != args.cache:
            raise ValueError('Cache must be an existing absolute directory without symlinks')
        with args.lockfile.open(encoding='utf-8') as source:
            dependencies = records(source)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda item: fetch(args.cache, item), dependencies))
        print(f'Fetched and verified {len(dependencies)} pinned Git dependencies.')
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError, subprocess.SubprocessError) as exc:
        print(f'Git dependency fetch failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
