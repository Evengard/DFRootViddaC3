#!/usr/bin/env python3
"""Inspect a pinned DFRoot checkout without modifying its sources.

This is a source acquisition/analysis step, NOT a service refactor.
Do not assume matching words identify a safe root entrypoint.
"""
import argparse
import json
from pathlib import Path
import re
import shutil

PATTERNS = {
    "ipsec": re.compile(r"\bIpSec(?:Manager|Transform)\b|UdpEncapsulationSocket|SecurityParameterIndex"),
    "native": re.compile(r"\bnative\b|System\.loadLibrary|JNIEXPORT|Java_df_root_"),
    "exploit": re.compile(r"(?i)\b(root|exploit|launchRoot|startRoot|runRoot|bootstrap)\b"),
    "threads": re.compile(r"\bnew\s+Thread\b|\bExecutor\b|\bCompletableFuture\b|\.execute\s*\("),
    "ui_callback": re.compile(r"setOnClickListener|onClick\s*\("),
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dfroot", type=Path)
    ap.add_argument("out", type=Path)
    args = ap.parse_args()
    base = args.dfroot.resolve()
    out = args.out.resolve()
    java = base / "app/src/main/java"
    jni = base / "app/src/main/jni"
    manifest = base / "app/src/main/AndroidManifest.xml"
    if not java.is_dir() or not jni.is_dir() or not manifest.exists():
        ap.error("Not a supported DFRoot source checkout (Java/JNI/manifest missing)")
    out.mkdir(parents=True, exist_ok=True)
    report = []
    for tree, extensions in ((java, {".java"}), (jni,{".c", ".h", ".cpp"})):
        for source in tree.rglob("*"):
            if source.suffix not in extensions or not source.is_file():
                continue
            content = source.read_text(encoding="utf8", errors="replace")
            hits = []
            for kind, rx in PATTERNS.items():
                lines = [i for i, ln in enumerate(content.splitlines(), 1) if rx.search(ln)]
                if lines:
                    hits.append({"type":kind, "lines":lines[:150], "count":len(lines)})
            if hits:
                rel = source.relative_to(base)
                report.append({"source":str(rel),"hits":hits})
                target = out / "source" / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    shutil.copy2(manifest, out / "AndroidManifest.xml")
    report.sort(key=lambda d:d['source'])
    summary = {
        "source_root":"diabl0w/DFRoot v3.1 (checkout ref; see runner log for commit)",
        "purpose":"Locate UI, IPsec and JNI dependencies before moving exploit into service",
        "matches":report,
    }
    (out / "report.json").write_text(json.dumps(summary,indent=2)+"\n")
    lines = ["# DFRoot v3.1 source exploration", "", "This report does not identify a confirmed safe service entrypoint.", "Review selected Java and JNI files in source/ before refactoring.", ""]
    for item in report:
        lines.append("## " + item["source"])
        lines.append(", ".join(x['type']+" ("+str(x['count'])+" matches)" for x in item['hits']))
        lines.append("")
    (out / "report.md").write_text("\n".join(lines))
    if not report:
        raise SystemExit("No source references found; upstream source likely changed")
    print(f"Inspected {len(report)} relevant files; copied source and report to {out}")

if __name__ == '__main__': main()
