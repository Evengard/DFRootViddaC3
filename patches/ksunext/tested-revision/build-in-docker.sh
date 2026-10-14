#!/usr/bin/env bash
# Rebuild reference KernelSU source as a separate, unverified candidate.
# Based on the builder archived with the module that worked on the C3U.
# No insmod, no flashing, no APK modification, no device interaction.
set -euo pipefail
if [[ $# -ne 2 ]]; then
  echo "Usage: bash build-in-docker.sh /absolute/patched/KernelSU-Next /absolute/output" >&2
  exit 2
fi
for exe in docker sha256sum; do command -v "$exe" >/dev/null || { echo "Missing $exe" >&2; exit 2; }; done
KSU_REPO="$(cd "$1" && pwd -P)"
OUT="$(cd "$2" && pwd -P)"
[[ -f "$KSU_REPO/kernel/Makefile" && -f "$KSU_REPO/kernel/Kbuild" ]] || { echo 'Not a KernelSU checkout' >&2; exit 2; }
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
LAYOUT_CHECK="$SCRIPT_DIR/../verify-module-layout.py"
[[ -f "$LAYOUT_CHECK" ]] || { echo "Missing $LAYOUT_CHECK" >&2; exit 2; }
# This is the exact DDK tag from the archived successful-module builder.
IMAGE="ghcr.io/ylarod/ddk-min:android14-5.15-20260828"
printf 'Reference rebuild image: %s\n' "$IMAGE"
docker run --rm --platform linux/amd64 \
  -v "$KSU_REPO:/ksunext" -v "$OUT:/result" \
  -v "$LAYOUT_CHECK:/verify-module-layout.py:ro" \
  -w /ksunext/kernel "$IMAGE" /bin/bash -euo pipefail -c '
    KMI="android14-5.15"
    : "${KDIR:=/opt/ddk/kdir/$KMI}"
    KERNEL_SRC="/opt/ddk/src/$KMI"
    [[ -f "$KDIR/.config" && -f "$KERNEL_SRC/scripts/config" ]] || {
      echo "DDK files missing: $KDIR / $KERNEL_SRC" >&2; exit 1;
    }
    cp "$KDIR/.config" /result/ddk-config-before.txt
    "$KERNEL_SRC/scripts/config" --file "$KDIR/.config" \
       -d KASAN -d KASAN_HW_TAGS -d KASAN_SW_TAGS -d KASAN_GENERIC \
       -d ANDROID_VENDOR_OEM_DATA \
       -d ANDROID_KABI_RESERVE -d DETECT_HUNG_TASK \
       -d ARM64_PTR_AUTH -d ARM64_PTR_AUTH_KERNEL -d ARM64_MTE \
       -e NUMA -e DEBUG_STACK_USAGE \
       -d LTO_CLANG_FULL -e LTO_CLANG_THIN
    make -C "$KERNEL_SRC" O="$KDIR" ARCH=arm64 LLVM=1 olddefconfig
    make -C "$KERNEL_SRC" O="$KDIR" ARCH=arm64 LLVM=1 modules_prepare
    cp "$KDIR/.config" /result/ddk-config-after.txt
    for key in KASAN ANDROID_VENDOR_OEM_DATA ANDROID_KABI_RESERVE DETECT_HUNG_TASK ARM64_PTR_AUTH ARM64_MTE LTO_CLANG_FULL; do
      grep -qx "# CONFIG_${key} is not set" "$KDIR/.config" || {
        echo "Refusing unexpected CONFIG_${key} setting" >&2; exit 1;
      }
    done
    for key in NUMA DEBUG_STACK_USAGE LTO_CLANG_THIN; do
      grep -qx "CONFIG_${key}=y" "$KDIR/.config" || {
        echo "Refusing unexpected CONFIG_${key} setting" >&2; exit 1;
      }
    done
    make -C "$KDIR" M="$PWD" src="$PWD" clean
    rm -f check_symbol
    CONFIG_KSU=m CC=clang make -C "$KDIR" M="$PWD" src="$PWD" modules -j4
    test -s kernelsu.ko
    if ! grep -aFq "Permissive SELinux, keeping" kernelsu.ko; then
      echo "Missing device-tested permissive-preservation marker" >&2; exit 1;
    fi
    if readelf -rW core/init.o | grep -E "[[:space:]]setenforce([+[:space:]]|$)"; then
      echo "Refusing init.o with setenforce relocation" >&2; exit 1;
    fi
    if readelf -Ws kernelsu.ko | grep -E "[[:space:]]UND[[:space:]].*kasan_flag_enabled"; then
      echo "Refusing unresolved kasan_flag_enabled" >&2; exit 1;
    fi
    python3 /verify-module-layout.py kernelsu.ko | tee /result/layout-report.txt
    readelf -h kernelsu.ko | grep "Machine:" > /result/module-info.txt
    readelf -p .modinfo kernelsu.ko | grep -i vermagic >> /result/module-info.txt || true
    readelf -Ws kernelsu.ko | awk "\$7 == \"UND\" && \$8 != \"\" {print \$8}" | sort -u > /result/undefined-module-symbols.txt
    # Retain the upstream DDK-symbol check as a diagnostic only, because the
    # DDK vmlinux was not rebuilt with our altered C3U ABI-relevant Kconfig.
    clang tools/check_symbol.c -o check_symbol
    if ./check_symbol kernelsu.ko "$KDIR/vmlinux" > /result/ddk-symbol-check.txt 2>&1; then
      echo "DDK symbol diagnostic passed"
    else
      echo "DDK symbol diagnostic reported mismatches; inspect report"
    fi
    cp kernelsu.ko /result/KernelSU-Next-C3U-REBUILT-UNVERIFIED-DO-NOT-LOAD.ko
    sha256sum /result/KernelSU-Next-C3U-REBUILT-UNVERIFIED-DO-NOT-LOAD.ko > /result/rebuilt-module.sha256
    echo "Offline candidate complete; this module has NOT been tested on device"
  '
