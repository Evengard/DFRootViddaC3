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
MANAGER_KSUD = "/data/user_de/0/df.root/ksud"
LATE_LOAD_MARKER = "C3U_MANAGER_KSUD_LATE_LOAD"

# Pinned upstream DFRoot v3.1 bootstrap.c late-load block. Abort instead of
# guessing if upstream DFRoot changes its argument construction.
ORIGINAL_LATE_LOAD = '''    char **late_load;
    if (soft_reboot)
        late_load = (char *[]){ KSUD, "late-load", "--package-name", su_manager, "--soft-reboot", NULL };
    else
        late_load = (char *[]){ KSUD, "late-load", "--package-name", su_manager, NULL };'''
C3U_LATE_LOAD = '''    /* C3U_MANAGER_KSUD_LATE_LOAD: KernelSU Next v3.4.1 late-load has no
     * soft-reboot flag. Preserve its normal module-init/mounting path. */
    (void)soft_reboot; /* DFRoot's optional preference is ignored on C3U. */
    char *late_load[] = { KSUD, "late-load", "--package-name", su_manager, NULL };'''


def normalize_manager_ksud_late_load(bootstrap: str) -> str:
    expected_define = f'#define KSUD       "{MANAGER_KSUD}"'
    if bootstrap.count(expected_define) != 1:
        raise ValueError("DFRoot KSUD path changed; cannot guarantee Manager-staged ksud is used")
    if LATE_LOAD_MARKER in bootstrap:
        if bootstrap.count(C3U_LATE_LOAD) != 1 or ORIGINAL_LATE_LOAD in bootstrap:
            raise ValueError("Inconsistent C3U Manager ksud late-load patch")
        return bootstrap
    if bootstrap.count(ORIGINAL_LATE_LOAD) != 1:
        raise ValueError("DFRoot v3.1 late-load command changed; refusing unsafe rewrite")
    return bootstrap.replace(ORIGINAL_LATE_LOAD, C3U_LATE_LOAD, 1)

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
    bootstrap = normalize_manager_ksud_late_load(bootstrap)
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
        # Run immediately after the independent root service, before ANY
        # existing DFRoot ksud launch. Both paths use the Manager-staged
        # device-protected ksud rather than a preinstalled /data/adb/ksud.
        # Do not anchor to /dev/dfm5: its position relative to executing
        # late-load is not a safe invariant across DFRoot versions.
        anchor = '    else touch("/dev/dfsue0");'
        if bootstrap.count(anchor) != 1:
            raise ValueError("Cannot locate expected root service anchor")
        injection = '''
    /* C3U_V7_KSU_PRELOAD: load the EXACT v6 KO before ANY stock late-load.
     * Requires the ksud staged from the selected installed SU Manager.
     * Failure MUST NOT fall through to an incompatible stock module. */
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
        "ksud_source": "installed selected SU Manager lib/arm64-v8a/libksud.so",
        "ksud_staged_path": MANAGER_KSUD,
        "preload_cmd": "Manager-staged ksud insmod <staged exact v6 .ko>",
        "continuation": "same Manager-staged ksud late-load, without unsupported soft reboot option",
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
