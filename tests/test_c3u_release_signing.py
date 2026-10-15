"""Persistent APK certificate + monotonic versionCode safeguards; no Android SDK needed."""
from __future__ import annotations

import base64
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'tools/prepare-apk-signing.py'
WORKFLOW = ROOT / '.github/workflows/build-vidda-c3.yml'
BUILDER = ROOT / 'tools/build-dfroot.sh'
WRAPPER = ROOT / 'tools/build-vidda-c3.sh'


def load():
    spec = importlib.util.spec_from_file_location('c3u_release_signer', HELPER)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class SigningTests(unittest.TestCase):
    def env(self):
        return {
            'C3U_SIGNING_KEYSTORE_B64': base64.b64encode(b'SIMULATED JKS '*24).decode(),
            'C3U_SIGNING_KEYSTORE_PASSWORD': 'p=assword: !#\\ okay',
            'C3U_SIGNING_KEY_ALIAS': 'dfroot-c3u',
            'C3U_SIGNING_KEY_PASSWORD': 'p=assword: !#\\ okay',
            'GITHUB_RUN_NUMBER': '42',
        }

    def test_missing_credentials_fail_closed(self):
        s = load()
        with self.assertRaisesRegex(ValueError, 'C3U_SIGNING_KEYSTORE_B64'):
            s.credentials({})
        corrupted = self.env()
        corrupted['C3U_SIGNING_KEYSTORE_B64'] = 'not-base64??'
        with self.assertRaisesRegex(ValueError, 'Base64'):
            s.credentials(corrupted)
        invalid = self.env()
        invalid.pop('C3U_SIGNING_KEY_ALIAS')
        with self.assertRaisesRegex(ValueError, 'C3U_SIGNING_KEY_ALIAS'):
            s.credentials(invalid)

    def test_signing_props_and_version_are_staged_privately(self):
        s = load()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            gradle = work/'app/build.gradle.kts'
            gradle.parent.mkdir()
            gradle.write_text('defaultConfig {\n versionCode = 401\n versionName = "4.1"\n}\n')
            code = s.prepare(work, self.env())
            self.assertEqual(code, 500042)
            self.assertEqual(s.version_code(self.env()), 500042)
            props = (work/'signing.properties').read_text()
            self.assertIn('KEYSTORE_FILE=../keystore.jks', props)
            self.assertIn('KEYSTORE_PASSWORD=p\\=assword\\: \\!\\#\\\\ okay', props)
            self.assertIn('KEY_ALIAS=dfroot-c3u', props)
            self.assertEqual((work/'keystore.jks').read_bytes(), b'SIMULATED JKS '*24)
            if os.name != 'nt':
                self.assertEqual((work/'keystore.jks').stat().st_mode & 0o777, 0o600)
                self.assertEqual((work/'signing.properties').stat().st_mode & 0o777, 0o600)
            self.assertIn('versionCode = 500042', gradle.read_text())

    def test_only_disposable_gradle_file_is_accepted(self):
        s = load()
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            (work/'app').mkdir()
            (work/'app/build.gradle.kts').write_text('versionCode = 999\n')
            with self.assertRaisesRegex(ValueError, 'Unexpected upstream'):
                s.prepare(work, self.env())
            self.assertFalse((work/'keystore.jks').exists())

    def test_apk_version_code_increases_on_github_run(self):
        s = load()
        env = self.env()
        self.assertEqual(s.version_code(env), 500042)
        env['GITHUB_RUN_NUMBER'] = '43'
        self.assertEqual(s.version_code(env), 500043)
        env['C3U_APK_VERSION_CODE'] = '201000'
        self.assertEqual(s.version_code(env), 201000)
        env['C3U_APK_VERSION_CODE'] = 'banana'
        with self.assertRaisesRegex(ValueError, 'integer'):
            s.version_code(env)

    def test_ci_uses_one_persistent_secret_identity(self):
        workflow = WORKFLOW.read_text()
        build = BUILDER.read_text()
        wrapper = WRAPPER.read_text()
        self.assertIn('branches: [master]', workflow)
        self.assertIn('default: dev', workflow)
        self.assertIn('run: bash tools/build-vidda-c3.sh', workflow)
        for name in load().NAMES:
            self.assertIn(f'{name}: ${{{{ secrets.{name} }}}}', workflow)
        self.assertIn('prepare-apk-signing.py" "$WORK"', build)
        self.assertIn('prepare-apk-signing.py" --check', wrapper)
        self.assertIn('unset C3U_SIGNING_KEYSTORE_B64', wrapper)
        self.assertNotIn('\n    make signing.properties\n', build)
        self.assertIn('rm -f -- "$WORK/keystore.jks" "$WORK/signing.properties"', build)
        self.assertIn('apksigner" verify', build)
        self.assertIn('signing_certificate_sha256', build)
        self.assertIn('version_code', build)
        self.assertNotIn('keytool -genkeypair', build)


if __name__ == '__main__':
    unittest.main()
