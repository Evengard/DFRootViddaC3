import json, subprocess, sys, tempfile
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
class PatchsetTests(unittest.TestCase):
    def test_manifest(self):
        config = json.loads((ROOT/'patches/dfroot/patchset/series.json').read_text())
        self.assertEqual(config['upstream']['ref'], 'v3.1')
        self.assertEqual(config['service_owned_exploit_status'], 'NOT_IMPLEMENTED')
        self.assertEqual(len(config['stages']), 4)
        for entry in config['stages']:
            self.assertTrue((ROOT/entry['entrypoint']).is_file())
    def test_inspector_samples(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)/'DFRoot'
            java=base/'app/src/main/java/df/root'
            jni=base/'app/src/main/jni'
            java.mkdir(parents=True);jni.mkdir(parents=True)
            (java/'MainActivity.java').write_text('''package df.root; class MainActivity { IpSecManager ipsec; void runRoot() {} }''')
            (jni/'exp.c').write_text('void Java_df_root_exploit() {}')
            (base/'app/src/main/AndroidManifest.xml').write_text('<manifest/>')
            out=Path(td)/'report'
            subprocess.run([sys.executable,str(ROOT/'tools/inspect_dfroot_root_flow.py'),str(base),str(out)],check=True,capture_output=True)
            result=json.loads((out/'report.json').read_text())
            self.assertTrue(any(x['source'].endswith('MainActivity.java') for x in result['matches']))
            self.assertTrue((out/'source/app/src/main/java/df/root/MainActivity.java').exists())
if __name__ == '__main__': unittest.main()
