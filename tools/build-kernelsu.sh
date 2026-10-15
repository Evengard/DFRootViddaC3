#!/usr/bin/env bash
# Build the chosen KernelSU Next ref (default: dev), C3U patch, and ABI report.
# This is the only KernelSU source; the old static binary is not used.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
REF="${C3U_KSUN_REF:-dev}"
REPO=https://github.com/KernelSU-Next/KernelSU-Next.git
WORK="$ROOT/work/KernelSU-Next"
DIST="$ROOT/dist/vidda-c3-kernelsu"
BASELINE="$ROOT/config/kernel-abi-baseline.json"
PATCH="$ROOT/patches/ksunext/dynamic/apply-c3u.py"
BUILDER="$ROOT/patches/ksunext/build-in-docker.sh"
for cmd in git python3 docker sha256sum; do
  command -v "$cmd" >/dev/null || { echo "Missing $cmd" >&2; exit 2; }
done
# A ref is always handled as data, not an interpolated shell command.
[[ ${#REF} -le 128 && "$REF" =~ ^[A-Za-z0-9._/-]+$ && "$REF" != -* && "$REF" != *..* ]] || {
  echo 'Invalid KernelSU branch/tag/commit ref' >&2; exit 2;
}
[[ -s "$BASELINE" ]] || { echo 'Device-tested ABI metadata is required' >&2; exit 1; }
mkdir -p "$(dirname "$WORK")" "$DIST"
rm -rf -- "$WORK"
git init -q "$WORK"
git -C "$WORK" remote add origin "$REPO"
# Full history and tags are required for the REAL 30000+Git-commit-count version.
# A shallow checkout silently produces misleading version codes.
git -C "$WORK" -c protocol.version=2 fetch -q --no-prune --tags origin
if git -C "$WORK" rev-parse --verify -q "refs/remotes/origin/$REF^{commit}" >/dev/null; then
  TARGET="refs/remotes/origin/$REF"
elif git -C "$WORK" rev-parse --verify -q "refs/tags/$REF^{commit}" >/dev/null; then
  TARGET="refs/tags/$REF"
elif [[ "$REF" =~ ^[a-fA-F0-9]{7,40}$ ]] && git -C "$WORK" rev-parse --verify -q "$REF^{commit}" >/dev/null; then
  TARGET="$REF"
else
  echo "KernelSU ref '$REF' not found; expected branch, tag, or reachable commit" >&2
  exit 1
fi
git -C "$WORK" checkout -q --detach "$TARGET"
# The selector above always gets the actual resolved Git SHA from a complete tree.
python3 "$PATCH" "$WORK" "$DIST" --ref "$REF"
git -C "$WORK" diff -- kernel/core/init.c kernel/Kbuild > "$DIST/vidda-c3-kernelsu-source-patch.diff"
printf '%s\n' 'ghcr.io/ylarod/ddk-min:android14-5.15-20260828' > "$DIST/ddk-image.txt"
bash "$BUILDER" "$WORK" "$DIST"
KO="$DIST/ViddaC3-KernelSU-Next.ko"
SOURCE_SHA="$(cat "$DIST/source-commit.txt")"
python3 "$ROOT/tools/compare-kernelsu-abi.py" --baseline "$BASELINE" \
  --candidate "$KO" --source-revision "$SOURCE_SHA" --output "$DIST"
echo "KernelSU ref '$REF' compiled and compared; source SHA: $SOURCE_SHA"
