#!/usr/bin/env python3
"""Automate upstream release watching, OBS source assembly, staging builds, and APT promotion."""
import argparse
from dataclasses import dataclass
import email.utils
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Callable, Sequence
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_script(name: str):
    if name in sys.modules:
        return sys.modules[name]
    path = SCRIPTS_DIR / f'{name}.py'
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Unable to load sibling script: {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


inspect_upstream = _load_script('inspect_upstream')
archive_source = _load_script('archive_source')
fetch_pub_archives = _load_script('fetch_pub_archives')
fetch_pub_git = _load_script('fetch_pub_git')
prepare_pub_cache = _load_script('prepare_pub_cache')
retention = _load_script('retention')

SEMVER_RE = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')
DSC_FILE_RE = re.compile(r'^rustdesk_([A-Za-z0-9.+~-]+)\.dsc$')
DEFAULT_OBS_API = 'https://api.opensuse.org'
DEFAULT_STAGING_PROJECT = 'home:dwolfF:rustdesk:staging'
DEFAULT_PRODUCTION_PROJECT = 'home:dwolfF:rustdesk'
DEFAULT_PACKAGE = 'rustdesk'
DEFAULT_REPOSITORY = 'xUbuntu_26.04'
DEFAULT_ARCH = 'x86_64'
DEFAULT_APT_BASE = 'https://download.opensuse.org/repositories/home:/dwolfF:/rustdesk/xUbuntu_26.04'
DEFAULT_REVISION_SUFFIX = '-0ubuntu1~obs1'
TERMINAL_FAIL_STATES = {'failed', 'broken', 'unresolvable', 'excluded'}
PENDING_STATES = {'scheduled', 'building', 'dispatching', 'blocked', 'finished', 'signing'}


@dataclass(frozen=True)
class PublisherConfig:
    """Configuration for the OBS watcher, builder, and promoter pipeline."""

    repo_root: Path
    work_root: Path
    staging_project: str = DEFAULT_STAGING_PROJECT
    production_project: str = DEFAULT_PRODUCTION_PROJECT
    package: str = DEFAULT_PACKAGE
    repository: str = DEFAULT_REPOSITORY
    arch: str = DEFAULT_ARCH
    obs_api: str = DEFAULT_OBS_API
    apt_base_url: str = DEFAULT_APT_BASE
    poll_interval: int = 30
    poll_timeout: int = 3600


def disk_tmpdir(work_root: Path) -> Path:
    """Ensure a disk-backed TMPDIR exists under work_root instead of /tmp."""
    tmp = work_root / 'tmp'
    tmp.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(tmp)
    return tmp


def normalize_upstream_version(tag: str) -> str:
    """Normalize an upstream tag such as ``1.5.3`` or ``v1.5.3`` to X.Y.Z."""
    cleaned = tag.strip().lstrip('v')
    if not SEMVER_RE.fullmatch(cleaned):
        raise ValueError(f'Unsupported upstream release version: {tag!r}')
    return cleaned


def base_version_from_debian(deb_version: str) -> str:
    """Extract the upstream X.Y.Z component from a Debian revision string."""
    head = deb_version.strip().split('-', 1)[0].split('~', 1)[0]
    return normalize_upstream_version(head)


def compare_versions(left: str, right: str) -> int:
    """Compare two X.Y.Z version strings numerically (-1, 0, or +1)."""
    lt = tuple(int(x) for x in normalize_upstream_version(left).split('.'))
    rt = tuple(int(x) for x in normalize_upstream_version(right).split('.'))
    return (lt > rt) - (lt < rt)


def debian_revision_for(version: str, revision_suffix: str = DEFAULT_REVISION_SUFFIX) -> str:
    """Format the Debian package version string for an upstream release."""
    return f'{normalize_upstream_version(version)}{revision_suffix}'


def parse_apt_packages_version(packages_text: str, package: str = DEFAULT_PACKAGE) -> str | None:
    """Return the highest Version field for ``package`` in a Debian Packages index."""
    best_tuple: tuple[tuple[int, int, int], str] | None = None
    for stanza in packages_text.strip().split('\n\n'):
        pkg_name = None
        pkg_ver = None
        for line in stanza.splitlines():
            if line.startswith('Package:'):
                pkg_name = line.split(':', 1)[1].strip()
            elif line.startswith('Version:'):
                pkg_ver = line.split(':', 1)[1].strip()
        if pkg_name == package and pkg_ver:
            try:
                parsed = tuple(int(x) for x in base_version_from_debian(pkg_ver).split('.'))
            except ValueError:
                continue
            if best_tuple is None or (parsed, pkg_ver) > best_tuple:
                best_tuple = (parsed, pkg_ver)
    return best_tuple[1] if best_tuple else None


def fetch_url(url: str) -> bytes:
    """Download a public HTTP(S) resource with a clean user-agent."""
    req = urllib.request.Request(url, headers={'User-Agent': 'rustdesk-obs-publisher'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def get_published_version(
    config: PublisherConfig,
    fetch: Callable[[str], bytes] = fetch_url,
    run_cmd: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> str | None:
    """Inspect the currently published Debian version via APT Packages.gz or OBS production."""
    for suffix in ('Packages.gz', 'Packages'):
        url = f'{config.apt_base_url.rstrip("/")}/{suffix}'
        try:
            raw = fetch(url)
            text = (gzip.decompress(raw) if suffix.endswith('.gz') else raw).decode('utf-8')
            version = parse_apt_packages_version(text, config.package)
            if version:
                return version
        except (OSError, ValueError, urllib.error.URLError, EOFError):
            continue

    result = run_cmd(
        ['osc', '-A', config.obs_api, 'ls', config.production_project, config.package],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        found = []
        for line in result.stdout.splitlines():
            m = DSC_FILE_RE.fullmatch(line.strip())
            if m:
                found.append(m.group(1))
        if found:
            return sorted(found)[-1]
    return None


def parse_control_stanzas(control_text: str) -> tuple[dict[str, str], dict[str, str]]:
    """Parse Source and first Package stanza headers from debian/control."""
    stanzas = [s.strip() for s in control_text.strip().split('\n\n') if s.strip()]
    if len(stanzas) < 2:
        raise ValueError('debian/control must contain both Source and Package stanzas')

    def _parse(block: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        current: str | None = None
        for line in block.splitlines():
            if line[:1].isspace() and current:
                fields[current] += '\n' + line
            elif ':' in line:
                key, value = line.split(':', 1)
                current = key.strip()
                fields[current] = value.strip()
        return fields

    return _parse(stanzas[0]), _parse(stanzas[1])


def file_digests(path: Path) -> dict[str, str | int]:
    """Compute byte size, MD5, SHA1, and SHA256 digests for a file in bounded chunks."""
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    with path.open('rb') as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            md5.update(chunk)
            sha1.update(chunk)
            sha256.update(chunk)
    return {
        'size': path.stat().st_size,
        'md5': md5.hexdigest(),
        'sha1': sha1.hexdigest(),
        'sha256': sha256.hexdigest(),
    }


def build_dsc_text(control_path: Path, version: str, archive_paths: Sequence[Path]) -> str:
    """Build a valid Format 3.0 (quilt) Debian .dsc descriptor from control and archives."""
    src_fields, pkg_fields = parse_control_stanzas(control_path.read_text(encoding='utf-8'))
    build_deps = ', '.join(
        item.strip()
        for item in src_fields['Build-Depends'].replace('\n', ' ').split(',')
        if item.strip()
    )
    sha1_lines, sha256_lines, md5_lines = [], [], []
    for archive in archive_paths:
        dig = file_digests(archive)
        sha1_lines.append(f" {dig['sha1']} {dig['size']} {archive.name}")
        sha256_lines.append(f" {dig['sha256']} {dig['size']} {archive.name}")
        md5_lines.append(f" {dig['md5']} {dig['size']} {archive.name}")

    lines = [
        'Format: 3.0 (quilt)',
        f"Source: {src_fields['Source']}",
        f"Binary: {pkg_fields['Package']}",
        f"Architecture: {pkg_fields['Architecture']}",
        f'Version: {version}',
        f"Maintainer: {src_fields['Maintainer']}",
    ]
    for opt_key in ('Homepage', 'Standards-Version', 'Vcs-Browser', 'Vcs-Git'):
        if opt_key in src_fields:
            lines.append(f'{opt_key}: {src_fields[opt_key]}')
    lines.extend([
        f'Build-Depends: {build_deps}',
        'Package-List:',
        f" {pkg_fields['Package']} deb {src_fields['Section']} {src_fields['Priority']} arch={pkg_fields['Architecture']}",
        'Checksums-Sha1:',
        *sha1_lines,
        'Checksums-Sha256:',
        *sha256_lines,
        'Files:',
        *md5_lines,
        '',
    ])
    return '\n'.join(lines)


def ensure_changelog_version(changelog_path: Path, deb_version: str, maintainer: str) -> bool:
    """Prepend a changelog stanza if the top entry is not already ``deb_version``."""
    existing = changelog_path.read_text(encoding='utf-8') if changelog_path.is_file() else ''
    first_line = existing.splitlines()[0] if existing.splitlines() else ''
    expected_prefix = f'rustdesk ({deb_version}) '
    if first_line.startswith(expected_prefix):
        return False
    timestamp = email.utils.formatdate(usegmt=True).replace('GMT', '+0000')
    entry = (
        f'rustdesk ({deb_version}) resolute; urgency=medium\n\n'
        f'  * Automated upstream sync release for Ubuntu 26.04 LTS (amd64).\n\n'
        f' -- {maintainer}  {timestamp}\n\n'
    )
    changelog_path.write_text(entry + existing, encoding='utf-8')
    return True


def link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink ``src`` to ``dst`` when on the same filesystem, falling back to copy2."""
    if dst.exists() and os.path.samefile(src, dst):
        return
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def assemble_source_set(
    repo_root: Path,
    release_dir: Path,
    upstream_version: str,
    debian_revision: str,
    component_archives: dict[str, Path],
    verify_extract: bool = False,
    extract_tmp: Path | None = None,
) -> Path:
    """Assemble multi-tarball 3.0 (quilt) source files and .dsc inside ``release_dir``."""
    release_dir.mkdir(parents=True, exist_ok=True)
    staged_archives: list[Path] = []
    required_suffixes = ('orig.tar.gz', 'orig-sdk.tar.xz', 'orig-pubcache.tar.xz', 'orig-vendor.tar.xz')
    for suffix in required_suffixes:
        if suffix not in component_archives or not component_archives[suffix].is_file():
            raise FileNotFoundError(f'Missing required component archive for {suffix}')
        dst = release_dir / f'rustdesk_{upstream_version}.{suffix}'
        link_or_copy(component_archives[suffix], dst)
        staged_archives.append(dst)

    debian_tar = release_dir / f'rustdesk_{debian_revision}.debian.tar.xz'
    debian_tmp = release_dir / f'rustdesk_{debian_revision}.debian.tar.xz.tmp'
    subprocess.run(
        [
            'tar', '--sort=name', '--mtime=UTC 1970-01-01',
            '--owner=0', '--group=0', '--numeric-owner',
            '-cJf', str(debian_tmp),
            '-C', str(repo_root / 'packaging'),
            'debian',
        ],
        check=True,
    )
    debian_tmp.replace(debian_tar)
    staged_archives.append(debian_tar)

    dsc_path = release_dir / f'rustdesk_{debian_revision}.dsc'
    dsc_path.write_text(
        build_dsc_text(repo_root / 'packaging/debian/control', debian_revision, staged_archives),
        encoding='utf-8',
    )
    (release_dir / '.rustdesk-source-set').write_text(retention.MARKER, encoding='utf-8')

    if verify_extract:
        probe_dir = (extract_tmp or release_dir) / '.dsc-extract-check'
        if probe_dir.exists():
            shutil.rmtree(probe_dir)
        try:
            subprocess.run(['dpkg-source', '--no-check', '-x', str(dsc_path), str(probe_dir)], check=True)
            for req in (
                probe_dir / 'Cargo.toml',
                probe_dir / 'debian/rules',
                probe_dir / 'sdk/bin/flutter',
                probe_dir / 'pubcache/hosted',
                probe_dir / 'vendor/vendor-config.toml',
            ):
                if not req.exists():
                    raise RuntimeError(f'Extracted source tree missing expected path: {req}')
        finally:
            if probe_dir.exists():
                shutil.rmtree(probe_dir)
    return dsc_path


def parse_osc_results_xml(xml_text: str, repository: str, arch: str, package: str) -> str:
    """Parse ``osc results --xml`` output and return the status code for ``package``."""
    root = ET.fromstring(xml_text)
    for res in root.findall('result'):
        if res.attrib.get('repository') == repository and res.attrib.get('arch') == arch:
            if res.attrib.get('dirty') == 'true':
                return 'building'
            for status in res.findall('status'):
                if status.attrib.get('package') == package:
                    return status.attrib.get('code', 'unknown')
    return 'unknown'


def sync_obs_staging(
    config: PublisherConfig,
    release_dir: Path,
    deb_revision: str,
    run_cmd: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Upload the assembled source set cleanly to OBS staging without stale tarballs."""
    co_root = config.work_root / 'obs-checkout'
    co_root.mkdir(parents=True, exist_ok=True)
    pkg_dir = co_root / config.staging_project / config.package
    if not (pkg_dir / '.osc').is_dir():
        if pkg_dir.exists():
            shutil.rmtree(pkg_dir)
        run_cmd(
            ['osc', '-A', config.obs_api, 'checkout', config.staging_project, config.package],
            cwd=str(co_root),
            check=True,
        )
    else:
        run_cmd(['osc', '-A', config.obs_api, 'up'], cwd=str(pkg_dir), check=True)

    upstream_ver = base_version_from_debian(deb_revision)
    wanted_names = [
        f'rustdesk_{upstream_ver}.orig.tar.gz',
        f'rustdesk_{upstream_ver}.orig-sdk.tar.xz',
        f'rustdesk_{upstream_ver}.orig-pubcache.tar.xz',
        f'rustdesk_{upstream_ver}.orig-vendor.tar.xz',
        f'rustdesk_{deb_revision}.debian.tar.xz',
        f'rustdesk_{deb_revision}.dsc',
    ]
    retention.prune_obs_package_files(pkg_dir, wanted_names, apply=True)
    for name in wanted_names:
        link_or_copy(release_dir / name, pkg_dir / name)

    run_cmd(['osc', '-A', config.obs_api, 'addremove'], cwd=str(pkg_dir), check=True)
    run_cmd(
        ['osc', '-A', config.obs_api, 'commit', '-m', f'Build {config.package} {deb_revision}'],
        cwd=str(pkg_dir),
        check=True,
    )


def wait_for_obs_build(
    config: PublisherConfig,
    run_cmd: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    """Poll OBS staging until the build succeeds or fails fatally."""
    deadline = time.monotonic() + config.poll_timeout
    last_code = 'unknown'
    while True:
        res = run_cmd(
            [
                'osc', '-A', config.obs_api, 'results',
                config.staging_project, config.package,
                '-r', config.repository, '-a', config.arch, '--xml',
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        code = parse_osc_results_xml(res.stdout, config.repository, config.arch, config.package)
        last_code = code
        if code == 'succeeded':
            return code
        if code in TERMINAL_FAIL_STATES:
            log = run_cmd(
                [
                    'osc', '-A', config.obs_api, 'remotebuildlog',
                    config.staging_project, config.package,
                    config.repository, config.arch,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            tail = '\n'.join(log.stdout.splitlines()[-40:])
            raise RuntimeError(f'OBS build ended in terminal state {code!r}:\n{tail}')
        if time.monotonic() >= deadline:
            raise TimeoutError(f'Timed out waiting for OBS build (last state: {last_code})')
        sleep_fn(config.poll_interval)


def promote_to_production(
    config: PublisherConfig,
    run_cmd: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> None:
    """Promote verified staging binaries and sources to the production APT OBS project."""
    run_cmd(
        [
            'osc', '-A', config.obs_api, 'release',
            '-r', config.repository,
            '--target-project', config.production_project,
            '--target-repository', config.repository,
            '--no-delay',
            config.staging_project,
            config.package,
        ],
        check=True,
    )


def verify_apt_endpoint(
    config: PublisherConfig,
    expected_version: str | None = None,
    fetch: Callable[[str], bytes] = fetch_url,
) -> dict[str, str]:
    """Verify that the published OBS APT repository serves Release, Release.key, and Packages.gz."""
    base = config.apt_base_url.rstrip('/')
    release_bytes = fetch(f'{base}/Release')
    key_bytes = fetch(f'{base}/Release.key')
    if b'Suites:' not in release_bytes and b'Origin:' not in release_bytes:
        raise RuntimeError('OBS APT Release metadata appears malformed')
    if b'BEGIN PGP PUBLIC KEY BLOCK' not in key_bytes:
        raise RuntimeError('OBS APT Release.key missing PGP public key block')

    pkg_raw = fetch(f'{base}/Packages.gz')
    pkg_text = gzip.decompress(pkg_raw).decode('utf-8')
    published = parse_apt_packages_version(pkg_text, config.package)
    if not published:
        raise RuntimeError(f'Package {config.package!r} not found in live APT Packages.gz')
    if expected_version and published != expected_version:
        raise RuntimeError(f'APT Packages.gz has {published!r}, expected {expected_version!r}')
    return {'apt_version': published}


def sync_own_git_repo(
    repo_root: Path,
    version: str,
    run_cmd: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    """Validate public hygiene, commit packaging metadata updates, and push to origin."""
    status = run_cmd(['git', '-C', str(repo_root), 'status', '--porcelain'], capture_output=True, text=True, check=True)
    if not status.stdout.strip():
        return False
    run_cmd(['git', '-C', str(repo_root), 'add', 'packaging/debian/changelog'], check=True)
    run_cmd([sys.executable, '-B', str(SCRIPTS_DIR / 'check_public_tree.py')], cwd=str(repo_root), check=True)
    diff = run_cmd(['git', '-C', str(repo_root), 'diff', '--cached', '--quiet'], check=False)
    if diff.returncode == 0:
        return False
    run_cmd(
        ['git', '-C', str(repo_root), 'commit', '-m', f'Update Ubuntu 26.04 OBS packaging metadata for {version}'],
        check=True,
    )
    run_cmd(['git', '-C', str(repo_root), 'push', 'origin', 'HEAD'], check=True)
    return True


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=SCRIPTS_DIR.parent)
    parser.add_argument('--work-root', type=Path, default=Path('/var/tmp/rustdesk'))
    parser.add_argument('--staging-project', default=DEFAULT_STAGING_PROJECT)
    parser.add_argument('--production-project', default=DEFAULT_PRODUCTION_PROJECT)
    parser.add_argument('--package', default=DEFAULT_PACKAGE)
    parser.add_argument('--repository', default=DEFAULT_REPOSITORY)
    parser.add_argument('--arch', default=DEFAULT_ARCH)
    parser.add_argument('--obs-api', default=DEFAULT_OBS_API)
    parser.add_argument('--apt-base-url', default=DEFAULT_APT_BASE)
    parser.add_argument('--version', help='Explicit upstream X.Y.Z version instead of querying GitHub')
    parser.add_argument('--check-only', action='store_true')
    parser.add_argument('--assemble-only', action='store_true')
    parser.add_argument('--force-build', action='store_true')
    parser.add_argument('--promote-only', action='store_true')
    parser.add_argument('--verify-apt', action='store_true')
    parser.add_argument('--sync-git', action='store_true')
    parser.add_argument('--poll-interval', type=int, default=30)
    parser.add_argument('--poll-timeout', type=int, default=3600)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    work_root = args.work_root.resolve()
    config = PublisherConfig(
        repo_root=args.repo_root.resolve(),
        work_root=work_root,
        staging_project=args.staging_project,
        production_project=args.production_project,
        package=args.package,
        repository=args.repository,
        arch=args.arch,
        obs_api=args.obs_api,
        apt_base_url=args.apt_base_url,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
    )
    tmpdir = disk_tmpdir(config.work_root)

    if args.verify_apt:
        info = verify_apt_endpoint(config)
        print(json.dumps(info, indent=2, sort_keys=True))
        return 0

    if args.promote_only:
        wait_for_obs_build(config)
        promote_to_production(config)
        info = verify_apt_endpoint(config)
        print(json.dumps({'promoted': True, **info}, indent=2, sort_keys=True))
        return 0

    upstream_ver = (
        normalize_upstream_version(args.version)
        if args.version
        else normalize_upstream_version(inspect_upstream.inspect()['tag'])
    )
    published_deb = get_published_version(config)
    published_base = base_version_from_debian(published_deb) if published_deb else None
    update_available = published_base is None or compare_versions(upstream_ver, published_base) > 0

    if args.check_only:
        print(json.dumps({
            'upstream_version': upstream_ver,
            'published_debian_version': published_deb,
            'published_base_version': published_base,
            'update_available': update_available,
        }, indent=2, sort_keys=True))
        return 0

    if not update_available and not args.force_build and not args.assemble_only:
        print(json.dumps({'status': 'up-to-date', 'version': published_deb}, indent=2))
        return 0

    deb_rev = debian_revision_for(upstream_ver)
    src_fields, _ = parse_control_stanzas(
        (config.repo_root / 'packaging/debian/control').read_text(encoding='utf-8')
    )
    ensure_changelog_version(
        config.repo_root / 'packaging/debian/changelog',
        deb_rev,
        src_fields['Maintainer'],
    )

    releases_root = config.work_root / 'releases'
    release_dir = releases_root / upstream_ver
    component_map = {
        'orig.tar.gz': config.work_root / f'rustdesk_{upstream_ver}.orig.tar.gz',
        'orig-sdk.tar.xz': config.work_root / 'fetch-only/flutter-sdk.tar.xz',
        'orig-pubcache.tar.xz': config.work_root / 'fetch-only/pub-cache.tar.xz',
        'orig-vendor.tar.xz': config.work_root / f'rustdesk_{upstream_ver}.orig-vendor.tar.xz',
    }
    dsc_path = assemble_source_set(
        config.repo_root,
        release_dir,
        upstream_ver,
        deb_rev,
        component_map,
        verify_extract=True,
        extract_tmp=tmpdir,
    )
    if args.assemble_only:
        print(json.dumps({'assembled': str(dsc_path)}, indent=2))
        return 0

    sync_obs_staging(config, release_dir, deb_rev)
    wait_for_obs_build(config)
    promote_to_production(config)
    apt_info = verify_apt_endpoint(config, expected_version=deb_rev)
    retention.prune(releases_root, apply=True, keep=2, protect=(upstream_ver,))
    if args.sync_git:
        sync_own_git_repo(config.repo_root, upstream_ver)
    print(json.dumps({'published': deb_rev, **apt_info}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
