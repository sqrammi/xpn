#!/usr/bin/env python3
"""Generate an ignored XcodeGen signing overlay; no account access or signing."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('team', help='10-character Apple Developer team ID')
    parser.add_argument('bundle_prefix', help='Your unique reverse-DNS prefix, e.g. com.jeffhansen.xpn')
    parser.add_argument('--write-only', action='store_true', help='Write config without running XcodeGen')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Z0-9]{10}', args.team):
        parser.error('team must be 10 uppercase letters/digits')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z][A-Za-z0-9-]*)+', args.bundle_prefix):
        parser.error('bundle_prefix must be a reverse-DNS identifier without wildcards')
    root = Path(__file__).resolve().parents[2] / 'clients/apple'
    lines = ['include: project.yml', 'settings:', '  base:',
             '    DEVELOPMENT_TEAM: ' + json.dumps(args.team),
             '    CODE_SIGN_STYLE: Automatic',
             '    XPN_SHARED_GROUP: ' + json.dumps(args.bundle_prefix + '.shared'), 'targets:']
    for target, suffix in [('XPN-iOS', 'ios'), ('XPN-iOS-Tunnel', 'ios.tunnel'),
                           ('XPN-macOS', 'macos'), ('XPN-macOS-Tunnel', 'macos.tunnel')]:
        lines += [f'  {target}:', '    settings:', '      base:',
                  '        PRODUCT_BUNDLE_IDENTIFIER: ' + json.dumps(args.bundle_prefix + '.' + suffix)]
    destination = root / 'project.local.yml'
    destination.write_text('\n'.join(lines) + '\n')
    print(destination)
    if not args.write_only:
        subprocess.run(['xcodegen', 'generate', '--spec', str(destination)], cwd=root, check=True)


if __name__ == '__main__':
    main()
