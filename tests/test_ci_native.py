from pathlib import Path
import importlib.util
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('verify_native', ROOT/'tools/verify-apk-native.py')
verify_native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_native)


class ApkNativeTests(unittest.TestCase):
    def test_missing_native_lib_fails(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t)/'test.apk'
            with ZipFile(path, 'w') as z:
                z.writestr('AndroidManifest.xml', b'manifest')
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'libexp.so'):
                    verify_native.verify(path)

    def test_native_with_exact_ko_passes(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            ko = p/'c3u.ko'
            payload = b'\x7fELF' + b'X'*100000
            ko.write_bytes(payload)
            apk = p/'test.apk'
            with ZipFile(apk, 'w') as z:
                z.writestr('lib/arm64-v8a/libexp.so', b'\x7fELF' + b'EXPLOIT' + payload)
                z.writestr('lib/arm64-v8a/libdfrootsu.so', b'\x7fELF' + b'CLIENT')
            with redirect_stdout(io.StringIO()):
                verify_native.verify(apk, ko)

    def test_wrong_ko_fails_closed(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t)
            ko = p/'c3u.ko'
            ko.write_bytes(b'\x7fELF' + b'A'*100000)
            apk = p/'test.apk'
            with ZipFile(apk, 'w') as z:
                z.writestr('lib/arm64-v8a/libexp.so', b'\x7fELF' + b'B'*100000)
                z.writestr('lib/arm64-v8a/libdfrootsu.so', b'\x7fELF' + b'CLIENT')
            with redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError, 'Exact C3U KernelSU'):
                    verify_native.verify(apk, ko)

    def test_native_build_before_gradle(self):
        text = (ROOT/'patches/dfroot/build-in-docker.sh').read_text()
        self.assertLess(text.index('build-native-in-docker.sh /work'),
                        text.index('./gradlew :app:assembleRelease'))
        text2 = (ROOT/'patches/dfroot/build-native-in-docker.sh').read_text()
        self.assertIn('jniLibs/arm64-v8a', text2)
        self.assertIn('android14-5.15.ko', text2)
        self.assertIn('CMAKE_TOOLCHAIN_FILE', text2)

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
