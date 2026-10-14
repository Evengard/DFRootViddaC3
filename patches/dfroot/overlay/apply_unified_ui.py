#!/usr/bin/env python3
"""Unify DFRoot v3.1 UI+ADB root entrypoints behind the FGS (stage 06).

Applies after apply_adb_intent.py and apply_service_worker.py.
Checks the reviewed v3.1 upstream API and exact MainActivity root-button
handler before mutation. Does NOT patch native exploit or kernel module.
"""
from __future__ import annotations
import argparse
import hashlib
import re
from pathlib import Path
import xml.etree.ElementTree as ET

EXPECTED_RUNNER_SHA256 = 'f34c93dddca5eeaf1eb01c44db2cdd031640f57e9ea07781d66b1a5f361992ae'
NS = '{http://schemas.android.com/apk/res/android}'
MARKER = '// C3U_UNIFIED_ROOT_UI: button and ADB invoke the same service-owned worker'
ROOT_BUTTON = '''        binding.btnRun.setOnClickListener(v -> {
            binding.btnRun.setEnabled(false);
            binding.outputView.setText("");
            mExec.execute(this::runExploit);
        });'''
ROOT_BUTTON_NEW = '''        // C3U_UNIFIED_ROOT_UI: button and ADB invoke the same service-owned worker
        binding.btnRun.setOnClickListener(v -> {
            binding.btnRun.setEnabled(false);
            try {
                Intent service = new Intent(this, C3URootForegroundService.class);
                service.setAction(C3URootForegroundService.ACTION_START_UI);
                if (android.os.Build.VERSION.SDK_INT >= 26) startForegroundService(service);
                else startService(service);
            } catch (RuntimeException e) {
                report("Cannot start C3U foreground root service: " + e + "\\n");
                binding.btnRun.setEnabled(true);
            }
        });'''
REPORT_METHOD = '''    @Override
    public void report(String msg) {
        Log.i(TAG, msg.trim());
        mMain.post(() -> {
            binding.outputView.append(msg);
            binding.outputScroll.post(() -> binding.outputScroll.fullScroll(View.FOCUS_DOWN));
        });
    }
'''
REPORT_NEW = '''    @Override
    public void report(String msg) {
        if (msg == null) return;
        Log.i(TAG, msg.trim());
        C3URootLog.append(this, msg);
        // The on-screen log reader sees this and service messages alike.
    }
'''
LOGGER_FIELDS = '''    private String mLastRenderedLog = null;
    private final Runnable mRefreshLog = new Runnable() {
        @Override public void run() {
            if (binding != null) {
                String text = C3URootLog.read(MainActivity.this);
                if (!text.equals(mLastRenderedLog)) {
                    mLastRenderedLog = text;
                    binding.outputView.setText(text);
                    binding.outputScroll.post(() ->
                            binding.outputScroll.fullScroll(View.FOCUS_DOWN));
                }
                binding.btnRun.setEnabled(!C3URootForegroundService.isRunning()
                        && !new File("/dev/df").exists());
            }
            mMain.postDelayed(this, 600L);
        }
    };

    @Override protected void onStart() {
        super.onStart();
        mMain.removeCallbacks(mRefreshLog);
        mMain.post(mRefreshLog);
    }

    @Override protected void onStop() {
        mMain.removeCallbacks(mRefreshLog);
        super.onStop();
    }

'''


def method_end(text: str, brace: int) -> int:
    depth = 0
    state = 'code'
    i = brace
    while i < len(text):
        c = text[i]
        n = text[i + 1] if i + 1 < len(text) else ''
        if state == 'code':
            if c == '"': state = 'string'
            elif c == "'": state = 'char'
            elif c == '/' and n == '/': state = 'line'; i += 1
            elif c == '/' and n == '*': state = 'block'; i += 1
            elif c == '{': depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0: return i
        elif state in ('string', 'char'):
            if c == '\\': i += 1
            elif c == ('"' if state == 'string' else "'"): state = 'code'
        elif state == 'line':
            if c == '\n': state = 'code'
        elif state == 'block':
            if c == '*' and n == '/': state = 'code'; i += 1
        i += 1
    raise ValueError('Unbalanced runExploit() block')


