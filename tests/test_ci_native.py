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

    def test_native_build_before_gradle(self):
        text = (ROOT/'patches/dfroot/build-in-docker.sh').read_text()
        self.assertLess(text.index('build-native-in-docker.sh /work'),
                        text.index('./gradlew :app:assembleRelease'))
        text2 = (ROOT/'patches/dfroot/build-native-in-docker.sh').read_text()
        self.assertIn('jniLibs/arm64-v8a', text2)
        self.assertIn('android14-5.15.ko', text2)
        self.assertIn('CMAKE_TOOLCHAIN_FILE', text2)
        for library in ('libdfroot.so', 'libbootstrap.so', 'libdfrootsu.so'):
            self.assertIn(library, text2)

    def test_native_stager_accepts_three_real_cmake_outputs(self):
        # Fake the CMake process, not the validation: the stager itself runs
        # against three minimal AArch64 ELF files and must NOT demand libexp.
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
            # Valid enough ELF64/AArch64 for readelf -h; only machine is
            # relevant to staging, which should not accept host x86_64 ELFs.
            ident = b'\x7fELF' + bytes((2, 1, 1)) + bytes(9)
            elf = struct.pack('<16sHHIQQQIHHHHHH', ident, 3, 183, 1, 0, 0, 0, 0,
                              64, 0, 0, 0, 0, 0)
            fake_elf = p/'fake-arm64.so'
            fake_elf.write_bytes(elf)
            fake_cmake = p/'fake-cmake.sh'
            fake_cmake.write_text('#!/bin/sh\nset -eu\n'
                                  'if [ "${1:-}" = "--build" ]; then\n'
                                  f'  mkdir -p "{repo}/.c3u-native-build/artifacts"\n'
                                  '  for name in libbootstrap.so libdfroot.so libdfrootsu.so; do\n'
                                  f'    cp "{fake_elf}" "{repo}/.c3u-native-build/artifacts/$name"\n'
                                  '  done\nfi\n')
            fake_cmake.chmod(0o755)
            env = os.environ.copy()
            env.update({'C3U_CMAKE': str(fake_cmake),
                        'ANDROID_NDK_HOME': str(ndk)})
            res = subprocess.run(['bash', str(ROOT/'patches/dfroot/build-native-in-docker.sh'),
                                  str(repo)], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertIn('Staged native binary: libbootstrap.so', res.stdout)
            self.assertIn('Staged native binary: libdfroot.so', res.stdout)
            self.assertIn('Staged native binary: libdfrootsu.so', res.stdout)
            for lib in ('libdfroot.so', 'libbootstrap.so', 'libdfrootsu.so'):
                self.assertTrue((repo/'app/src/main/jniLibs/arm64-v8a'/lib).is_file())

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
