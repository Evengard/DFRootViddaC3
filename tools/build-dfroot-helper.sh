#!/usr/bin/env bash
# Recompile only DFRoot android14-5.15 helper using original working DDK toolchain.
# Refuse to publish a different binary: prior DFRoot helper CFI mismatches panicked the projector.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
[[ $# -eq 1 ]] || { echo "Usage: $0 /path/to/pinned/DFRoot" >&2; exit 2; }
WORK="$(cd "$1" && pwd -P)"
INFO="$ROOT/config/dfroot-helper-baseline.json"
for cmd in docker python3 sha256sum git; do
  command -v "$cmd" >/dev/null || { echo "Missing tool: $cmd" >&2; exit 2; }
done
python3 - "$WORK" "$INFO" <<'PYTHON'
import hashlib,json,subprocess,sys
from pathlib import Path
repo=Path(sys.argv[1]); data=json.loads(Path(sys.argv[2]).read_text())
revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
if revision!=data['dfroot_commit']:
    raise SystemExit('Refusing to compile DFRoot helper from a different commit: '+revision)
for fn, field in [('lkm/dfroot.c','source_sha256'),('lkm/Makefile','makefile_sha256')]:
    sha=hashlib.sha256((repo/fn).read_bytes()).hexdigest()
    if sha != data[field]: raise SystemExit(f'DFRoot helper source changed: {fn} {sha}')
if data['module_kmi']!='android14-5.15' or data['ddk_image_tag']!='ghcr.io/ylarod/ddk-min:android14-5.15-20260828':
    raise SystemExit('Unrecognized or changed DFRoot DDK image/KMI')
print('PASS: exact pinned DFRoot helper source and Makefile verified')
PYTHON
TARGET="$WORK/app/src/main/jni/ko/dfroot-android14-5.15.ko"
# A fresh pinned checkout is used on every run; ensure the result comes from THIS build.
rm -f -- "$TARGET"
# This sequence matches the previously uploaded, successful build-in-docker.sh.
docker run --rm --platform linux/amd64 --pid=host --network=none \
  --mount "type=bind,src=${WORK},dst=/proj" \
  --env KMI=android14-5.15 \
  ghcr.io/ylarod/ddk-min:android14-5.15-20260828 \
  bash -euc '
    cd /proj/lkm
    make -j"$(nproc)"
    llvm-objcopy --strip-unneeded \
      -R .comment -R .note.gnu.build-id -R .note.gnu.property \
      -R .note.Linux -R .note.GNU-stack \
      -R .BTF -R .BTF.base -R .llvm_addrsig \
      -R .hyp.text -R .hyp.bss -R .hyp.rodata -R .hyp.event_ids \
      -R .hyp.patchable_function_entries -R .hyp.data dfroot.ko
    mkdir -p /proj/app/src/main/jni/ko
    cp dfroot.ko /proj/app/src/main/jni/ko/dfroot-${KMI}.ko
    make clean
  '
[[ -s "$TARGET" ]] || { echo 'No newly built DFRoot helper produced' >&2; exit 1; }
python3 - "$TARGET" "$INFO" <<'PYTHON'
import hashlib,json,sys
from pathlib import Path
binary=Path(sys.argv[1]); info=json.loads(Path(sys.argv[2]).read_text())
payload=binary.read_bytes(); digest=hashlib.sha256(payload).hexdigest()
if digest != info['device_tested_module_sha256'] or len(payload)!=info['device_tested_module_bytes']:
    raise SystemExit(f'FAIL: DFRoot helper output differs from DEVICE-TESTED binary. '
                     f'actual={digest}, bytes={len(payload)}, '
                     f'expected={info["device_tested_module_sha256"]}, bytes={info["device_tested_module_bytes"]}. '
                     'Do NOT deploy this helper; investigate DDK/toolchain drift.')
print(f'PASS: just-compiled DFRoot helper is byte-for-byte identical to device-tested binary: {digest}')
PYTHON
