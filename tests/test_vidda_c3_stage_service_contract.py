"""Regression: service migration must accept EXACTLY the output of the
preceding, verified legacy+KernelSU staging patch after unpinning Manager ksud.
No network, Docker, or external ELF tools needed.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
REL = "app/src/main/java/df/root/ExploitRunner.java"
FIXTURE = ROOT / "tests/fixtures/ExploitRunner-6de6222.java"


def module_at(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StageServiceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stage = module_at(ROOT / "patches/dfroot/legacy-ksu/apply_stage.py", "vidda_stage_contract")
        cls.service = module_at(ROOT / "patches/dfroot/legacy-ksu/apply_foreground_service.py", "vidda_service_contract")

    def test_post_stage_runner_matches_foreground_service_hash(self):
        upstream = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(upstream).hexdigest(),
                         self.stage.UPSTREAM_BASELINE[REL])
        staged = self.stage.modify_runner(upstream.decode("utf-8"))
        actual_sha256 = hashlib.sha256(staged.encode("utf-8")).hexdigest()
        self.assertEqual(actual_sha256, self.service.EXPECTED[REL],
                         "apply_stage.py and apply_foreground_service.py are out of sync")
        self.assertIn("ksud.canExecute()", staged)
        self.assertNotIn("C3U_MANAGER_KSUD_SHA256", staged)
        self.assertNotIn("Manager ksud differs from manually tested", staged)
        self.assertIn(REL, self.service.NATIVE_IMMUTABLE)
        self.assertNotIn(REL, self.service.TRANSFORMS)

    def test_unexpected_runner_still_fails_closed(self):
        upstream = FIXTURE.read_text()
        staged = self.stage.modify_runner(upstream)
        self.assertNotEqual(hashlib.sha256((staged + "// unexpected edit\n").encode()).hexdigest(),
                            self.service.EXPECTED[REL])
        self.assertIn("digest(source.read_bytes()) != expected_hash",
                      (ROOT / "patches/dfroot/legacy-ksu/apply_foreground_service.py").read_text())


if __name__ == "__main__":
    unittest.main()
