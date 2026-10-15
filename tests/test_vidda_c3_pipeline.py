"""Regression guards for the single maintained Vidda C3 compile-and-embed build."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'patches/dfroot/legacy-ksu/c3u_ksu_stage.c'
BASELINE = ROOT / 'config/kernel-abi-baseline.json'
WORKFLOW = ROOT / '.github/workflows/build-vidda-c3.yml'
TRUSTED_DFROOT_SHA = '5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473'
TRUSTED_KSU_SHA = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'


def load(file: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class ViddaC3SingleBuild(unittest.TestCase):
    def test_one_workflow_and_one_source_build(self):
        workflows = list((ROOT / '.github/workflows').glob('*.yml'))
        self.assertEqual(workflows, [WORKFLOW])
        yml = WORKFLOW.read_text()
        self.assertIn('name: Build Vidda C3 Root', yml)
        self.assertIn('branches: [master]', yml)
        self.assertIn('workflow_dispatch:', yml)
        self.assertIn('default: dev', yml)
        self.assertIn('run: bash tools/build-vidda-c3.sh', yml)
        self.assertIn('name: vidda-c3-root-', yml)
        self.assertNotIn('use_known_good', yml)
        self.assertNotIn('pull-requests: write', yml)
        self.assertIn('ViddaC3-Root.apk', yml)
        sh = (ROOT/'tools/build-vidda-c3.sh').read_text()
        self.assertLess(sh.index('build-kernelsu.sh'), sh.index('build-dfroot.sh'))
        self.assertIn('prepare-apk-signing.py" --check', sh)
        self.assertIn('verify-vidda-c3-apk.py', sh)

    def test_both_modules_are_source_built_without_reference_hash_gate(self):
        self.assertFalse((ROOT/'known-good/working-v6.ko').exists())
        self.assertFalse((ROOT/'known-good/working-v6.sha256').exists())
        self.assertFalse((ROOT/'assets/dfroot-helper-6de6222.ko').exists())
        self.assertFalse((ROOT/'assets/dfroot-helper-6de6222.sha256').exists())
        helper_baseline = json.loads((ROOT/'config/dfroot-helper-baseline.json').read_text())
        self.assertEqual(helper_baseline['device_tested_module_sha256'], TRUSTED_DFROOT_SHA)
        self.assertEqual(helper_baseline['device_tested_module_bytes'], 12232)
        self.assertEqual(helper_baseline['source_sha256'], '1a661b6231030d3ccc1578345825831825baf1e966be2bde498f6d8d8e8ac0e6')
        self.assertEqual(helper_baseline['makefile_sha256'], 'e7708a6338001960c1155c21e500c8f98aeb60c800effe56efa1d5137659306f')
        helper_build = (ROOT/'tools/build-dfroot-helper.sh').read_text()
        for expected in ('docker run', 'make -j', 'llvm-objcopy --strip-unneeded',
                         'android14-5.15-20260828', 'dfroot_commit',
                         'source_sha256', 'makefile_sha256',
                         'not an ARM64 ELF relocatable module', 'SHA-256={digest}'):
            self.assertIn(expected, helper_build)
        wrapper = (ROOT/'tools/build-dfroot.sh').read_text()
        self.assertIn('6de62220809a678fddbd3819e4fcb3bb68aa1eae', wrapper)
        self.assertLess(wrapper.index('prepare-dfroot.py'), wrapper.index('build-dfroot-helper.sh'))
        self.assertLess(wrapper.index('build-dfroot-helper.sh'), wrapper.index('apply_stage.py'))
        self.assertLess(wrapper.index('build-dfroot-helper.sh'), wrapper.index('assembleRelease'))
        self.assertIn('ViddaC3-DFRoot-Helper.ko', wrapper)
        self.assertIn('helper_sha256', wrapper)
        self.assertIn('helper_matches_reference', wrapper)
        self.assertIn("'helper_selection':'compiled-from-pinned-source'", wrapper)
        self.assertIn("'status': 'CI_BUILD_COMPLETE'", wrapper)
        self.assertNotIn('both DFRoot and KernelSU modules', wrapper)
        self.assertNotIn('device-test-pending', wrapper)
        self.assertNotIn('WARNING: DFRoot helper differs', helper_build)
        self.assertNotIn('sha256sum -c -', wrapper)
        self.assertNotIn('compiled-from-pinned-source-byte-identical-to-device-tested', wrapper)
        self.assertNotIn('DFRoot helper output differs from DEVICE-TESTED binary', helper_build)
        self.assertIn('ViddaC3-KernelSU-Next.ko', wrapper)
        self.assertNotIn('assets/dfroot-helper-6de6222.ko', wrapper)
        self.assertNotIn('GOOD_KSU', wrapper)
        self.assertIn("500000 + int(env['GITHUB_RUN_NUMBER'])", (ROOT/'tools/prepare-apk-signing.py').read_text())
        baseline = json.loads(BASELINE.read_text())
        self.assertEqual(baseline['sha256'], TRUSTED_KSU_SHA)
        self.assertEqual(baseline['undefined_count'], 232)
        self.assertEqual(len(baseline['undefined_symbols']), 232)
        self.assertEqual(baseline['vermagic'], '5.15.202 SMP preempt mod_unload modversions aarch64')

    def test_helper_hash_warning_removed_without_losing_checks(self):
        helper_script = (ROOT/'tools/build-dfroot-helper.sh').read_text()
        apk_builder = (ROOT/'tools/build-dfroot.sh').read_text()
        for required in ('dfroot_commit', 'source_sha256', 'makefile_sha256',
                         'not an ARM64 ELF relocatable module', 'SHA-256={digest}'):
            self.assertIn(required, helper_script)
        self.assertNotIn('WARNING: DFRoot helper', helper_script)
        self.assertNotIn('historical device-tested artifact', helper_script)
        self.assertIn("'helper_sha256':helper_sha", apk_builder)
        self.assertIn("'helper_matches_reference':helper_sha == sys.argv[3]", apk_builder)
        self.assertIn('old.count(helper.read_bytes()) != 1', apk_builder)
        self.assertIn('KernelSU Next is compiled from a selectable upstream ref', apk_builder)
        self.assertNotIn('both DFRoot and KernelSU modules', apk_builder)

    def test_docker_helper_precreates_writable_jni_directory(self):
        """Docker must not become owner of the directory used by apply_stage.py."""
        helper_build = (ROOT / 'tools/build-dfroot-helper.sh').read_text()
        directory = 'STAGING_DIR="$(dirname "$TARGET")"'
        create = 'mkdir -p -- "$STAGING_DIR"'
        preflight = '[[ ! -w "$STAGING_DIR" ]]'
        docker = 'docker run --rm'
        self.assertEqual(helper_build.count(directory), 1)
        self.assertEqual(helper_build.count(create), 1)
        self.assertEqual(helper_build.count(preflight), 1)
        self.assertLess(helper_build.index(directory), helper_build.index(docker))
        self.assertLess(helper_build.index(create), helper_build.index(docker))
        self.assertLess(helper_build.index(preflight), helper_build.index(docker))
        self.assertIn('c3u-autobuilt.ko', helper_build)

    def test_abi_comparison_is_offline_without_static_binary(self):
        c = load(ROOT/'tools/compare-kernelsu-abi.py', 'vidda_abi')
        baseline = c.load_baseline(BASELINE)
        candidate = dict(baseline)
        candidate['sha256'] = 'a' * 64
        candidate['undefined_symbols'] = baseline['undefined_symbols'] + ['new_unverified_symbol']
        candidate['undefined_count'] += 1
        with patch.object(c, 'metadata', return_value=candidate):
            result = c.compare(BASELINE, Path('/nonexistent/build.ko'), 'b'*40)
        self.assertEqual(result['candidate_only_undefined_symbols'], ['new_unverified_symbol'])
        self.assertFalse(result['candidate_matches_known_good_bytes'])
        self.assertEqual(result['source_revision'], 'b'*40)

    def test_stage_always_requires_compiled_attested_kernel_module(self):
        stage = load(ROOT/'patches/dfroot/legacy-ksu/apply_stage.py', 'vidda_stage')
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, 'no fallback'):
                stage.select_module(Path(td))
        source = SOURCE.read_text()
        self.assertIn('__VIDDA_C3_KO_SIZE__', source)
        self.assertNotIn('6797960', source)
        patched, embedded = stage.compiled_stage_files(source, 6800000)
        self.assertIn('if (len != 6800000)', patched)
        self.assertNotIn('__VIDDA_C3_KO_SIZE__', patched)
        self.assertEqual(embedded, 'ko/c3u-autobuilt.ko')
        self.assertEqual(patched.count('c3u-autobuilt.ko'), 2)
        self.assertNotIn('c3u-working-v6.ko', patched)

    def test_manifest_keeps_upgrade_identity_and_new_brand(self):
        branded = load(ROOT/'patches/dfroot/set-app-name.py', 'vidda_brand')
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'app/src/main'
            path.mkdir(parents=True)
            (path / 'AndroidManifest.xml').write_text('<manifest package="df.root"><application android:label="DFRoot"/></manifest>')
            branded.apply(Path(td))
            updated = (path / 'AndroidManifest.xml').read_text()
            self.assertIn('android:label="Vidda C3 Root"', updated)
            self.assertIn('package="df.root"', updated)
        service = (ROOT/'patches/dfroot/legacy-ksu/android-service/C3URootForegroundService.java').read_text()
        self.assertIn('"Vidda C3 Root"', service)
        self.assertIn('"Vidda C3 root operation"', service)

    def test_apk_verifier_uses_the_new_output_layout(self):
        verify = load(ROOT/'tools/verify-vidda-c3-apk.py', 'vidda_apk_verify')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            apkdir = root/'dist/vidda-c3'; apkdir.mkdir(parents=True)
            kodir = root/'dist/vidda-c3-kernelsu'; kodir.mkdir(parents=True)
            payload = b'\x7fELF'+b'test-module-mock'+b'v3.4.2-viddaC3'
            ko = kodir/'ViddaC3-KernelSU-Next.ko'; ko.write_bytes(payload)
            source = {'source_revision':'a'*40, 'version_tag':'v3.4.2-viddaC3','version_code':33355}
            (kodir/'source-version.json').write_text(json.dumps(source))
            apk = apkdir/'ViddaC3-Root.apk'
            with zipfile.ZipFile(apk, 'w') as z:
                z.writestr('lib/arm64-v8a/libc3uksu.so',
                           b'/data/user_de/0/df.root/ksud\0c3u-autobuilt.ko\0'+payload)
                for name in ('libbootstrap.so', 'libdfroot.so', 'libdfrootsu.so'):
                    z.writestr('lib/arm64-v8a/'+name, b'\x7fELF')
            manifest = apkdir/'build-manifest.json'
            manifest.write_text(json.dumps({
                'kernelsu':dict(source, selection='ci-compiled-unverified', sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload)),
                'apk':{'sha256':hashlib.sha256(apk.read_bytes()).hexdigest()}}))
            self.assertEqual(verify.verify(apk, ko, manifest), hashlib.sha256(payload).hexdigest())

if __name__ == '__main__':
    unittest.main()
