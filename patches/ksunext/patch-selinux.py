#!/usr/bin/env python3
"""Fail-closed, idempotent source patch for the C3U's permissive SELinux mode.

This changes ONLY KernelSU Next's late-load automatic enforcing transition.
It does not modify the target device or disable SELinux itself.
"""

import argparse
from pathlib import Path
import re
import sys

MARKER = "C3U: preserving permissive SELinux"
BEFORE = re.compile(
    r'(?P<indent>^[ \t]*)if\s*\(\s*!\s*getenforce\s*\(\s*\)\s*\)\s*\{\s*'
    r'pr_info\s*\(\s*"Permissive SELinux, enforcing\\n"\s*\)\s*;\s*'
    r'setenforce\s*\(\s*true\s*\)\s*;\s*\}',
    re.MULTILINE,
)


def patch_file(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if MARKER in text:
        if BEFORE.search(text):
            raise RuntimeError("Both original enforcing block and v6 marker are present")
        if text.count(MARKER) != 1:
            raise RuntimeError("Expected exactly one v6 marker")
        if 'setenforce(true);' in text:
            raise RuntimeError("Source still contains setenforce(true); manual review needed")
        return "ALREADY_PATCHED"

    matches = list(BEFORE.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one upstream late-load enforcement block; found {len(matches)}. "
            "Use the same KernelSU Next revision as v5, or review init.c manually."
        )

    m = matches[0]
    indent = m.group("indent")
    after = (
        f'{indent}if (!getenforce()) {{\n'
        f'{indent}    /* C3U vendor firmware boots permissive; preserve that baseline. */\n'
        f'{indent}    pr_info("{MARKER}\\n");\n'
        f'{indent}}}'
    )
    text = text[:m.start()] + after + text[m.end():]
    # Update a nearby comment when present. No other runtime behavior changes.
    comment = re.compile(
        r'(?m)^([ \t]*)// Grant current process \(ksud late-load\) root\n'
        r'[ \t]*// with KSU SELinux domain before enforcing SELinux, so it\n'
        r'[ \t]*// can continue to access /data/app etc\. after enforcement\.'
    )
    text = comment.sub(
        lambda m: (
            f'{m.group(1)}// Grant current process (ksud late-load) root with\n'
            f'{m.group(1)}// KSU domain; preserve the C3U vendor SELinux state.'
        ),
        text,
    )
    if MARKER not in text or 'setenforce(true);' in text:
        raise RuntimeError("Unexpected source state after applying patch")
    source.write_text(text, encoding="utf-8")
    return "PATCHED"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, help="KernelSU-Next source checkout")
    args = parser.parse_args()
    target = args.repo.resolve() / "kernel" / "core" / "init.c"
    if not target.is_file():
        parser.error(f"Source file missing: {target}")
    try:
        status = patch_file(target)
    except (OSError, RuntimeError) as exc:
        print(f"C3U v6 source patch failed: {exc}", file=sys.stderr)
        return 1
    print(f"{status}: {target}")
    print("Change: keep the existing SELinux enforcement state during late-load")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
