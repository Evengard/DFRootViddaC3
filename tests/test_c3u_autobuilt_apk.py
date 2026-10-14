"""Offline regression tests for ACTUAL compile-and-embed pipeline, no Docker."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / 'patches/dfroot/legacy-ksu/apply_stage.py'
VERIFY = ROOT / 'tools/verify-c3u-autobuilt-apk.py'
GOOD = ROOT / 'known-good/working-v6.ko'
REF = '78ed5d1f5b5041a197f0b55291876d62a6bd7c67'
GOOD_SHA = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'
NAME = 'KernelSU-Next-C3U-REBUILT-UNVERIFIED-DO-NOT-LOAD.ko'


def imported(path: Path, key: str):
    spec = importlib.util.spec_from_file_location(key, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class AutobuiltIntegrationTests(unittest.TestCase):
    def test_source_loader_does_not_replace_tested_module_by_default(self):
        loader = imported(STAGE, 'ksu_staging_default')
        self.assertEqual(loader.select_module(ROOT), GOOD)
        self.assertEqual(hashlib.sha256(GOOD.read_bytes()).hexdigest(), GOOD_SHA)

    def test_no_compiled_module_never_falls_back(self):
        loader = imported(STAGE, 'ksu_staging_fail_closed')
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'NEVER fall back'):
                loader.select_module(Path(tmp), compiled=True)

    def test_compiled_module_identity_and_size_guard(self):
        loader = imported(STAGE, 'ksu_staging_compiled')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            dist = tmp / 'dist-ksunext-reference'
            dist.mkdir()
            # Append inert bytes to the known-good ELF for a *file-handling*
            # regression case only. This is NOT a loadable/device-tested module.
            blob = GOOD.read_bytes() + b'COMPILER_OUTPUT_TEST_PAD'
            rebuilt = dist / NAME
            rebuilt.write_bytes(blob)
            sha = hashlib.sha256(blob).hexdigest()
            (dist / 'rebuilt-module.sha256').write_text(f'{sha}  {NAME}\n')
            (dist / 'source-commit.txt').write_text(REF+'\n')
            (dist / 'layout-report.txt').write_text('offline targeted ABI checks passed\n')
            (dist / 'module-comparison.json').write_text(json.dumps({
                'source_revision': REF,
                'rebuilt_candidate': {'sha256': sha, 'vermagic': '5.15.202'},
                'device_tested_known_good': {'sha256': GOOD_SHA, 'vermagic': '5.15.202'},
                'candidate_only_undefined_symbols': [],
            }))
            self.assertEqual(loader.select_module(tmp, compiled=True), rebuilt)
            source = (ROOT/'patches/dfroot/legacy-ksu/c3u_ksu_stage.c').read_text()
            generated, staged = loader.compiled_stage_files(source, len(blob))
            self.assertIn(f'if (len != {len(blob)})', generated)
            self.assertIn('c3u-autobuilt.ko', generated)
            self.assertEqual(staged, 'ko/c3u-autobuilt.ko')
            self.assertIn('if (len != 6797960)', source)  # unchanged known-good template
            # A newly added kernel symbol must stop packaging.
            report = json.loads((dist / 'module-comparison.json').read_text())
            report['candidate_only_undefined_symbols'] = ['unverified_new_symbol']
            (dist / 'module-comparison.json').write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, 'New undefined kernel symbols'):
                loader.select_module(tmp, compiled=True)

    def test_final_apk_check_identifies_real_embedded_bytes(self):
        verifier = imported(VERIFY, 'c3u_verified_apk')
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ko = tmp / 'compiled.ko'
            ko.write_bytes(GOOD.read_bytes())
            raw = ko.read_bytes()
            apk = tmp / 'assembled.apk'
            def write_apk(payload):
                with zipfile.ZipFile(apk, 'w', compression=zipfile.ZIP_STORED) as z:
                    z.writestr('lib/arm64-v8a/libc3uksu.so',
                               b'c3u-autobuilt.ko\x00/data/user_de/0/df.root/ksud\x00' + payload)
                    for lib in ('libbootstrap.so', 'libdfroot.so', 'libdfrootsu.so'):
                        z.writestr('lib/arm64-v8a/' + lib, b'placeholder')
            write_apk(raw)
            manifest = tmp / 'build-manifest.json'
            def write_manifest():
                manifest.write_text(json.dumps({
                    'kernelsu': {'selection': 'ci-compiled-unverified',
                                 'source_revision': REF, 'sha256': hashlib.sha256(raw).hexdigest(),
                                 'bytes': len(raw)},
                    'apk': {'sha256': hashlib.sha256(apk.read_bytes()).hexdigest()},
                }))
            write_manifest()
            self.assertEqual(verifier.verify(apk, ko, manifest), hashlib.sha256(raw).hexdigest())
            write_apk(b'not-the-same-as-compiled-output')
            write_manifest()
            with self.assertRaisesRegex(ValueError, 'EXACTLY ONE byte-identical'):
                verifier.verify(apk, ko, manifest)

    def test_workflow_is_actual_compilation_then_packaging(self):
        workflow = (ROOT/'.github/workflows/build-legacy-manager-ksu.yml').read_text()
        wrapper = (ROOT/'tools/build-c3u-autobuilt-apk.sh').read_text()
        build = (ROOT/'tools/build-legacy-manager-ksu.sh').read_text()
        self.assertIn('compile-and-embed-kernelsu:', workflow)
        self.assertNotIn('reference-module-candidate:', workflow)
        self.assertIn('bash tools/build-c3u-autobuilt-apk.sh', workflow)
        self.assertLess(wrapper.index('build-ksunext-tested-ref-candidate.sh'),
                        wrapper.index('C3U_EMBED_REBUILT_KSU=1'))
        self.assertIn('SELECTED_KSU="$REBUILT_KSU"', build)
        self.assertIn('"${STAGE_ARG[@]}"', build)
        self.assertIn('loader.count(ksu.read_bytes()) != 1', build)
        self.assertIn('ci-compiled-unverified', build)
        self.assertIn('DFRoot-C3U-AUTOBUILT-KSUNEXT-UNVERIFIED.apk', build)
        self.assertNotIn('C3URootForegroundService', build)


if __name__ == '__main__':
    unittest.main()
