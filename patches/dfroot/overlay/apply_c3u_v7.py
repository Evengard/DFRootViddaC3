#!/usr/bin/env python3
"""Bundle a *previously verified* C3U v6 .ko into DFRoot's bootstrap executable.

Run the legacy single-KMI + root-shell overlay before this patcher.
This script refuses ambiguous/new upstream structures rather than guessing.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys

TAG = "C3U_V7_KSU_PRELOAD"
EMBEDDED_NAME = "c3u-ksunext-v6.ko"


def check_ko(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    if not (64 * 1024 <= len(data) < 64 * 1024 * 1024):
        raise ValueError("KO size is unexpected")
    if data[:5] != b"\x7fELF\x02" or data[5] != 1 or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("Expected ARM64, ELF64, little-endian KernelSU .ko")
    if b"C3U: preserving permissive SELinux" not in data:
        raise ValueError("Not a v6 C3U permissive module (v6 marker absent). Never use the v5 KO")
    if b"vermagic=5.15." not in data:
        raise ValueError("Kernel version metadata missing")
    digest = hashlib.sha256(data).hexdigest()
    return data, digest


def patch(repo: Path, source_ko: Path, source_dir: Path) -> None:
    jni = repo / "app/src/main/jni"
    bootstrap_path = jni / "bootstrap.c"
    cmake_path = jni / "CMakeLists.txt"
    exp_path = jni / "exp.c"
    for p in (bootstrap_path, cmake_path, exp_path):
        if not p.is_file():
            raise ValueError(f"DFRoot checkout incomplete: {p}")

    data, sha256 = check_ko(source_ko)
    bootstrap = bootstrap_path.read_text()
    cmake = cmake_path.read_text()
    exploit = exp_path.read_text()
    if "C3U_ONLY_KMI_ANDROID14_5_15" not in exploit:
        raise ValueError("Run `python3 overlay/apply_overlay.py /path/to/DFRoot` (v3) first")
    if "dfroot_start_root_service" not in bootstrap or "touch(\"/dev/dfsue0\");" not in bootstrap:
        raise ValueError("Expected v3 C3U root service hook is absent. Apply v3 overlay first")
    if "touch(\"/dev/dfm6\");" not in bootstrap or "ksud" not in bootstrap:
        raise ValueError("Cannot verify DFRoot's normal ksud continuation; aborting")

    if TAG not in bootstrap:
        decl = "int c3u_ksu_preload(void); /* C3U_V7_KSU_PRELOAD */\n"
        if bootstrap.count("int main(void)") != 1:
            raise ValueError("Expected exactly one bootstrap main(void)")
        bootstrap = bootstrap.replace("int main(void)", decl + "\nint main(void)", 1)
        # Run immediately after the ADB-only root service, before ANY
        # pre-existing DFRoot ksud launch. This revision relies on the
        # /data/adb/ksud that the user already has persistently installed.
        # Do not anchor to /dev/dfm5: its position relative to executing
        # late-load is not a safe invariant across DFRoot versions.
        anchor = '    else touch("/dev/dfsue0");'
        if bootstrap.count(anchor) != 1:
            raise ValueError("Cannot locate expected root service anchor")
        injection = '''
    /* C3U_V7_KSU_PRELOAD: load the EXACT v6 KO before ANY stock late-load.
     * Requires already installed /data/adb/ksud. Failure MUST NOT fall
     * through to the stock module, which crashes this Hisense kernel. */
    if (c3u_ksu_preload() == 0) {
        touch("/dev/dfkc1");
    } else {
        touch("/dev/dfke1");
        return 97;
    }'''
        bootstrap = bootstrap.replace(anchor, anchor + injection, 1)
    else:
        if (bootstrap.count("c3u_ksu_preload()") != 1 or bootstrap.count('touch("/dev/dfke1")') != 1):
            raise ValueError("v7 bootstrap patch is inconsistent; aborting")
        if bootstrap.index("c3u_ksu_preload()") < bootstrap.index('touch("/dev/dfm1")'):
            raise ValueError("Unexpected preload location; aborting")
        if bootstrap.index("c3u_ksu_preload()") > bootstrap.index('touch("/dev/dfm5")'):
            raise ValueError("Preload occurs after ksud-load marker; aborting")

    if "C3U_V7_KSU_PRELOAD" not in cmake:
        if "target_sources(bootstrap PRIVATE rootshell.c)" not in cmake:
            raise ValueError("Expected v3 CMake root shell target not found")
        cmake += '''
# C3U_V7_KSU_PRELOAD: Embed the exact, proven KernelSU Next v6 KO into bootstrap.
# The dependency forces CMake to relink bootstrap when v6 KO bytes change.
target_sources(bootstrap PRIVATE c3u_ksu_preload.c)
set_source_files_properties(c3u_ksu_preload.c PROPERTIES
    OBJECT_DEPENDS "${JNI_DIR}/ko/c3u-ksunext-v6.ko")
'''
    else:
        if cmake.count("c3u-ksunext-v6.ko") != 1:
            raise ValueError("v7 CMake patch is inconsistent")

    # All source transformations are validated before modifying the checkout.
    if bootstrap.count('touch("/dev/dfkc1")') != 1 or bootstrap.count('touch("/dev/dfke1")') != 1:
        raise ValueError("Invalid insertion: v7 markers not unique")
    if cmake.count("c3u_ksu_preload.c") != 2:
        raise ValueError("CMake source/dependency wiring is unexpected")
    # Abort if our privileged preload could occur after a stock load.
    # We require the original bootstrap first-stage markers to exist.
    if not (bootstrap.index('touch("/dev/dfm1")') <
            bootstrap.index('if (c3u_ksu_preload() == 0)') <
            bootstrap.index('touch("/dev/dfm2")')):
        raise ValueError("Preload is not at the guarded first-stage location")

    (jni / "ko").mkdir(parents=True, exist_ok=True)
    staged = jni / "ko" / EMBEDDED_NAME
    staged.write_bytes(data)
    shutil.copy2(source_dir / "c3u_ksu_preload.c", jni / "c3u_ksu_preload.c")
    bootstrap_path.write_text(bootstrap)
    cmake_path.write_text(cmake)

    manifest = {
        "purpose": "Vidda C3U KernelSU Next v6 embedded in DFRoot",
        "source_ko": str(source_ko),
        "embedded_ko": str(staged),
        "sha256": sha256,
        "bytes": len(data),
        "expected_kernel": "5.15.148-android14-11-g7b7674251b5d-dirty",
        "expected_fingerprint": "Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys",
        "root_service_fallback": "libdfrootsu.so",
        "preload_cmd": "ksud insmod <staged exact v6 .ko>",
        "continuation": "existing DFRoot ksud late-load (skips embedded module when already loaded)",
    }
    (jni / "c3u-v7-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Embedded v6 KernelSU .ko: {len(data):,} bytes")
    print(f"Embedded SHA-256: {sha256}")
    print("DFRoot bootstrap will fail closed if C3U module preload fails.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dfroot", type=Path)
    parser.add_argument("working_v6_ko", type=Path)
    args = parser.parse_args()
    try:
        patch(args.dfroot.resolve(), args.working_v6_ko.resolve(), Path(__file__).resolve().parent)
    except (OSError, ValueError) as e:
        parser.exit(1, f"v7 patch refused: {e}\n")


if __name__ == "__main__":
    main()
