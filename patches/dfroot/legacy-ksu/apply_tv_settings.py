#!/usr/bin/env python3
"""Expose a permanent, focusable Settings button for Android TV remotes.

The legacy app only exposed Settings via the invisible/awkward options menu.
This patch runs after the working FGS integration and never touches native code.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

FILES = {
    'app/src/main/java/df/root/MainActivity.java': 'be5b424f6149187431410fa97952aec3c3ab60a46b7a8187df1e87730f9b28aa',
    'app/src/main/res/layout/activity_main.xml': '8cd783727ebf3de7886cfa35d9fbd28cf2c6c98caeda936883be02198f9f6f8f',
}


def once(s: str, old: str, new: str) -> str:
    if s.count(old) != 1:
        raise ValueError(f'Unexpected Android TV source: target occurred {s.count(old)} times')
    return s.replace(old, new, 1)


def main_activity(s: str) -> str:
    s = once(s, '    private Button btnRunKsu;', '    private Button btnRunKsu;\n    private Button btnSettings;')
    s = once(s, '        btnRunKsu = findViewById(R.id.btnRunKsu);',
             '        btnRunKsu = findViewById(R.id.btnRunKsu);\n        btnSettings = findViewById(R.id.btnSettings);')
    s = once(s, '        btnRunKsu.setOnClickListener(v -> launch(true));',
             '''        btnRunKsu.setOnClickListener(v -> launch(true));
        // A visible D-pad focusable control; do not depend on Android TV's action bar.
        btnSettings.setOnClickListener(v ->
                startActivity(new Intent(this, SettingsActivity.class)));''')
    return s


def layout(s: str) -> str:
    anchor = '    <ScrollView\n        android:id="@+id/outputScroll"'
    replacement = '''    <!-- Android TV often hides the overflow/action-bar Settings item. -->
    <Button
        android:id="@+id/btnSettings"
        android:layout_width="match_parent"
        android:layout_height="wrap_content"
        android:minHeight="48dp"
        android:focusable="true"
        android:focusableInTouchMode="false"
        android:text="Settings" />

''' + anchor
    return once(s, anchor, replacement)


def apply(repo: Path) -> None:
    changes = {}
    for rel, expected in FILES.items():
        p = repo / rel
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise ValueError(f'TV Settings integration refuses changed input: {rel}')
        changes[p] = (main_activity if rel.endswith('.java') else layout)(p.read_text())
    for p, content in changes.items():
        p.write_text(content)
    print('PASS: visible, focusable Settings button opens existing SettingsActivity on Android TV')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkout', type=Path)
    args = parser.parse_args()
    try:
        apply(args.checkout)
    except (ValueError, OSError) as e:
        parser.exit(1, f'REFUSED: {e}\n')


if __name__ == '__main__':
    main()
