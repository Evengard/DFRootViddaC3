#!/usr/bin/env python3
"""DFRoot experimental root shell + C3U-only android14-5.15 module packaging.

Usage: python3 overlay/apply_overlay.py /path/to/DFRoot

Targets upstream diabl0w/DFRoot master as of 2026-10-12. Deliberately fail
rather than silently mangling a changed upstream file layout.
"""
from pathlib import Path
import re
import shutil
import sys

ONLY_KMI = "android14-5.15"
TAG = "C3U_ONLY_KMI_ANDROID14_5_15"

if len(sys.argv) != 2:
    raise SystemExit("Usage: python3 apply_overlay.py /path/to/DFRoot")
root = Path(sys.argv[1]).resolve()
jni = root / "app/src/main/jni"
bootstrap = jni / "bootstrap.c"
cmake = jni / "CMakeLists.txt"
exploit = jni / "exp.c"
if not (bootstrap.is_file() and cmake.is_file() and exploit.is_file()):
    raise SystemExit("Not a DFRoot checkout (expected bootstrap.c, exp.c, CMakeLists.txt)")

b = bootstrap.read_text()
c = cmake.read_text()
e = exploit.read_text()

# Validate *all* patches before writing any files, avoiding a half-patched tree.
if "dfroot_start_root_service" not in b:
    if "int main(void)" not in b or b.count('touch("/dev/dfm1");') != 1:
        raise SystemExit("Unsupported bootstrap.c structure; cannot apply root-shell hook")
    b = b.replace("int main(void)", "int dfroot_start_root_service(void);\n\nint main(void)", 1)
    b = b.replace(
        'touch("/dev/dfm1");',
        'touch("/dev/dfm1");\n'
        '    /* Experimental local-ADB root service; separate from KernelSU. */\n'
        '    if (dfroot_start_root_service() == 0) touch("/dev/dfsu0");\n'
        '    else touch("/dev/dfsue0");',
        1,
    )

if "DFROOT_SU_CLIENT" not in c:
    if "add_executable(bootstrap bootstrap.c)" not in c:
        raise SystemExit("Unsupported CMakeLists.txt: bootstrap target missing")
    c += '''
# Experimental temporary root service and its command-line client.
target_sources(bootstrap PRIVATE rootshell.c)
add_executable(dfrootsu rootshell.c)
target_compile_definitions(dfrootsu PRIVATE DFROOT_SU_CLIENT)
set_target_properties(dfrootsu PROPERTIES
    PREFIX "lib"
    SUFFIX ".so"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}")
target_link_options(dfrootsu PRIVATE -Wl,-z,max-page-size=16384)
'''

# Upstream embeds 8 binaries via inline assembly. Keep only the actual C3U
# target and keep only one KoImage entry; don't fabricate empty .ko files.
if TAG not in e:
    section = "/* ---- KO and splicehelper blobs ---- */"
    begin = e.find('asm(\n    ".section .rodata\\n"', e.find(section))
    end = e.find("static int read_device_versions(", begin)
    if section not in e or begin == -1 or end == -1 or begin >= end:
        raise SystemExit("Unsupported exp.c module-embedding structure; aborting")
    original = e[begin:end]
    expected = [
        "android12-5.10", "android13-5.10", "android13-5.15", "android14-5.15",
        "android14-6.1", "android15-6.6", "android16-6.12", "android17-6.18",
    ]
    if not all(f'ko/dfroot-{k}.ko' in original for k in expected):
        raise SystemExit("Upstream exp.c KMI list changed; aborting")
    if 'splice_helper_start' not in original or 'select_ko_image' not in original:
        raise SystemExit("Upstream exp.c payload layout changed; aborting")
    single = r'''/* C3U_ONLY_KMI_ANDROID14_5_15: intentionally embed just one KO. */
asm(
    ".section .rodata\n"
    ".global dfroot_ko_14_5_15_start\n.global dfroot_ko_14_5_15_end\n"
    "dfroot_ko_14_5_15_start:\n.incbin \"ko/dfroot-android14-5.15.ko\"\ndfroot_ko_14_5_15_end:\n"
);
asm(
    ".section .rodata\n"
    ".global splice_helper_start\n.global splice_helper_end\n"
    "splice_helper_start:\n.incbin \"splicehelper\"\nsplice_helper_end:\n"
);
extern char dfroot_ko_14_5_15_start[], dfroot_ko_14_5_15_end[];
extern char splice_helper_start[], splice_helper_end[];
struct KoImage { int android_release, kver_major, kver_minor; const char *start, *end; };
static const struct KoImage *select_ko_image(int andr, int major, int minor) {
    static const struct KoImage image = {
        14, 5, 15, dfroot_ko_14_5_15_start, dfroot_ko_14_5_15_end
    };
    return (andr == 14 && major == 5 && minor == 15) ? &image : NULL;
}
'''
    e = e[:begin] + single + e[end:]

# CMake's OBJECT_DEPENDS must also mention only the single required KO.
ko_block = re.search(r'(?ms)^set\(KO_FILES\n.*?^\)', c)
if not ko_block:
    raise SystemExit("Unsupported CMakeLists.txt: KO_FILES block missing")
original_ko_block = ko_block.group(0)
if ONLY_KMI not in original_ko_block:
    raise SystemExit("CMakeLists.txt does not contain target KMI")
if ('android12-5.10' not in original_ko_block and
        original_ko_block != 'set(KO_FILES\n    "${JNI_DIR}/ko/dfroot-android14-5.15.ko"\n)'):
    raise SystemExit("Unexpected existing KO_FILES; aborting rather than overwriting edits")
c = c[:ko_block.start()] + '''set(KO_FILES
    "${JNI_DIR}/ko/dfroot-android14-5.15.ko"
)''' + c[ko_block.end():]

# Final consistency checks before writing.
if e.count('ko/dfroot-android14-5.15.ko') != 1 or e.count('.incbin \\"ko/dfroot-') != 1:
    raise SystemExit("Internal consistency error: wrong number of embedded modules")
if c.count('dfroot-android14-5.15.ko') != 1:
    raise SystemExit("Internal consistency error: CMake module dependency count")

shutil.copy2(Path(__file__).with_name("rootshell.c"), jni / "rootshell.c")
bootstrap.write_text(b)
cmake.write_text(c)
exploit.write_text(e)
print(f"Overlay applied: only {ONLY_KMI} LKM will be embedded in the APK.")
print("Temporary ADB root shell and original KernelSU loading path both retained.")
