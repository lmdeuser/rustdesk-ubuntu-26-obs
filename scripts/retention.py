#!/usr/bin/env python3
"""Remove older marked source sets from a dedicated local cache and stale OBS checkout files."""
import argparse
import fcntl
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable

VERSION = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
MARKER = 'rustdesk-obs-source-set-v1\n'
OBS_ARTIFACT = re.compile(
    r'^rustdesk_([0-9]+\.[0-9]+\.[0-9]+)(?:-[A-Za-z0-9.~+-]+)?\.(?:dsc|debian\.tar\.[a-z0-9]+|orig(?:-[a-z0-9-]+)?\.tar\.[a-z0-9]+)$'
)


def parse_version(text: str) -> tuple[int, int, int] | None:
    """Return a comparable integer tuple for a numeric X.Y.Z version string."""
    match = VERSION.fullmatch(text.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def candidates(root: Path) -> list[Path]:
    """List valid marked version directories ordered newest-first."""
    result = []
    for child in root.iterdir():
        parsed = parse_version(child.name)
        if not parsed or child.is_symlink() or not child.is_dir():
            continue
        marker = child / '.rustdesk-source-set'
        if marker.is_symlink() or not marker.is_file():
            continue
        if marker.read_text(encoding='utf-8') != MARKER:
            continue
        result.append((parsed, child))
    return [path for _, path in sorted(result, reverse=True)]


def prune(
    root: Path,
    apply: bool = False,
    keep: int = 2,
    protect: Iterable[str] = (),
) -> list[Path]:
    """Prune older marked release sets under root, keeping at least ``keep`` newest sets.

    Any version directory whose name appears in ``protect`` is never deleted even if it
    falls outside the top ``keep`` slots (for example an active in-flight build).
    """
    if keep < 0:
        raise ValueError('keep must be non-negative')
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError('Cache must be an existing absolute directory, not a symlink')
    protected = set(protect)
    lock_path = root / '.retention.lock'
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(lock_path, flags, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        all_sets = candidates(root)
        old = [path for path in all_sets[keep:] if path.name not in protected]
        if apply:
            for path in old:
                shutil.rmtree(path)
        return old


def prune_obs_package_files(
    checkout_dir: Path,
    active_files: Iterable[str],
    apply: bool = False,
) -> list[Path]:
    """Identify or delete stale Debian source artifacts inside an OBS package checkout."""
    if not checkout_dir.is_dir() or checkout_dir.is_symlink():
        raise ValueError('OBS checkout directory must exist and not be a symlink')
    keep_names = set(active_files)
    stale: list[Path] = []
    for child in sorted(checkout_dir.iterdir()):
        if child.name == '.osc' or child.is_dir() or child.is_symlink():
            continue
        if OBS_ARTIFACT.fullmatch(child.name) and child.name not in keep_names:
            stale.append(child)
    if apply:
        for path in stale:
            path.unlink()
    return stale


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('--apply', action='store_true', help='delete eligible old sets')
    parser.add_argument('--keep', type=int, default=2, help='number of newest sets to retain')
    parser.add_argument(
        '--protect',
        action='append',
        default=[],
        help='version directory name to exclude from pruning',
    )
    args = parser.parse_args()
    try:
        for path in prune(args.cache, apply=args.apply, keep=args.keep, protect=args.protect):
            print(('removed ' if args.apply else 'would remove ') + str(path))
    except (OSError, ValueError) as exc:
        print(f'Retention failed: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
