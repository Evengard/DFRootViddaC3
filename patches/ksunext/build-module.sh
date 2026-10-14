#!/usr/bin/env bash
# v6: create clean KernelSU Next clone, patch SELinux late-load, build one LKM.
# Does NOT install/insmod/late-load, and NEVER modifies the source checkout.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /path/to/KernelSU-Next [output-directory]" >&2
  exit 2
fi
for exe in docker git python3; do
  command -v "$exe" >/dev/null || { echo "$exe is required" >&2; exit 2; }
done
ORIGINAL="$(cd "$1" && pwd -P)"
[[ -f "$ORIGINAL/kernel/core/init.c" ]] || {
  echo "Not a KernelSU Next source checkout: $ORIGINAL" >&2; exit 2;
}
if ! git -C "$ORIGINAL" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "KernelSU Next must be a Git checkout; a clean local clone is required." >&2
  exit 2
fi
REV="$(git -C "$ORIGINAL" rev-parse HEAD)"
OUT="${2:-$PWD/ksunext-c3u-v6-out}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd -P)"
SELF="$(cd "$(dirname "$0")" && pwd -P)"

# The original tree may contain .o/.ko files and local changes from previous
# experiments. Cloning at the exact commit prevents those from leaking in.
# A normal local clone (not a git worktree) keeps .git paths valid in Docker.
# Put temporary build sources alongside the requested output: on Docker Desktop
# for macOS this guarantees the bind mount uses the same shared host directory.
STAGE="$(mktemp -d "$OUT/.c3u-ksunext-v6-stage.XXXXXXXX")"
cleanup() {
  if [[ "${C3U_KEEP_STAGE:-0}" == "1" ]]; then
    echo "C3U_KEEP_STAGE=1: preserved temporary build checkout at $STAGE" >&2
  else
    rm -rf -- "$STAGE"
  fi
}
trap cleanup EXIT

STAGED_REPO="$STAGE/KernelSU-Next"
printf 'Input checkout: %s\nPinned commit: %s\nOutput directory: %s\n' "$ORIGINAL" "$REV" "$OUT"
git clone --quiet --no-local "$ORIGINAL" "$STAGED_REPO"
git -C "$STAGED_REPO" checkout --quiet --detach "$REV"

python3 "$SELF/patch-selinux.py" "$STAGED_REPO" | tee "$OUT/v6-source-patch-report.txt"
git -C "$STAGED_REPO" diff -- kernel/core/init.c > "$OUT/v6-selinux-source.diff"
if [[ ! -s "$OUT/v6-selinux-source.diff" ]]; then
  echo "No v6 source diff found; refusing to compile." >&2
  exit 1
fi
printf 'Source commit: %s\n' "$REV" > "$OUT/source-revision.txt"
printf 'Source description: %s\n' "$(git -C "$STAGED_REPO" describe --tags --always 2>/dev/null || true)" >> "$OUT/source-revision.txt"

# Remove only the v6 product from a previous attempt, preventing stale output
# from being mistaken for a successful new build.
rm -f -- "$OUT/aarch64_android14-5.15_kernelsu-c3u-permissive-v6-UNVERIFIED-DO-NOT-LOAD.ko"
"$SELF/build-kmod-in-docker.sh" "$STAGED_REPO" "$OUT"

# A final host-side consistency check: confirm that the fresh artifact exists.
KO="$OUT/aarch64_android14-5.15_kernelsu-c3u-permissive-v6-UNVERIFIED-DO-NOT-LOAD.ko"
[[ -s "$KO" ]] || { echo "Expected v6 .ko missing after Docker build" >&2; exit 1; }
python3 - "$KO" "$OUT/module-sha256.txt" <<'PY'
import hashlib, pathlib, sys
path = pathlib.Path(sys.argv[1]); target = pathlib.Path(sys.argv[2])
target.write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n")
print(f"Output (UNVERIFIED, DO NOT LOAD): {path}")
print(f"SHA-256: {target.read_text().split()[0]}")
PY

echo "v6 offline build complete. No files were changed on the projector."
echo "Not proof of runtime compatibility; do not load automatically or at boot."
