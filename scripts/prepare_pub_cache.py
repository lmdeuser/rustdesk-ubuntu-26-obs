#!/usr/bin/env python3
"""Prepare an offline Dart pub cache from verified package sources."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
from urllib.parse import urlparse

import fetch_pub_archives
import fetch_pub_git

MAX_FILES = 100000
MAX_UNPACKED = 1024 * 1024 * 1024


def unpack(archive_path, destination):
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) > MAX_FILES or sum(m.size for m in members) > MAX_UNPACKED:
            raise ValueError('Package archive exceeds extraction limits')
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError('Unsafe member in package archive')
            if member.name in seen:
                raise ValueError('Duplicate member in package archive')
            seen.add(member.name)
        archive.extractall(destination, members=members, filter='data')


def prepare(lockfile, archives, git_sources, output):
    for directory in (archives, git_sources):
        if not directory.is_absolute() or not directory.is_dir() or directory.resolve() != directory:
            raise ValueError('Source directories must be absolute paths without symlinks')
    if not output.is_absolute() or output.parent.resolve() != output.parent:
        raise ValueError('Output must have an absolute parent path without symlinks')
    if output.exists() or output.is_symlink():
        raise FileExistsError('Output path already exists')
    with lockfile.open(encoding='utf-8') as lock:
        hosted = fetch_pub_archives.package_records(lock)
    with lockfile.open(encoding='utf-8') as lock:
        git_packages = fetch_pub_git.records(lock)
    output.mkdir(mode=0o700)
    try:
        hosted_dir = output / 'hosted/pub.dev'
        hash_dir = output / 'hosted-hashes/pub.dev'
        git_cache = output / 'git/cache'
        for directory in (hosted_dir, hash_dir, git_cache):
            directory.mkdir(parents=True, exist_ok=True)
        for name, version, digest in hosted:
            package = f'{name}-{version}'
            source = archives / (package + '.tar.gz')
            if source.is_symlink() or fetch_pub_archives.digest_file(source) != digest:
                raise ValueError('Package source checksum mismatch: ' + package)
            destination = hosted_dir / package
            destination.mkdir()
            unpack(source, destination)
            (hash_dir / (package + '.sha256')).write_text(digest, encoding='ascii')
        for name, url, commit in git_packages:
            source = git_sources / f'{name}-{commit}.git'
            if source.is_symlink() or not source.is_dir():
                raise ValueError('Missing Git source: ' + name)
            actual = fetch_pub_git.run('--git-dir', str(source), 'rev-parse', '--verify', 'refs/heads/locked^{commit}')
            if actual != commit:
                raise ValueError('Git source commit mismatch: ' + name)
            repo_name = Path(urlparse(url).path).name.removesuffix('.git')
            repo_key = hashlib.sha1(url.encode('utf-8')).hexdigest()
            bare = git_cache / f'{repo_name}-{repo_key}'
            shutil.copytree(source, bare, symlinks=False)
            revision = output / 'git' / f'{repo_name}-{commit}'
            fetch_pub_git.run('-c', 'core.logAllRefUpdates=false', 'clone', '--no-checkout', '--no-hardlinks', '--', str(bare), str(revision))
            fetch_pub_git.run('-C', str(revision), '-c', 'core.logAllRefUpdates=false', 'checkout', '--detach', commit)
            fetch_pub_git.run('-C', str(revision), 'remote', 'set-url', 'origin', url)
            logs = revision / '.git/logs'
            if logs.exists():
                shutil.rmtree(logs)
    except BaseException:
        shutil.rmtree(output)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lockfile', type=Path)
    parser.add_argument('archives', type=Path)
    parser.add_argument('git_sources', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        prepare(args.lockfile, args.archives, args.git_sources, args.output)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(f'Pub cache preparation failed: {exc}', file=sys.stderr)
        return 1
    print('Prepared pub cache; offline resolution still needs OBS verification.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
