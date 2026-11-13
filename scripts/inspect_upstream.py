#!/usr/bin/env python3
"""Inspect a public RustDesk release without modifying upstream or the host."""
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request

API = 'https://api.github.com/repos/rustdesk/rustdesk/releases/latest'
RAW = 'https://raw.githubusercontent.com/rustdesk/rustdesk/{}/Cargo.toml'
TAG = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'rustdesk-obs-inspector', 'Accept': 'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def inspect(fetch=get):
    release = json.loads(fetch(API))
    tag = release['tag_name']
    if not isinstance(tag, str) or not TAG.fullmatch(tag):
        raise ValueError('Unexpected release tag')
    manifest = tomllib.loads(fetch(RAW.format(tag)).decode('utf-8'))
    features = manifest.get('features', {})
    scrap = manifest.get('dependencies', {}).get('scrap', {})
    scrap_features = scrap.get('features', []) if isinstance(scrap, dict) else []
    return {'tag': tag, 'release_url': release['html_url'],
            'cargo_features': {name: name in features for name in ('wayland', 'hwcodec')},
            'scrap_wayland_enabled': 'wayland' in scrap_features}


def main():
    try:
        result = inspect()
    except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
        print(f'Upstream inspection failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
