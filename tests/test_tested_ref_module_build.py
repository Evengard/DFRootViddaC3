"""Offline regression gates for the optional, isolated reference KSU rebuild."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / 'patches/ksunext/tested-revision/apply-tested-selinux.py'
BUILDER = ROOT / 'patches/ksunext/tested-revision/build-in-docker.sh'
RUNNER = ROOT / 'tools/build-ksunext-tested-ref-candidate.sh'
WORKFLOW = ROOT / '.github/workflows/build-legacy-manager-ksu.yml'
APK_RUNNER = ROOT / 'tools/build-legacy-manager-ksu.sh'
COMPARATOR = ROOT / 'tools/compare-ksunext-modules.py'
REF = '78ed5d1f5b5041a197f0b55291876d62a6bd7c67'
TESTED_SHA = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'


def module_at(file: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, file)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestReferenceCandidateCI(unittest.TestCase):
    def test_exact_historical_patch_only(self):
        p = module_at(PATCH, 'archived_selinux_patch')
        self.assertEqual(p.COMMIT, REF)
        self.assertEqual(p.ORIGINAL_SHA256, '0582020d71b6a282e3371a6f97f579dd5e87342c225e82ea232d53b3fcbe451b')
        self.assertEqual(p.PATCHED_SHA256, '0700275dcc77217a224ca252f6f5129c3d6947043ce9b95776a11af7760c499d')
        original = '/*unrelated*/\n' + p.BEFORE + '\n/*other code*/\n'
        changed = p.modify(original)
        self.assertIn('Permissive SELinux, keeping', changed)
        self.assertIn('//setenforce(true);', changed)
        self.assertNotIn('pr_info("Permissive SELinux, enforcing', changed)
        self.assertEqual(changed.count(p.AFTER), 1)
        for invalid in ('bad input', p.BEFORE + p.BEFORE, p.AFTER):
            with self.subTest(invalid=invalid[:40]), self.assertRaises(ValueError):
                p.modify(invalid)

    def test_dynamic_source_and_isolated_paths(self):
        shell = RUNNER.read_text()
        builder = BUILDER.read_text()
        apk = APK_RUNNER.read_text()
        self.assertIn('REF="${C3U_KSUN_REF:-dev}"', shell)
        self.assertIn('git -C "$WORK" checkout -q --detach "$TARGET"', shell)
        self.assertIn('sha256sum -c working-v6.sha256', shell)
        self.assertIn('dist-ksunext-reference', shell)
        self.assertIn('work-ksunext-reference', shell)
        self.assertIn('apply-c3u.py', shell)
        self.assertIn('ghcr.io/ylarod/ddk-min:android14-5.15-20260828', builder)
        self.assertIn('CONFIG_KSU=m CC=clang', builder)
        self.assertIn('python3 /verify-module-layout.py', builder)
        self.assertIn('Permissive SELinux, keeping', builder)
        self.assertIn('UNVERIFIED-DO-NOT-LOAD', builder)
        self.assertNotIn('dist-legacy-manager-ksu', shell + builder)
        self.assertIn('GOOD_KSU="$ROOT/known-good/working-v6.ko"', apk)
        self.assertIn('dist-ksunext-reference', apk)
        self.assertIn('C3U_EMBED_REBUILT_KSU', apk)

    def test_workflow_compiles_and_embeds_in_one_sequential_job(self):
        yml = WORKFLOW.read_text()
        runner = (ROOT / 'tools/build-c3u-autobuilt-apk.sh').read_text()
        self.assertIn('workflow_dispatch:', yml)
        self.assertIn('compile-and-embed-kernelsu:', yml)
        self.assertNotIn('reference-module-candidate:', yml)
        self.assertIn('run: bash tools/build-c3u-autobuilt-apk.sh', yml)
        self.assertIn('C3U_EMBED_REBUILT_KSU=1', runner)
        self.assertIn('build-ksunext-tested-ref-candidate.sh', runner)
        self.assertIn('build-legacy-manager-ksu.sh', runner)
        self.assertIn('verify-c3u-autobuilt-apk.py', runner)
        self.assertLess(runner.index('build-ksunext-tested-ref-candidate.sh'),
                        runner.index('C3U_EMBED_REBUILT_KSU=1'))
        self.assertIn('push:', yml)
        self.assertIn('ksun_ref:', yml)
        self.assertIn('default: dev', yml)
        self.assertNotIn('pull_request:', yml)
        # Scripts are invoked through bash; no requirement to preserve +x in ZIPs.
        for f in (RUNNER, BUILDER, APK_RUNNER,
                  ROOT / 'tools/build-c3u-autobuilt-apk.sh'):
            subprocess.run(['bash', '-n', str(f)], check=True)

    def test_comparator_remains_read_only_and_mac_portable(self):
        c = module_at(COMPARATOR, 'comparison')
        self.assertEqual(c.KNOWN_GOOD_SHA, TESTED_SHA)
        self.assertIn('comparison_is_read_only', COMPARATOR.read_text())
        self.assertIn('candidate_differs_UNVERIFIED', COMPARATOR.read_text())
        # Read-only ELF inspection must work without Linux readelf or Homebrew.
        reference = ROOT / 'known-good/working-v6.ko'
        if reference.exists():
            with patch('subprocess.check_output', side_effect=AssertionError('External ELF tool invoked')):
                result = c.compare(reference, reference)
            self.assertEqual(result['status'], 'byte_identical_to_tested_module')
            self.assertEqual(result['device_tested_known_good']['undefined_count'], 232)
            self.assertEqual(result['device_tested_known_good']['vermagic'],
                             '5.15.202 SMP preempt mod_unload modversions aarch64')
            self.assertTrue(result['candidate_matches_known_good_bytes'])
            self.assertTrue(result['comparison_is_read_only'])

    def test_comparator_rejects_invalid_elf_without_external_tools(self):
        c = module_at(COMPARATOR, 'comparison_invalid')
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            corrupt = Path(d) / 'invalid.ko'
            corrupt.write_bytes(b'not-an-ELF-module')
            with self.assertRaisesRegex(ValueError, 'truncated ELF|expected little-endian ELF64'):
                c.metadata(corrupt)


if __name__ == '__main__':
    unittest.main()
