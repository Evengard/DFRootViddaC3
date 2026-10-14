"""Offline tests only; does not execute or load the kernel module."""
from pathlib import Path
import importlib.util
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "patches/dfroot/overlay/apply_c3u_v7.py"
spec = importlib.util.spec_from_file_location("c3u_pin", SRC)
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)

class ArchivedModulePinTest(unittest.TestCase):
    def test_recovered_archive_matches_pinned_sha(self):
        path = ROOT / "known-good/working-v6.ko"
        data, digest = patcher.check_ko(path)
        self.assertEqual(digest, patcher.ARCHIVED_C3U_V6_SHA256)
        self.assertIn(b"KernelSU: Permissive SELinux, keeping", data)
        expected = (ROOT / "known-good/working-v6.sha256").read_text().split()[0]
        self.assertEqual(digest, expected)

    def test_tampered_legacy_module_is_rejected(self):
        path = ROOT / "known-good/working-v6.ko"
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        with tempfile.TemporaryDirectory() as tmp:
            altered = Path(tmp) / "altered.ko"
            altered.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "matching archived-module SHA-256"):
                patcher.check_ko(altered)

    def test_generic_legacy_marker_without_pin_is_rejected(self):
        data = bytearray(65536)
        data[:6] = b"\x7fELF\x02\x01"
        data[18:20] = (183).to_bytes(2,"little")
        data[512:512+len(b"KernelSU: Permissive SELinux, keeping")] = b"KernelSU: Permissive SELinux, keeping"
        data[1024:1024+len(b"vermagic=5.15.")] = b"vermagic=5.15."
        with tempfile.TemporaryDirectory() as tmp:
            altered = Path(tmp) / "altered.ko"
            altered.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "matching archived-module SHA-256"):
                patcher.check_ko(altered)

if __name__ == "__main__":
    unittest.main()
