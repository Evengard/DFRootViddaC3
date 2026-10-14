"""Safe offline invariants for the optional legacy DFRoot + KSU build."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / 'patches/dfroot/legacy-ksu/apply_stage.py'
spec = importlib.util.spec_from_file_location('legacy_ksu_overlay', APPLY)
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


class LegacyManagerKsuTests(unittest.TestCase):
    def test_only_exact_proven_kernel_module_is_permitted(self):
        ko = ROOT / 'known-good/working-v6.ko'
        self.assertEqual(ko.stat().st_size, 6797960)
        self.assertEqual(hashlib.sha256(ko.read_bytes()).hexdigest(), loader.KO_SHA256)
        self.assertEqual(loader.KO_SHA256,
                         '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b')

    def test_current_manager_daemon_is_used_not_packaged(self):
        self.assertEqual(loader.MANAGER_KSUD_SHA256,
                         '448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974')
        native = (ROOT / 'patches/dfroot/legacy-ksu/c3u_ksu_stage.c').read_text()
        self.assertIn('/data/user_de/0/df.root/ksud', native)
        self.assertIn('"insmod"', native)
        self.assertNotIn('/data/adb/ksud', native)
        self.assertIn('ko/c3u-working-v6.ko', native)
        self.assertNotIn('07c12cee5bbe68c989dd4edc3189dfba6832ca0f73ff1be90727da8a0a1869c3', native)

    def test_auto_or_manual_workflow_keeps_original_first_stage(self):
        workflow = (ROOT / '.github/workflows/build-legacy-manager-ksu.yml').read_text()
        script = (ROOT / 'tools/build-legacy-manager-ksu.sh').read_text()
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('push:', workflow)
        self.assertNotIn('pull_request:', workflow)
        self.assertIn('prepare-legacy-first-stage.py', script)
        self.assertIn('apply_stage.py', script)
        self.assertNotIn('apply_c3u_v7.py', script)
        self.assertNotIn('build-module.sh', script)
        self.assertIn('old.count(helper.read_bytes()) != 1', script)
        self.assertIn('loader.count(ksu.read_bytes()) != 1', script)

    def test_one_shot_gate_and_root_service_remain(self):
        text = Path(APPLY).read_text()
        self.assertIn('c3u_consume_stage_request', text)
        self.assertIn('/proc/sys/kernel/random/boot_id', text)
        self.assertIn('unlink(C3U_STAGE_REQUEST)', text)
        self.assertIn('dfroot_start_root_service(void)', text)
        self.assertIn('"late-load"', text)
        self.assertIn('KSUD_STAGE', text)
        self.assertIn('soft_reboot', text)
        self.assertNotIn('C3URootForegroundService', text)

    def test_default_root_button_clears_request(self):
        text = Path(APPLY).read_text()
        self.assertIn('launch(false)', text)
        self.assertIn('launch(true)', text)
        self.assertIn('Files.deleteIfExists(request.toPath())', text)

    def test_fail_closed_on_wrong_legacy_sources(self):
        fn = loader.replace_once
        self.assertEqual(fn('A-B-C', '-B-', ':B:', 'test'), 'A:B:C')
        with self.assertRaises(ValueError):
            fn('does-not-match', 'missing', 'new', 'test')
        with self.assertRaises(ValueError):
            fn('X X', 'X', 'Y', 'test')


if __name__ == '__main__':
    unittest.main()
