#!/usr/bin/env python3
"""Archive/export/upload iOS using existing native SDKs; never builds C dependencies."""
import argparse
import plistlib
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('action', choices=['archive', 'export', 'upload'])
p.add_argument('--build', type=int, required=True, help='Unique positive build number')
p.add_argument('--version', default='1.0.0')
p.add_argument('--external', action='store_true', help='Allow external TestFlight/App Store distribution (default: internal beta only)')
args = p.parse_args()
if args.build < 1: p.error('--build must be positive')
if not args.version or any(c not in '0123456789.' for c in args.version): p.error('Invalid version')
output = root / 'build/distribution'
output.mkdir(parents=True, exist_ok=True)
archive = output / f'XPN-{args.version}-{args.build}.xcarchive'

def run(*command): subprocess.run(command, cwd=root, check=True)

if args.action == 'archive':
    framework = root / 'clients/apple/Frameworks/XPNNative.xcframework/Info.plist'
    with framework.open('rb') as stream: slices = plistlib.load(stream)['AvailableLibraries']
    if not any(x.get('SupportedPlatform') == 'ios' and not x.get('SupportedPlatformVariant') for x in slices):
        p.error('An iOS device native framework is required; this helper does not compile C')
    run('xcodegen', 'generate', '--spec', 'clients/apple/project.local.yml')
    run('xcodebuild', '-project', 'clients/apple/XPN.xcodeproj', '-scheme', 'XPN-iOS',
        '-configuration', 'Release', '-destination', 'generic/platform=iOS',
        '-archivePath', str(archive), '-derivedDataPath', str(root / 'build/xcode-release'),
        f'MARKETING_VERSION={args.version}', f'CURRENT_PROJECT_VERSION={args.build}', 'archive')
else:
    app = archive / 'Products/Applications/XPN-iOS.app'
    with (app / 'Info.plist').open('rb') as stream: info = plistlib.load(stream)
    if info['CFBundleVersion'] != str(args.build) or info['CFBundleShortVersionString'] != args.version:
        p.error('Archive version/build does not match the request')
    for bundle in (app, app / 'PlugIns/XPN-iOS-Tunnel.appex'):
        if not (bundle / 'PrivacyInfo.xcprivacy').is_file(): p.error(f'Missing privacy manifest: {bundle.name}')
    options = output / f'ExportOptions-{args.action}.plist'
    options.write_bytes(plistlib.dumps({'method': 'app-store-connect', 'destination': args.action,
        'signingStyle': 'automatic', 'manageAppVersionAndBuildNumber': False,
        'uploadSymbols': True, 'testFlightInternalTestingOnly': not args.external}))
    run('xcodebuild', '-exportArchive', '-archivePath', str(archive),
        '-exportPath', str(output / f'XPN-{args.version}-{args.build}-{args.action}'),
        '-exportOptionsPlist', str(options), '-allowProvisioningUpdates')
