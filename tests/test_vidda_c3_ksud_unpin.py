"""Allow updated KernelSU Next Managers without shipping a standalone ksud."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STAGE_PATH = ROOT / 'patches/dfroot/legacy-ksu/apply_stage.py'
BUILDER_PATH = ROOT / 'tools/build-dfroot.sh'
NATIVE_PATH = ROOT / 'patches/dfroot/legacy-ksu/c3u_ksu_stage.c'
OLD_SHA = '448155d297e0402ca577379131fc081387a4454392212c3b1567a9de0d58c974'


class ManagerKsudUnpinTests(unittest.TestCase):
    def test_java_runner_accepts_updated_manager_ksud(self):
        spec = importlib.util.spec_from_file_location('vidda_c3_stage_unpinned', STAGE_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        upstream_fragment = '''class FakeRunner {
    private static void reportDeviceInfo(IReporter reporter) {
        stageBin(ctx, new File(app.nativeLibraryDir, "libksud.so"), "ksud"); // stage for a predictable path
        stageBin(ctx, new File(ctx.getApplicationInfo().nativeLibraryDir, "libbootstrap.so"), "bootstrap");
    }
}'''
        modified = module.modify_runner(upstream_fragment)
        self.assertIn('libksud.so', modified)
        self.assertIn('"ksud"); // staged FROM the selected Manager', modified)
        self.assertIn('if (!ksud.isFile() || !ksud.canExecute())', modified)
        self.assertIn('"libc3uksu.so"', modified)
        self.assertNotIn('C3U_MANAGER_KSUD_SHA256', modified)
        self.assertNotIn('c3uSha256(', modified)
        self.assertNotIn(OLD_SHA, modified)
        self.assertNotIn('Manager ksud differs', modified)

    def test_compiler_does_not_require_old_ksud_sha(self):
        script = BUILDER_PATH.read_text()
        self.assertNotIn("'required_sha256':", script)
        self.assertNotIn('Manager-staged ksud runtime pin missing', script)
        self.assertIn("'sha256_policy':'not pinned; updated Manager ksud accepted'", script)
        # A stale APK is rejected by its old error message, without retaining
        # the obsolete Manager fingerprint anywhere in the build script.
        self.assertNotIn(OLD_SHA, script)
        self.assertIn("if b'Manager ksud differs from manually tested C3U binary' in dex:", script)
        self.assertIn('obsolete Manager ksud SHA-256 restriction remains in APK', script)

    def test_missing_daemon_is_still_rejected(self):
        stage = STAGE_PATH.read_text()
        native = NATIVE_PATH.read_text()
        self.assertIn('if (!ksud.isFile() || !ksud.canExecute())', stage)
        self.assertIn('C3U_KSUD "/data/user_de/0/df.root/ksud"', native)
        self.assertIn('if (access(C3U_KSUD, X_OK) != 0)', native)
        self.assertIn('"insmod"', native)
        self.assertIn('dfroot_start_root_service', stage)


if __name__ == '__main__':
    unittest.main()
