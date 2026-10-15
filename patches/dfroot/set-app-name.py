#!/usr/bin/env python3
"""Set user-facing Vidda C3 app branding without altering package df.root."""
from pathlib import Path
import argparse


def apply(checkout: Path):
    manifest = checkout / 'app/src/main/AndroidManifest.xml'
    source = manifest.read_text()
    old = 'android:label="DFRoot"'
    if source.count(old) != 1 or 'package="df.root"' not in source:
        raise ValueError('Unexpected DFRoot manifest: refusing to rename application')
    manifest.write_text(source.replace(old, 'android:label="Vidda C3 Root"', 1))
    print('PASS: Android app display name Vidda C3 Root; package df.root unchanged')

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('checkout', type=Path)
    a = ap.parse_args()
    apply(a.checkout)
