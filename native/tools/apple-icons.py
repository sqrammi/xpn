#!/usr/bin/env python3
"""Generate Apple app-icon sizes from the checked-in opaque artwork (macOS sips)."""
import json
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[2]
source = root / 'docs/branding/xpn-icon-original.png'
catalog = root / 'clients/apple/AppResources/Assets.xcassets'
output = catalog / 'AppIcon.appiconset'
output.mkdir(parents=True, exist_ok=True)
info = {'version': 1, 'author': 'xcode'}
(catalog / 'Contents.json').write_text(json.dumps({'info': info}, indent=2) + '\n')
images = [{'filename': 'icon-1024.png', 'idiom': 'universal', 'platform': 'ios', 'size': '1024x1024'}]
for points in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        images.append({'filename': f'icon-{points * scale}.png', 'idiom': 'mac',
                       'size': f'{points}x{points}', 'scale': f'{scale}x'})
for pixels in (16, 32, 64, 128, 256, 512, 1024):
    subprocess.run(['sips', '-z', str(pixels), str(pixels), str(source), '--out', str(output / f'icon-{pixels}.png')], check=True, stdout=subprocess.DEVNULL)
(output / 'Contents.json').write_text(json.dumps({'images': images, 'info': info}, indent=2) + '\n')
print(output)
