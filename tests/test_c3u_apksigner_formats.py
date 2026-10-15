"""Regression checks for Build Tools 36/37 APK signing report formats."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / 'tools/parse-apk-signature.py'
BUILDER = ROOT / 'tools/build-dfroot.sh'
FINGERPRINT = '0123456789abcdef' * 4


def load():
    spec = importlib.util.spec_from_file_location('c3u_signing_parser', PARSER)
    mod = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


class ApkSignerReportTests(unittest.TestCase):
    def test_build_tools_36_format(self):
        report = 'Verifies\nSigner #1 certificate SHA-256 digest: ' + FINGERPRINT + '\n'
        self.assertEqual(load().fingerprint(report), FINGERPRINT)

    def test_build_tools_37_v2_v3_format(self):
        report = ('Verifies\nV2 Signer: certificate SHA-256 digest: ' + FINGERPRINT + '\n'
                  'V3.0 Signer: certificate SHA-256 digest: ' + FINGERPRINT.upper() + '\n')
        self.assertEqual(load().fingerprint(report), FINGERPRINT)

    def test_fail_closed_on_absent_digest(self):
        with self.assertRaisesRegex(ValueError, 'does not include'):
            load().fingerprint('Verifies\nNumber of signers: 1\n')

    def test_fail_closed_on_conflicting_signers(self):
        report = ('V2 Signer: certificate SHA-256 digest: ' + FINGERPRINT + '\n'
                  'V3.0 Signer: certificate SHA-256 digest: ' + ('a'*64) + '\n')
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            load().fingerprint(report)

    def test_build_wires_parser_to_manifest_and_preserves_verify(self):
        src = BUILDER.read_text()
        self.assertIn('apksigner" verify', src)
        self.assertIn('"$ROOT/tools/parse-apk-signature.py"', src)
        self.assertIn('"$SIGNING_CERT_SHA256" <<\'PY\'', src)
        self.assertIn('cert_sha256=sys.argv[7]', src)
        self.assertNotIn('grep -q "Signer #1 certificate SHA-256 digest', src)
        self.assertIn("'signing_certificate_sha256':cert_sha256", src)

    def test_parser_command_line(self):
        with tempfile.TemporaryDirectory() as td:
            report = Path(td) / 'report.txt'
            report.write_text('V2 Signer: certificate SHA-256 digest: ' + FINGERPRINT + '\n')
            res = subprocess.run([sys.executable, str(PARSER), str(report)],
                                 capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout.strip(), FINGERPRINT)


if __name__ == '__main__':
    unittest.main()
