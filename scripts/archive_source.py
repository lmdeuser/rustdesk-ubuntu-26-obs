#!/usr/bin/env python3
"""Archive a checked-out RustDesk tag and its pinned hbb_common submodule.

The result is upstream source only, not a complete offline OBS source package.
"""
import argparse
import gzip
from pathlib import Path
import re
import subprocess
import sys
import tarfile

VERSION = re.compile(r'^[0-9]+\.[0-9]+\.[0-9]+$')


def git(directory, *arguments):
    return subprocess.check_output(['git', '-C', str(directory), *arguments], text=True).strip()


def append_archive(destination, directory, prefix):
    process = subprocess.Popen(['git', '-C', str(directory), 'archive', '--format=tar',
                                '--prefix=' + prefix, 'HEAD'], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as source:
            for member in source:
                data = source.extractfile(member) if member.isfile() else None
                destination.addfile(member, data)
    finally:
        process.stdout.close()
        status = process.wait()
    if status:
        raise RuntimeError('git archive failed')


def prepare(checkout, output, version):
    if not VERSION.fullmatch(version):
        raise ValueError('Only numeric stable release versions are accepted')
    if not checkout.is_absolute() or not output.is_absolute():
        raise ValueError('Checkout and output paths must be absolute')
    if git(checkout, 'rev-parse', 'HEAD') != git(checkout, 'rev-parse', f'refs/tags/{version}^{{commit}}'):
        raise ValueError('Checkout does not match the requested release tag')
    if git(checkout, 'status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked source files or submodules have local changes')
    submodule = git(checkout, 'submodule', 'status', '--recursive')
    if any(line.startswith(('-', '+', 'U')) for line in submodule.splitlines()):
        raise ValueError('Submodules are missing, conflicted, or at the wrong revision')
    if len(submodule.splitlines()) != 1 or ' libs/hbb_common ' not in (' ' + submodule + ' '):
        raise ValueError('Unexpected submodule layout; update the archive procedure')
    if not (checkout / 'libs/hbb_common/Cargo.toml').is_file():
        raise ValueError('The pinned hbb_common submodule is missing')
    if not output.parent.is_dir() or output.parent.resolve() != output.parent:
        raise ValueError('Output parent must exist and contain no symlink or traversal')
    created = False
    try:
        with output.open('xb') as raw:
            created = True
            with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|') as archive:
                    prefix = f'rustdesk-{version}/'
                    append_archive(archive, checkout, prefix)
                    append_archive(archive, checkout / 'libs/hbb_common', prefix + 'libs/hbb_common/')
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    parser.add_argument('version')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        prepare(args.checkout, args.output, args.version)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'Source archive failed: {exc}', file=sys.stderr)
        return 1
    print('Prepared upstream source archive:', args.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
