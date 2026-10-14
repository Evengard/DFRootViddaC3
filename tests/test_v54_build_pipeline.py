"""Catch v5.4 pipeline omissions that unit tests of the standalone patcher miss."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_verifier():
    path = ROOT / 'tools/verify-unified-ui.py'
    spec = importlib.util.spec_from_file_location('c3u_v54_verifier', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class V54BuildPipeline(unittest.TestCase):
    def test_manifest_requires_stage_06(self):
        series = json.loads((ROOT / 'patches/dfroot/patchset/series.json').read_text())
        self.assertEqual(series['stages'][-1]['id'], '06-unified-ui-adb-service')
        self.assertEqual(series['stages'][-1]['entrypoint'],
                         'patches/dfroot/overlay/apply_unified_ui.py')

    def test_build_wires_stage_06_before_gradle_and_checks_apk(self):
        script = (ROOT / 'tools/build-all.sh').read_text()
        points = [script.find(item) for item in (
            'apply_adb_intent.py', 'apply_service_worker.py',
            'apply_unified_ui.py', 'build-and-bundle.sh',
        )]
        self.assertTrue(all(p >= 0 for p in points), points)
        self.assertEqual(points, sorted(points), points)
        self.assertIn('--source-dir "$WORK/DFRoot/app/src/main/java/df/root"', script)
        self.assertIn('--apk "$DIST/DFRoot-C3U-CANDIDATE.apk"', script)

    def test_apk_check_fails_on_old_ui_and_missing_classes(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / 'fake.apk'
            with zipfile.ZipFile(apk, 'w') as z:
                z.writestr('classes.dex', b'dex\n035\0' + b'runExploit')
            with self.assertRaisesRegex(ValueError, 'lacks v5.4'):
                verifier.verify_apk(apk)
            with zipfile.ZipFile(apk, 'w') as z:
                z.writestr('classes.dex', b'dex\n035\0' + b'|'.join(verifier.DEX_REQUIRED)
                           + b'runExploit')
            with self.assertRaisesRegex(ValueError, 'old UI path'):
                verifier.verify_apk(apk)

    def test_apk_check_accepts_v54_symbols(self):
        verifier = load_verifier()
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp) / 'fake.apk'
            with zipfile.ZipFile(apk, 'w') as z:
                z.writestr('classes.dex', b'dex\n035\0' + b'|'.join(verifier.DEX_REQUIRED))
            verifier.verify_apk(apk)


if __name__ == '__main__':
    unittest.main()
