#!/usr/bin/env python3
"""Prepare a clean working-tree snapshot and npm sources for local Debian builds.

This downloads locked npm sources but does not build, install, sign or upload.
The Debian build itself needs no network. No git archive: uncommitted fixes count.
"""
import argparse
from datetime import datetime, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('series', choices=['noble', 'resolute'])
    parser.add_argument('--revision', default='1', help='Increment for each new upload to the same series')
    parser.add_argument('--output', type=Path, help='New empty output directory (default build/packages/SERIES)')
    args = parser.parse_args()
    if not re.fullmatch(r'[1-9][0-9]*', args.revision):
        parser.error('revision must be a positive integer')
    root = Path(__file__).resolve().parents[1]
    version = json.loads((root / 'package.json').read_text())['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        parser.error('package.json version must be MAJOR.MINOR.PATCH')
    out = (args.output or root / 'build/packages' / args.series).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        parser.error(f'{out} is not empty; use a new output directory')
    source = out / f'xpn-{version}'
    source.mkdir()
    # Explicit source roots: exclude private state, git metadata and Apple SDKs.
    for folder in ['server/public', 'native/src', 'native/include', 'native/tests', 'clients/linux', 'deploy', 'docs']:
        shutil.copytree(root / folder, source / folder, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for pattern in ['server/*.mjs', 'package.json', 'package-lock.json', 'README.md', 'native/CMakeLists.txt', 'LICENSE*']:
        for path in root.glob(pattern):
            dest = source / path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    # The lockfile is the authority; install scripts are forbidden at preparation time.
    subprocess.run(['npm', 'ci', '--omit=dev', '--ignore-scripts', '--no-audit', '--no-fund',
                    '--cache', str(root / 'build/npm-cache')], cwd=source, check=True)
    vendor = source / 'vendor'
    vendor.mkdir()
    (source / 'node_modules').rename(vendor / 'node_modules')
    # Reproducible orig tar across series, using a stable timestamp (override for a release).
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '1792929600'))
    def metadata(info):
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        info.mtime = epoch
        return info
    with tarfile.open(out / f'xpn_{version}.orig.tar.xz', 'w:xz') as archive:
        archive.add(source, arcname=source.name, filter=metadata)
    shutil.copytree(root / 'debian', source / 'debian')
    maintainer = f"{os.environ.get('DEBFULLNAME', 'XPN local builder')} <{os.environ.get('DEBEMAIL', 'builder@localhost')}>"
    if '\n' in maintainer or '\r' in maintainer:
        parser.error('invalid maintainer environment')
    control = source / 'debian/control'
    control.write_text(re.sub(r'^Maintainer: .*$', lambda _: 'Maintainer: ' + maintainer, control.read_text(), flags=re.M))
    package_version = f'{version}-0ubuntu1~{args.series}{args.revision}'
    (source / 'debian/changelog').write_text(
        f'xpn ({package_version}) {args.series}; urgency=medium\n\n'
        '  * Local client/server packaging; publication requires release review.\n\n'
        f' -- {maintainer}  {format_datetime(datetime.fromtimestamp(epoch, timezone.utc))}\n')
    for path in ['rules', 'xpn-server.postinst', 'xpn-server.prerm']:
        (source / 'debian' / path).chmod(0o755)
    print(f'Prepared {source}\nIn an Ubuntu {args.series} VM: cd {source} && dpkg-buildpackage -us -uc -b')


if __name__ == '__main__':
    main()
