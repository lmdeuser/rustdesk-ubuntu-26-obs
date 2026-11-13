#!/usr/bin/env python3
"""Download and verify pub.dev source archives named in a Dart lockfile."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import re
import sys
import urllib.request

try:
    import yaml
except ImportError:
    sys.exit('Install the Python 3 YAML parser to read the upstream lockfile.')

NAME = re.compile(r'^[_a-zA-Z][_a-zA-Z0-9]*$')
VERSION = re.compile(r'^[0-9][0-9A-Za-z.+-]*$')
HASH = re.compile(r'^[0-9a-f]{64}$')
MAX_SIZE = 100 * 1024 * 1024


def package_records(lock):
    packages = yaml.safe_load(lock)['packages']
    result = []
    for name, entry in packages.items():
        if entry['source'] != 'hosted':
            continue
        info = entry['description']
        version, digest = entry['version'], info['sha256']
        if (not NAME.fullmatch(name) or name != info['name'] or
                not VERSION.fullmatch(version) or not HASH.fullmatch(digest) or
                info['url'] != 'https://pub.dev'):
            raise ValueError('Invalid or unsupported hosted package entry: ' + str(name))
        result.append((name, version, digest))
    return result


def digest_file(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def download(cache, record):
    name, version, digest = record
    target = cache / f'{name}-{version}.tar.gz'
    if target.is_symlink():
        raise ValueError('Refusing symlink in archive cache')
    if target.exists():
        if digest_file(target) != digest:
            raise ValueError('Existing archive has an unexpected checksum: ' + target.name)
        return
    temporary = cache / (target.name + '.part')
    url = f'https://pub.dev/api/archives/{name}-{version}.tar.gz'
    created = False
    try:
        with temporary.open('xb') as out:
            created = True
            with urllib.request.urlopen(url, timeout=45) as response:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_SIZE:
                        raise ValueError('Package archive exceeds the size limit: ' + name)
                    out.write(chunk)
        if digest_file(temporary) != digest:
            raise ValueError('Downloaded archive has an unexpected checksum: ' + name)
        os.replace(temporary, target)
    finally:
        if created:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lockfile', type=Path)
    parser.add_argument('cache', type=Path)
    args = parser.parse_args()
    try:
        if not args.cache.is_absolute() or not args.cache.is_dir() or args.cache.resolve() != args.cache:
            raise ValueError('Cache must be an existing absolute directory without symlinks')
        with args.lockfile.open(encoding='utf-8') as source:
            records = package_records(source)
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(lambda item: download(args.cache, item), records))
        print(f'Verified {len(records)} hosted pub.dev package archives.')
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f'Package download failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
