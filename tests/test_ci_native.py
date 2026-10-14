"""Regression tests for actual DFRoot v3.1 ARM64 output names.

The exploit executable is libdfroot.so. The privileged bootstrap (with the
exact .ko from c3u_ksu_preload.c) is libbootstrap.so. There is no libexp.so.
"""
from pathlib import Path
import importlib.util
import io
import os
import subprocess
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_native', ROOT/'tools/verify-apk-native.py')
verify_native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_native)


class ApkNativeTests(unittest.TestCase):
    @staticmethod
    def make_apk(apk: Path, bootstrap: bytes, dfroot: bytes = b'\x7fELFexploit',
                 client: bytes = b'\x7fELFclient') -> None:
        with ZipFile(apk, 'w') as z:
            z.writestr('AndroidManifest.xml', b'manifest')
            z.writestr('lib/arm64-v8a/libbootstrap.so', bootstrap)
            z.writestr('lib/arm64-v8a/libdfroot.so', dfroot)
            z.writestr('lib/arm64-v8a/libdfrootsu.so', client)

    def test_missing_native_lib_fails(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'test.apk'
            with ZipFile(path, 'w') as z:
                z.writestr('AndroidManifest.xml', b'manifest')
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'libdfroot.so'):
                    verify_native.verify(path)

    def test_native_with_exact_ko_passes_without_libexp(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            ko = p/'c3u.ko'
            payload = b'\x7fELF' + b'X'*100000
            ko.write_bytes(payload)
            apk = p/'test.apk'
            self.make_apk(apk, b'\x7fELFbootstrap' + payload)
            with redirect_stdout(io.StringIO()):
                verify_native.verify(apk, ko)
            with ZipFile(apk) as z:
                self.assertNotIn('lib/arm64-v8a/libexp.so', z.namelist())

    def test_wrong_ko_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            ko = p/'c3u.ko'
            ko.write_bytes(b'\x7fELF' + b'A'*100000)
            apk = p/'test.apk'
            self.make_apk(apk, b'\x7fELF' + b'B'*100000)
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'Exact C3U KernelSU'):
                    verify_native.verify(apk, ko)

    def test_wrong_library_ko_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            ko = p/'c3u.ko'
            payload = b'\x7fELF' + b'A'*100000
            ko.write_bytes(payload)
            apk = p/'test.apk'
            self.make_apk(apk, b'\x7fELFbootstrap', b'\x7fELFexploit' + payload)
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'libbootstrap.so'):
                    verify_native.verify(apk, ko)

    def test_obsolete_only_libexp_fails(self):
        with tempfile.TemporaryDirectory() as t:
            apk = Path(t)/'test.apk'
            with ZipFile(apk, 'w') as z:
                z.writestr('lib/arm64-v8a/libexp.so', b'\x7fELF')
                z.writestr('lib/arm64-v8a/libdfrootsu.so', b'\x7fELF')
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'libdfroot.so'):
                    verify_native.verify(apk)

    def test_gradle_owns_cmake_targets_and_client_fallback_is_conditional(self):
        script = (ROOT/'patches/dfroot/build-in-docker.sh').read_text()
        # Gradle must compile/package its existing CMake library targets,
        # with no extra copies of those targets in jniLibs.
        self.assertIn('rm -f "$stage/libbootstrap.so" "$stage/libdfroot.so"', script)
        self.assertIn('rm -f "$stage/libbootstrap.so" "$stage/libdfroot.so"', script)
        self.assertLess(script.index('rm -f "$stage/libbootstrap.so"'),
                        script.index('./gradlew :app:assembleRelease'))
        self.assertIn('unzip -Z1 "$apk"', script)
        self.assertIn('if unzip -Z1 "$apk" | grep -Fxq "lib/arm64-v8a/libdfrootsu.so"', script)
        self.assertLess(script.index('if unzip -Z1 "$apk" | grep -Fxq "lib/arm64-v8a/libdfrootsu.so"'),
                        script.index('/tooling/build-native-in-docker.sh /work'))
        self.assertEqual(script.count('./gradlew :app:assembleRelease'), 2)
        fallback = (ROOT/'patches/dfroot/build-native-in-docker.sh').read_text()
        self.assertIn('--target dfrootsu', fallback)
        self.assertIn('install -m 0644 "$client" "$stage/libdfrootsu.so"', fallback)
        self.assertNotIn('install -m 0644 "$candidate"', fallback)
        self.assertIn('CMAKE_TOOLCHAIN_FILE', fallback)

    def test_native_fallback_only_stages_root_client(self):
        # Fake CMake and a minimal AArch64 ELF let us test the actual fallback
        # script without needing a Docker daemon or the Android NDK.
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            repo = p/'DFRoot'
            jni = repo/'app/src/main/jni'
            (jni/'ko').mkdir(parents=True)
            (jni/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.18)\n')
            (jni/'ko/dfroot-android14-5.15.ko').write_bytes(b'KO')
            (jni/'ko/c3u-ksunext-v6.ko').write_bytes(b'KO')
            ndk = p/'fake-ndk'
            toolchain = ndk/'build/cmake/android.toolchain.cmake'
            toolchain.parent.mkdir(parents=True)
            toolchain.write_text('dummy')
            ident = b'\x7fELF' + bytes((2, 1, 1)) + bytes(9)
            elf = struct.pack('<16sHHIQQQIHHHHHH', ident, 3, 183, 1, 0, 0, 0, 0,
                              64, 0, 0, 0, 0, 0)
            fake_elf = p/'fake-arm64.so'
            fake_elf.write_bytes(elf)
            fake_cmake = p/'fake-cmake.sh'
            fake_cmake.write_text('#!/bin/sh\nset -eu\n'
                                  'if [ "${1:-}" = "--build" ]; then\n'
                                  '  [ "${3:-}" = "--target" ] && [ "${4:-}" = "dfrootsu" ] || exit 12\n'
                                  f'  mkdir -p "{repo}/.c3u-native-build/artifacts"\n'
                                  f'  cp "{fake_elf}" "{repo}/.c3u-native-build/artifacts/libdfrootsu.so"\n'
                                  'fi\n')
            fake_cmake.chmod(0o755)
            env = os.environ.copy()
            env.update({'C3U_CMAKE': str(fake_cmake),
                        'ANDROID_NDK_HOME': str(ndk)})
            res = subprocess.run(['bash', str(ROOT/'patches/dfroot/build-native-in-docker.sh'),
                                  str(repo)], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn('Staged standalone client ONLY', res.stdout)
            stage = repo/'app/src/main/jniLibs/arm64-v8a'
            self.assertEqual({x.name for x in stage.glob('*.so')}, {'libdfrootsu.so'})

    def test_native_fallback_refuses_duplicate_gradle_libraries(self):
        with tempfile.TemporaryDirectory() as t:
            repo = Path(t)/'DFRoot'
            jni = repo/'app/src/main/jni'
            (jni/'ko').mkdir(parents=True)
            (jni/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.18)\n')
            (jni/'ko/dfroot-android14-5.15.ko').write_bytes(b'KO')
            (jni/'ko/c3u-ksunext-v6.ko').write_bytes(b'KO')
            stage = repo/'app/src/main/jniLibs/arm64-v8a'
            stage.mkdir(parents=True)
            (stage/'libbootstrap.so').write_bytes(b'\x7fELF')
            res = subprocess.run(['bash', str(ROOT/'patches/dfroot/build-native-in-docker.sh'),
                                  str(repo)], capture_output=True, text=True)
            self.assertNotEqual(res.returncode, 0)
            self.assertIn('must not run', res.stderr)

    def test_duplicate_apk_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            apk = Path(t)/'test.apk'
            with ZipFile(apk, 'w') as z:
                z.writestr('lib/arm64-v8a/libbootstrap.so', b'\x7fELF')
                z.writestr('lib/arm64-v8a/libbootstrap.so', b'\x7fELF')
                z.writestr('lib/arm64-v8a/libdfroot.so', b'\x7fELF')
                z.writestr('lib/arm64-v8a/libdfrootsu.so', b'\x7fELF')
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'duplicate'):
                    verify_native.verify(apk)

    def test_gradle_merge_simulated_with_or_without_native_client(self):
        # Run the real Android-container packaging fragment with a simulated
        # Gradle output. Verify stale jniLibs are removed before MergeNativeLibs
        # and the optional client gets staged only when actually missing.
        shell = (ROOT/'patches/dfroot/build-in-docker.sh').read_text()
        sentinel = '  "$builder" bash -euc ' + chr(39) + '\n'
        begin = shell.index(sentinel) + len(sentinel)
        finish = shell.index('\n  ' + chr(39) + '\n[[ -s', begin)
        fragment = shell[begin:finish].replace('/tooling/build-native-in-docker.sh /work',
                                               'bash ./fake-client.sh .')
        gradle_script = '''#!/usr/bin/env python3
import os
from pathlib import Path
from zipfile import ZipFile
stage = Path('app/src/main/jniLibs/arm64-v8a')
out = Path('app/build/outputs/apk/release')
out.mkdir(parents=True, exist_ok=True)
for name in ('libbootstrap.so', 'libdfroot.so'):
    if (stage / name).exists():
        raise SystemExit('DUPLICATE INPUT: ' + name)
if (stage / 'libdfrootsu.so').exists() and os.getenv('INCLUDE_CLIENT') == '1':
    raise SystemExit('DUPLICATE INPUT: libdfrootsu.so')
with ZipFile(out/'DFRoot_test.apk', 'w') as z:
    z.writestr('lib/arm64-v8a/libbootstrap.so', b'ELF-bootstrap')
    z.writestr('lib/arm64-v8a/libdfroot.so', b'ELF-exploit')
    if os.getenv('INCLUDE_CLIENT') == '1' or (stage / 'libdfrootsu.so').exists():
        z.writestr('lib/arm64-v8a/libdfrootsu.so', b'ELF-client')
with open('build-count.txt', 'a') as f:
    f.write('1\\n')
'''
        for contains_client in (True, False):
            with self.subTest(contains_client=contains_client), tempfile.TemporaryDirectory() as t:
                wd = Path(t)
                (wd/'gradlew').write_text(gradle_script)
                (wd/'gradlew').chmod(0o755)
                (wd/'fake-client.sh').write_text('''#!/bin/sh
set -eu
mkdir -p app/src/main/jniLibs/arm64-v8a
printf client > app/src/main/jniLibs/arm64-v8a/libdfrootsu.so
''')
                (wd/'fake-client.sh').chmod(0o755)
                bin_dir = wd/'bin'
                bin_dir.mkdir()
                (bin_dir/'make').write_text('#!/bin/sh\nexit 0\n')
                (bin_dir/'make').chmod(0o755)
                stage = wd/'app/src/main/jniLibs/arm64-v8a'
                stage.mkdir(parents=True)
                for name in ('libbootstrap.so', 'libdfroot.so', 'libdfrootsu.so'):
                    (stage/name).write_bytes(b'stale')
                env = os.environ.copy()
                env['PATH'] = f'{bin_dir}:{env["PATH"]}'
                env['INCLUDE_CLIENT'] = '1' if contains_client else '0'
                result = subprocess.run(['bash', '-euc', fragment], cwd=wd,
                                        capture_output=True, text=True, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                expected_passes = 1 if contains_client else 2
                self.assertEqual((wd/'build-count.txt').read_text().count('1'), expected_passes)
                self.assertFalse((stage/'libbootstrap.so').exists())
                self.assertFalse((stage/'libdfroot.so').exists())
                self.assertEqual((stage/'libdfrootsu.so').exists(), not contains_client)
                with ZipFile(wd/'out/DFRoot.apk') as z:
                    self.assertEqual(set(z.namelist()), {
                        'lib/arm64-v8a/libbootstrap.so',
                        'lib/arm64-v8a/libdfroot.so',
                        'lib/arm64-v8a/libdfrootsu.so',
                    })

    def test_caching_wired(self):
        workflow = (ROOT/'.github/workflows/build.yml').read_text()
        self.assertIn('actions/cache/restore@v4', workflow)
        self.assertIn('actions/cache/save@v4', workflow)
        self.assertIn('docker/setup-buildx-action@v3', workflow)
        text = (ROOT/'patches/dfroot/build-in-docker.sh').read_text()
        self.assertIn('type=gha,scope=c3u-android-sdk', text)
        self.assertIn('dfroot-ko/$ko_key.ko', text)


if __name__ == '__main__':
    unittest.main()
