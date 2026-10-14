"""Dynamic KernelSU source selection, C3U safety guards, and Android TV Settings UI."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
KSU_PATCH = ROOT / 'patches/ksunext/dynamic/apply-c3u.py'
TV_PATCH = ROOT / 'patches/dfroot/legacy-ksu/apply_tv_settings.py'


def imported(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DynamicC3UIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ksu = imported(KSU_PATCH, 'ksu_dyn')
        cls.tv = imported(TV_PATCH, 'tv_settings')

    def test_dynamic_git_version_code_and_c3u_suffix(self):
        source = self.ksu.BEFORE + '\n// unchanged kernel code\n'
        kbuild = (self.ksu.VERSION_START + '\n'
                  'KSU_GIT_VERSION := $(shell git rev-list --count HEAD)\n'
                  + self.ksu.VERSION_END + '\n'
                  'ifdef KSU_GIT_VERSION_VALID\n'
                  '$(eval KSU_VERSION=$(shell expr 30000 + $(KSU_GIT_VERSION)))\n'
                  'ccflags-y += -DKSU_VERSION=$(KSU_VERSION)\n'
                  'ccflags-y += -DKSU_VERSION_TAG=\\"$(KSU_VERSION_TAG)\\"\n')
        patched_init, patched_kbuild = self.ksu.patched_sources(source, kbuild, 3355, 'v3.4.2')
        self.assertIn('Permissive SELinux, keeping', patched_init)
        self.assertIn('KSU_GIT_VERSION := 3355', patched_kbuild)
        self.assertIn('KSU_GIT_TAG := v3.4.2-viddaC3', patched_kbuild)
        self.assertNotIn('$(shell git rev-list --count HEAD)', patched_kbuild)
        self.assertIn('$(eval KSU_VERSION=$(shell expr 30000 + $(KSU_GIT_VERSION)))', patched_kbuild)

    def test_refuse_changed_kernel_hooks_and_version_logic(self):
        good = self.ksu.BEFORE
        kb = (self.ksu.VERSION_START + '\nKSU_GIT_VERSION := x\n'
              + self.ksu.VERSION_END + '\nccflags-y += -DKSU_VERSION=$(KSU_VERSION)\n'
              'ccflags-y += -DKSU_VERSION_TAG=\\"$(KSU_VERSION_TAG)\\"\n')
        self.ksu.patched_sources(good, kb, 3355, 'v3.4.2')
        with self.assertRaisesRegex(ValueError, 'SELinux'):
            self.ksu.patched_sources(good.replace('setenforce(true)', 'setenforce(false)'), kb, 3355, 'v3.4.2')
        with self.assertRaisesRegex(ValueError, 'Kbuild'):
            self.ksu.patched_sources(good, kb.replace(self.ksu.VERSION_END, ''), 3355, 'v3.4.2')
        with self.assertRaisesRegex(ValueError, 'tag'):
            self.ksu.patched_sources(good, kb, 3355, 'unsafe;tag')

    def test_workflow_auto_runs_and_manual_ref_is_data(self):
        yml = (ROOT / '.github/workflows/build-legacy-manager-ksu.yml').read_text()
        sh = (ROOT / 'tools/build-ksunext-tested-ref-candidate.sh').read_text()
        self.assertIn('push:', yml)
        self.assertIn('branches: [master]', yml)
        self.assertIn('workflow_dispatch:', yml)
        self.assertIn('ksun_ref:', yml)
        self.assertIn('default: dev', yml)
        self.assertIn("github.event.inputs.ksun_ref || 'dev'", yml)
        self.assertIn('C3U_KSUN_REF:-dev', sh)
        self.assertIn('fetch -q --no-prune --tags origin', sh)
        self.assertNotIn('--depth=1', sh)
        self.assertIn('checkout -q --detach "$TARGET"', sh)
        self.assertIn('apply-c3u.py', sh)
        self.assertIn('--source-revision "$SOURCE_SHA"', sh)
        self.assertIn('C3U_EMBED_REBUILT_KSU=1', (ROOT/'tools/build-c3u-autobuilt-apk.sh').read_text())

    def test_android_tv_settings_is_real_visible_button(self):
        before = '''package df.root;\n    private Button btnRunKsu;\n'''
        before += '''        btnRunKsu = findViewById(R.id.btnRunKsu);\n'''
        before += '''        btnRunKsu.setOnClickListener(v -> launch(true));\n'''
        java = self.tv.main_activity(before)
        self.assertIn('btnSettings.setOnClickListener', java)
        self.assertIn('startActivity(new Intent(this, SettingsActivity.class))', java)
        layout = self.tv.layout('<LinearLayout>\n    <ScrollView\n        android:id="@+id/outputScroll"\n    </ScrollView>\n</LinearLayout>')
        self.assertIn('android:id="@+id/btnSettings"', layout)
        self.assertIn('android:focusable="true"', layout)
        self.assertIn('android:text="Settings"', layout)
        self.assertLess(layout.index('btnSettings'), layout.index('outputScroll'))
        build = (ROOT / 'tools/build-legacy-manager-ksu.sh').read_text()
        self.assertLess(build.index('apply_foreground_service.py'), build.index('apply_tv_settings.py'))

    def test_source_version_manifest_must_track_compiled_module(self):
        stage = (ROOT / 'patches/dfroot/legacy-ksu/apply_stage.py').read_text()
        verify = (ROOT / 'tools/verify-c3u-autobuilt-apk.py').read_text()
        self.assertIn("'source-version.json'", stage)
        self.assertIn('version_code', stage)
        self.assertIn("tag.encode('ascii') not in blob", stage)
        self.assertIn('source.get(\'source_revision\')', verify)
        self.assertIn('native.count(content) != 1', verify)
        self.assertIn('candidate_only_undefined_symbols', stage)


if __name__ == '__main__':
    unittest.main()
