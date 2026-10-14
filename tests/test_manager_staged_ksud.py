"""C3U regression checks: preloader and late-load must use Manager-staged ksud.

These tests do not load modules or require a connected C3U projector.
"""
import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "patches/dfroot/overlay"
SPEC = importlib.util.spec_from_file_location("c3u_apply_v7_for_test", OVERLAY / "apply_c3u_v7.py")
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


class ManagerStagedKsudTests(unittest.TestCase):
    # Exact DFRoot v3.1 late-load block (the version our patcher supports).
    ORIGINAL = '''    char **late_load;
    if (soft_reboot)
        late_load = (char *[]){ KSUD, "late-load", "--package-name", su_manager, "--soft-reboot", NULL };
    else
        late_load = (char *[]){ KSUD, "late-load", "--package-name", su_manager, NULL };'''
    DEFINE = '#define KSUD       "/data/user_de/0/df.root/ksud"'

    def bootstrap_fixture(self):
        return '\n'.join([
            self.DEFINE,
            'int dfroot_start_root_service(void);',
            'void touch(const char *path);',
            'int main(void) {',
            '    touch("/dev/dfm6");',
            '    touch("/dev/dfm1");',
            '    if (dfroot_start_root_service()) touch("/dev/dfsu0");',
            '    else touch("/dev/dfsue0");',
            '    touch("/dev/dfm2");',
            '    int soft_reboot = 0;',
            '    char *su_manager = "com.rifsxd.ksunext";',
            self.ORIGINAL,
            '    if (run(late_load) == 0) touch("/dev/dfm4");',
            '    else touch("/dev/dfm5");',
            '    return 0;',
            '}',
        ]) + '\n'

    def test_native_preloader_uses_only_manager_staged_ksud(self):
        source = (OVERLAY / "c3u_ksu_preload.c").read_text()
        self.assertIn('#define C3U_MANAGER_KSUD "/data/user_de/0/df.root/ksud"', source)
        self.assertIn('const char *ksud = C3U_MANAGER_KSUD;', source)
        self.assertIn('c3u_run_insmod(ksud)', source)
        self.assertNotIn('"/data/adb/ksud"', source)
        # Neither root shell, exact-firmware restrictions nor permissive checks disappear.
        for item in ('C3U_EXACT_KERNEL', 'C3U_EXACT_FINGERPRINT',
                     'c3u_is_permissive()', 'c3u_is_live()'):
            self.assertIn(item, source)

    def test_rewrites_only_the_unsupported_soft_reboot_branch(self):
        original = self.bootstrap_fixture()
        rewritten = PATCHER.normalize_manager_ksud_late_load(original)
        self.assertIn(self.DEFINE, rewritten)
        self.assertIn(PATCHER.LATE_LOAD_MARKER, rewritten)
        self.assertIn('char *late_load[] = { KSUD, "late-load", "--package-name", su_manager, NULL };', rewritten)
        self.assertNotIn('"--soft-reboot"', rewritten)
        self.assertIn('touch("/dev/dfm6")', rewritten)
        self.assertEqual(PATCHER.normalize_manager_ksud_late_load(rewritten), rewritten)

    def test_refuses_changed_ksud_path_or_cli(self):
        original = self.bootstrap_fixture()
        with self.assertRaisesRegex(ValueError, "KSUD path changed"):
            PATCHER.normalize_manager_ksud_late_load(original.replace(self.DEFINE, '#define KSUD "/data/adb/ksud"'))
        with self.assertRaisesRegex(ValueError, "late-load command changed"):
            PATCHER.normalize_manager_ksud_late_load(original.replace('"--soft-reboot"', '"--reboot"'))

    def test_patcher_wires_same_binary_before_late_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            jni = repo / 'app/src/main/jni'
            jni.mkdir(parents=True)
            (jni / 'bootstrap.c').write_text(self.bootstrap_fixture())
            (jni / 'CMakeLists.txt').write_text('target_sources(bootstrap PRIVATE rootshell.c)\n')
            (jni / 'exp.c').write_text('/* C3U_ONLY_KMI_ANDROID14_5_15 */\n')

            # Minimal synthetic AArch64 ELF containing the markers checked by the
            # patcher; not an operational kernel module.
            ko = bytearray(65536)
            ko[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<H', ko, 18, 183)
            ko[512:512 + len(b'C3U: preserving permissive SELinux')] = b'C3U: preserving permissive SELinux'
            ko[1024:1024 + len(b'vermagic=5.15.')] = b'vermagic=5.15.'
            ko_path = repo / 'fixture.ko'
            ko_path.write_bytes(ko)

            PATCHER.patch(repo, ko_path, OVERLAY)
            result = (jni / 'bootstrap.c').read_text()
            self.assertIn('dfroot_start_root_service()', result)
            self.assertIn('if (c3u_ksu_preload() == 0)', result)
            self.assertLess(result.index('if (c3u_ksu_preload() == 0)'), result.index('touch("/dev/dfm2")'))
            self.assertNotIn('"--soft-reboot"', result)
            self.assertIn('char *late_load[] = { KSUD, "late-load"', result)
            self.assertEqual((jni / 'c3u_ksu_preload.c').read_bytes(), (OVERLAY / 'c3u_ksu_preload.c').read_bytes())
            metadata = json.loads((jni / 'c3u-v7-manifest.json').read_text())
            self.assertEqual(metadata['ksud_staged_path'], '/data/user_de/0/df.root/ksud')
            # No partial double-injection on a repeated run.
            PATCHER.patch(repo, ko_path, OVERLAY)
            self.assertEqual((jni / 'bootstrap.c').read_text(), result)


if __name__ == '__main__':
    unittest.main()