def patch(repo: Path, sources: Path) -> None:
    java = repo/'app/src/main/java/df/root'
    main_path = java/'MainActivity.java'
    runner = java/'ExploitRunner.java'
    service = java/'C3URootForegroundService.java'
    act = java/'C3UAdbRootActivity.java'
    manifest = repo/'app/src/main/AndroidManifest.xml'
    for path in (main_path, runner, service, act, manifest):
        if not path.is_file(): raise ValueError('Stage 06 prerequisite missing: ' + str(path))
    if hashlib.sha256(runner.read_bytes()).hexdigest() != EXPECTED_RUNNER_SHA256:
        raise ValueError('ExploitRunner differs from reviewed DFRoot v3.1; refusing UI refactor')
    root = ET.parse(manifest).getroot()
    app = root.find('application')
    if app is None: raise ValueError('No manifest application')
    svcs = [n for n in app.findall('service')
            if n.get(NS+'name') == 'df.root.C3URootForegroundService']
    if len(svcs) != 1 or svcs[0].get(NS+'exported') != 'false' or svcs[0].get(NS+'foregroundServiceType') != 'specialUse':
        raise ValueError('Expected a single non-exported, specialUse foreground service')
    activities = [n for n in app.findall('activity')
                  if n.get(NS+'name') == 'df.root.C3UAdbRootActivity']
    if len(activities) != 1 or activities[0].get(NS+'permission') != 'android.permission.DUMP':
        raise ValueError('ADB launcher must require android.permission.DUMP')
    s = main_path.read_text()
    if MARKER not in s:
        if s.count(ROOT_BUTTON) != 1 or s.count(REPORT_METHOD) != 1:
            raise ValueError('Upstream DFRoot MainActivity root-click or reporter differs from v3.1')
        exec_decl = '    private final Executor mExec = Executors.newSingleThreadExecutor();\n'
        if s.count(exec_decl) != 1: raise ValueError('Unexpected MainActivity executor declaration')
        start = re.search(r'\n    private void runExploit\(\)\s*\{', s)
        if not start: raise ValueError('MainActivity.runExploit() not found')
        end = method_end(s, s.index('{', start.start()))
        if s.count('mExec.execute(this::runExploit)') != 1:
            raise ValueError('Unexpected direct exploit invocation')
        s = s[:start.start()] + s[end+1:]
        s = s.replace('import java.util.concurrent.Executor;\n', '')
        s = s.replace('import java.util.concurrent.Executors;\n', '')
        s = s.replace(exec_decl, '')
        s = s.replace(REPORT_METHOD, REPORT_NEW, 1)
        s = s.replace(ROOT_BUTTON, ROOT_BUTTON_NEW, 1)
        anchor = '    @Override\n    protected void onCreate(Bundle savedInstanceState) {'
        if s.count(anchor) != 1: raise ValueError('MainActivity lifecycle entrypoint changed')
        s = s.replace(anchor, LOGGER_FIELDS + anchor, 1)
    else:
        # Idempotence must not disguise partial or contradictory edits.
        if ROOT_BUTTON in s or 'private void runExploit()' in s:
            raise ValueError('Unified-UI marker exists but legacy executor path remains')
        if 'C3URootForegroundService.ACTION_START_UI' not in s or 'C3URootLog.read(' not in s:
            raise ValueError('Unified-UI marker exists but required UI code is missing')
    # Fail closed on unsupported bundled Java, before mutating source files.
    for name, required in {
        'C3URootForegroundService.java': ('ACTION_START_UI', 'ACTION_START_ADB', 'ExploitRunner.run(', 'C3URootLog.append(', 'stopSelf();'),
        'C3UAdbRootActivity.java': ('ACTION_START_ADB', 'startForegroundService(service)'),
        'C3URootLog.java': ('C3URootLog', 'static void begin(', 'static void append(', 'static String read('),
    }.items():
        path = sources/name
        if not path.is_file() or any(fragment not in path.read_text() for fragment in required):
            raise ValueError('Missing/unexpected stage 06 bundled source: ' + str(path))
    if 'ExploitRunner.run(' in s or 'mExec.execute(' in s:
        raise ValueError('MainActivity still owns native exploit')
    main_path.write_text(s)
    for name in ('C3URootForegroundService.java','C3UAdbRootActivity.java','C3URootLog.java'):
        (java/name).write_bytes((sources/name).read_bytes())


def main() -> None:
    arg = argparse.ArgumentParser(description=__doc__)
    arg.add_argument('dfroot', type=Path)
    args = arg.parse_args()
    try:
        patch(args.dfroot.resolve(), Path(__file__).resolve().parent.parent/'unified_ui')
    except (ValueError, OSError, ET.ParseError) as exc:
        arg.exit(1, f'C3U unified UI + service patch refused: {exc}\n')
    print('PASS: UI button and ADB launcher now invoke one service-owned exploit worker')
    print('PASS: app-private bounded log is readable live and after reopening DFRoot')


if __name__ == '__main__': main()
