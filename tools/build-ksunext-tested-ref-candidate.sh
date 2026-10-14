#!/usr/bin/env bash
# Compile the pinned device-tested KernelSU SOURCE revision.
# The next job stage embeds this newly built candidate into an opt-in APK.
# This script itself never touches known-good files or interacts with a device.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
REF=78ed5d1f5b5041a197f0b55291876d62a6bd7c67
REPO=https://github.com/KernelSU-Next/KernelSU-Next.git
WORK="$ROOT/work-ksunext-reference/KernelSU-Next"
DIST="$ROOT/dist-ksunext-reference"
GOOD="$ROOT/known-good/working-v6.ko"
PATCH="$ROOT/patches/ksunext/tested-revision/apply-tested-selinux.py"
BUILDER="$ROOT/patches/ksunext/tested-revision/build-in-docker.sh"
for cmd in git python3 docker sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 2; }
done
[[ -f "$GOOD" && -f "$ROOT/known-good/working-v6.sha256" ]] || {
  echo 'Device-tested .ko and checksum must be present' >&2; exit 1;
}
(cd "$ROOT/known-good" && sha256sum -c working-v6.sha256)
mkdir -p "$(dirname "$WORK")" "$DIST"
rm -rf -- "$WORK"
# Avoid accidentally using tag v3.4.1, a moved branch, or stale sources.
git init -q "$WORK"
git -C "$WORK" remote add origin "$REPO"
git -C "$WORK" -c protocol.version=2 fetch -q --depth=1 origin "$REF"
git -C "$WORK" checkout -q --detach FETCH_HEAD
[[ "$(git -C "$WORK" rev-parse HEAD)" == "$REF" ]] || {
  echo 'Git revision mismatch' >&2; exit 1;
}
python3 "$PATCH" "$WORK"
git -C "$WORK" diff -- kernel/core/init.c > "$DIST/device-tested-selinux-change.diff"
printf '%s\n' "$REF" > "$DIST/source-commit.txt"
printf '%s\n' 'ghcr.io/ylarod/ddk-min:android14-5.15-20260828' > "$DIST/ddk-image.txt"
# Any failure stops the integrated build; the APK must never fall back to known-good.
bash "$BUILDER" "$WORK" "$DIST"
KO="$DIST/KernelSU-Next-C3U-REBUILT-UNVERIFIED-DO-NOT-LOAD.ko"
python3 "$ROOT/tools/compare-ksunext-modules.py" --known "$GOOD" \
  --candidate "$KO" --output "$DIST"
echo "KernelSU compiled module + comparison artifact ready for APK embedding: $DIST"
