#!/usr/bin/env python3
"""Reject common secrets, private addresses, and generated artifacts in the Git index."""
import ipaddress
import re
import subprocess
import sys

IP = re.compile(rb'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')
SENSITIVE = [
    re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(rb'gh[pousr]_[A-Za-z0-9_]{20,}'),
    re.compile(rb'github_pat_[A-Za-z0-9_]{20,}'),
    re.compile(rb'(?i)(?:password|secret|token)\s*[=:]\s*["\'][^"\']{8,}["\']'),
    re.compile(rb'/' + rb'home/' + rb'[^/\s]+/'),
]
ARTIFACT = re.compile(r'(?:\.deb|\.dsc|\.changes|\.buildinfo|\.tar\.[a-z0-9]+)$', re.I)


def main():
    result = subprocess.check_output(['git', 'ls-files', '-z'])
    bad = []
    for item in result.split(b'\0'):
        if not item:
            continue
        path = item.decode('utf-8')
        data = subprocess.check_output(['git', 'show', ':' + path])
        if ARTIFACT.search(path) or b'\0' in data or any(p.search(data) for p in SENSITIVE):
            bad.append(path)
            continue
        for address in IP.findall(data):
            try:
                if not ipaddress.ip_address(address.decode('ascii')).is_global:
                    bad.append(path)
                    break
            except ValueError:
                continue
    if bad:
        print('Public tree check rejected:', *bad, sep='\n', file=sys.stderr)
        return 1
    print('Public tree check passed; manually review the complete diff as well.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
