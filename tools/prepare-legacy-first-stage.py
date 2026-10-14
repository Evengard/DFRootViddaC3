#!/usr/bin/env python3
"""Prepare the archived DFRoot first-stage revision for a diagnostic build.

No KernelSU injection is added. This deliberately keeps the original
Activity-based exploit path and the archived independent temporary-root server.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

LEGACY_DFROOT_REV = "6de62220809a678fddbd3819e4fcb3bb68aa1eae"
LEGACY_RUNNER_SHA256 = "088c4052876287067b74bec016f7aa34b5dc8dad2f44523692e5226fce686a8d"
LEGACY_HELPER_SHA256 = "5135155128a90947e6ec341c36ce4b7169bdfe68f363341c9d0ed9568c60e473"
HELPER_NAME = "dfroot-android14-5.15.ko"
# Source hashes taken from the actual archived checkout whose APK was verified
# on the projector. C3U overlay normally differs only in two comments.
LEGACY_JNI_SHA256 = {
    "bootstrap.c": "604b3296297530219d6e8337e1b3bee68a9a0ae7686012add4dc8beb39af5f53",
    "exp.c": "69e7a62fe98cdad5c21065d5605cbbe12ed8ad74d65553506e1e745e128220c6",
    "CMakeLists.txt": "3f07197f393089dc4c16cfd73dc628788e54971e11042221df5a3883acccad90",
    "rootshell.c": "0b6f6fe2c89c0acd4411c8081c6c14ac486ea36157f2d638620ed29d988f255e",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(repo: Path, overlay: Path, helper: Path) -> Path:
    if not (repo / ".git").exists():
        raise ValueError("Expected a Git checkout of DFRoot")
    revision = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != LEGACY_DFROOT_REV:
        raise ValueError(f"Wrong DFRoot commit: {revision}; expected {LEGACY_DFROOT_REV}")
    runner = repo / "app/src/main/java/df/root/ExploitRunner.java"
    if not runner.is_file() or sha256(runner) != LEGACY_RUNNER_SHA256:
        raise ValueError("Archived ExploitRunner source differs; refusing to patch")
    if not helper.is_file() or sha256(helper) != LEGACY_HELPER_SHA256:
        raise ValueError("DFRoot first-stage kernel helper is NOT the tested archived binary")
    if not (overlay / "apply_overlay.py").is_file() or not (overlay / "rootshell.c").is_file():
        raise ValueError("Existing C3U single-KMI/temporary-root overlay is missing")
    subprocess.run(
        [sys.executable, str(overlay / "apply_overlay.py"), str(repo)], check=True
    )
    jni = repo / "app/src/main/jni"
    # Reproduce the two source comments found in the archived, tested APK's
    # build tree. Fail closed if the overlay has changed its expected shape.
    comment_replacements = {
        "bootstrap.c": (
            "/* Experimental local-ADB root service; separate from KernelSU. */",
            "/* Independent temporary root shell even if ksud late-load fails. */",
        ),
        "CMakeLists.txt": (
            "# Experimental temporary root service and its command-line client.",
            "# Restricted temporary root server inside DFRoot bootstrap, and su -c client.",
        ),
    }
    for name, (old, new) in comment_replacements.items():
        path = jni / name
        body = path.read_text()
        if body.count(old) != 1:
            raise ValueError(f"Unexpected {name} overlay: archived comment cannot be restored")
        path.write_text(body.replace(old, new, 1))
    for name, expected in LEGACY_JNI_SHA256.items():
        actual = sha256(jni / name)
        if actual != expected:
            raise ValueError(f"{name} differs from original archived working source: {actual}")
    bootstrap = (jni / "bootstrap.c").read_text()
    exploit = (jni / "exp.c").read_text()
    cmake = (jni / "CMakeLists.txt").read_text()
    if not (
        'touch("/dev/dfsu0")' in bootstrap
        and "dfroot_start_root_service()" in bootstrap
        and "C3U_ONLY_KMI_ANDROID14_5_15" in exploit
        and "dfroot-android14-5.15.ko" in cmake
    ):
        raise ValueError("Temporary-root / one-KMI overlay was not correctly applied")
    if "c3u_ksu_preload" in bootstrap or "c3u_ksu_preload.c" in cmake:
        raise ValueError("Integrated KernelSU injection is forbidden in diagnostic build")
    target = jni / "ko" / HELPER_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(helper, target)
    if sha256(target) != LEGACY_HELPER_SHA256:
        raise ValueError("Staged DFRoot helper differs from the archived working binary")
    print(f"PASS: DFRoot source pinned to {revision}")
    print(f"PASS: legacy DFRoot helper SHA256 {LEGACY_HELPER_SHA256}")
    print("PASS: JNI/CMake source hashes exactly match archived working checkout")
    print("PASS: separate temporary root shell present; NO KernelSU injection")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dfroot_checkout", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.repo_root.resolve()
    try:
        prepare(
            args.dfroot_checkout.resolve(),
            root / "patches/dfroot/legacy-overlay",
            root / "known-good/dfroot-helper-6de6222.ko",
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as err:
        parser.exit(1, f"Legacy DFRoot preparation FAILED: {err}\n")


if __name__ == "__main__":
    main()
