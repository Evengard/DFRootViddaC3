"""Regression checks for opt-in pinned DFRoot first-stage rollback."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/prepare-legacy-first-stage.py"
spec = importlib.util.spec_from_file_location("legacy_dfroot_prep", SCRIPT)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


class LegacyFirstStageTests(unittest.TestCase):
    def test_exact_commit_and_helper_hash_are_pinned(self):
        self.assertEqual(legacy.LEGACY_DFROOT_REV, "6de62220809a678fddbd3819e4fcb3bb68aa1eae")
        self.assertEqual(legacy.LEGACY_HELPER_SHA256,
                         "5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473")
        ko = ROOT / "known-good/dfroot-helper-6de6222.ko"
        self.assertEqual(ko.stat().st_size, 12232)
        self.assertEqual(legacy.sha256(ko), legacy.LEGACY_HELPER_SHA256)

    def test_build_is_opt_in_and_excludes_ksu_and_service_patches(self):
        workflow = (ROOT / ".github/workflows/build-legacy-first-stage.yml").read_text()
        script = (ROOT / "tools/build-legacy-first-stage.sh").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("push:", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertIn('prepare-legacy-first-stage.py', script)
        self.assertNotIn('apply_c3u_v7.py', script)
        self.assertNotIn('apply_service_worker.py', script)
        self.assertNotIn('apply_unified_ui.py', script)
        self.assertNotIn('patches/ksunext/build-module.sh', script)
        self.assertIn('root.count(ko) != 1', script)

    def test_old_runner_hash_is_locked(self):
        self.assertEqual(legacy.LEGACY_RUNNER_SHA256,
                         "088c4052876287067b74bec016f7aa34b5dc8dad2f44523692e5226fce686a8d")


if __name__ == "__main__":
    unittest.main()
