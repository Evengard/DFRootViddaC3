#!/usr/bin/env bash
# Internal v6 Docker build: single experimental KernelSU Next LKM for C3U
# (android14-5.15), matching selected experimentally observed C3U structure layouts.
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /absolute/path/to/KernelSU-Next [output-directory]" >&2
  exit 2
fi

command -v docker >/dev/null || { echo "Docker is required" >&2; exit 2; }
KSU_REPO="$(cd "$1" && pwd -P)"
if [[ ! -f "$KSU_REPO/kernel/Makefile" || ! -f "$KSU_REPO/kernel/Kbuild" ]]; then
  echo "Not a KernelSU Next checkout: $KSU_REPO" >&2
  exit 2
fi
OUT="${2:-$PWD/ksunext-c3u-out}"
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd -P)"

IMAGE="ghcr.io/ylarod/ddk-min:android14-5.15-20260828"
TOOL_DIR="$(cd "$(dirname "$0")" && pwd -P)"
printf 'KernelSU Next temporary clean checkout: %s\nOutput: %s\nDocker image: %s\n' "$KSU_REPO" "$OUT" "$IMAGE"

docker run --rm --platform linux/amd64 \
  -v "$KSU_REPO:/ksunext" -v "$OUT:/result" \
  -v "$TOOL_DIR/verify-module-layout.py:/verify-module-layout.py:ro" \
  -w /ksunext/kernel \
  "$IMAGE" /bin/bash -euo pipefail -c '
    KMI="android14-5.15"
    : "${KDIR:=/opt/ddk/kdir/$KMI}"
    KERNEL_SRC="/opt/ddk/src/$KMI"
    if [[ ! -f "$KDIR/.config" || ! -f "$KERNEL_SRC/scripts/config" ]]; then
      echo "Missing DDK kernel configuration or scripts/config. KDIR=$KDIR source=$KERNEL_SRC" >&2
      exit 1
    fi

    printf "DDK original ABI-relevant settings:\n"
    grep -E "^(CONFIG_|# CONFIG_)(KASAN|ANDROID_VENDOR_OEM_DATA|ANDROID_KABI_RESERVE|DETECT_HUNG_TASK|ARM64_PTR_AUTH|ARM64_MTE|NUMA|DEBUG_STACK_USAGE|LTO_CLANG_(THIN|FULL))([= ]|$)" "$KDIR/.config" || true
    cp "$KDIR/.config" /result/ddk-config-before.txt

    # Reconfigure DDK output kernel headers; do NOT touch the live device.
    "$KERNEL_SRC/scripts/config" --file "$KDIR/.config" \
       -d KASAN -d KASAN_HW_TAGS -d KASAN_SW_TAGS -d KASAN_GENERIC \
       -d ANDROID_VENDOR_OEM_DATA \
       -d ANDROID_KABI_RESERVE -d DETECT_HUNG_TASK \
       -d ARM64_PTR_AUTH -d ARM64_PTR_AUTH_KERNEL -d ARM64_MTE \
       -e NUMA -e DEBUG_STACK_USAGE \
       -d LTO_CLANG_FULL -e LTO_CLANG_THIN
    make -C "$KERNEL_SRC" O="$KDIR" ARCH=arm64 LLVM=1 olddefconfig
    make -C "$KERNEL_SRC" O="$KDIR" ARCH=arm64 LLVM=1 modules_prepare

    echo "DDK resulting ABI-relevant settings:"
    grep -E "^(CONFIG_|# CONFIG_)(KASAN|ANDROID_VENDOR_OEM_DATA|ANDROID_KABI_RESERVE|DETECT_HUNG_TASK|ARM64_PTR_AUTH|ARM64_MTE|NUMA|DEBUG_STACK_USAGE|LTO_CLANG_(THIN|FULL))([= ]|$)" "$KDIR/.config" || true
    cp "$KDIR/.config" /result/ddk-config-after.txt
    if ! grep -qx "# CONFIG_KASAN is not set" "$KDIR/.config"; then
      echo "KASAN is still enabled; refusing to build." >&2
      exit 1
    fi

    # Fail closed if Kconfig silently restored a mismatched value.
    for key in KASAN ANDROID_VENDOR_OEM_DATA ANDROID_KABI_RESERVE DETECT_HUNG_TASK ARM64_PTR_AUTH ARM64_MTE LTO_CLANG_FULL; do
      if ! grep -qx "# CONFIG_${key} is not set" "$KDIR/.config"; then
        echo "CONFIG_${key} was not disabled as requested; refusing to build." >&2
        exit 1
      fi
    done
    for key in NUMA DEBUG_STACK_USAGE LTO_CLANG_THIN; do
      if ! grep -qx "CONFIG_${key}=y" "$KDIR/.config"; then
        echo "CONFIG_${key} is not enabled as requested; refusing to build." >&2
        exit 1
      fi
    done

    # KernelSU Next Makefile `make clean` calls plain `rm check_symbol` and
    # fails on a fresh checkout where `check_symbol` does not yet exist.
    # Clean via external-module Kbuild instead, then remove the helper safely.
    make -C "$KDIR" M="$PWD" src="$PWD" clean
    rm -f check_symbol
    # Compile using Kbuild itself rather than the upstream wrapper Makefile.
    # The upstream wrapper subsequently invokes check_symbol against the
    # DDK image-provided vmlinux, which was NOT rebuilt with our modified
    # Kconfig. That check can reject symbols that exist on the projector.
    CONFIG_KSU=m CC=clang make -C "$KDIR" M="$PWD" src="$PWD" modules -j4
    test -s kernelsu.ko

    # A source patch alone is not enough: the built object MUST contain the
    # v6 message and MUST NOT call setenforce() from the init translation unit.
    if ! grep -aFq "C3U: preserving permissive SELinux" kernelsu.ko; then
      echo "FATAL: v6 permissive-preservation marker absent from .ko" >&2
      exit 1
    fi
    if readelf -rW core/init.o | grep -E "[[:space:]]setenforce([+[:space:]]|$)"; then
      echo "FATAL: kernel/core/init.o still calls setenforce()" >&2
      exit 1
    fi
    echo "PASS: v6 marker is linked, no setenforce() relocation in core/init.o." | tee /result/v6-selinux-check.txt

    # Keep the original upstream symbol check as DIAGNOSTICS, not a release gate.
    # An error here is NOT a sign that the symbol exists on the real C3U.
    clang tools/check_symbol.c -o check_symbol
    if ./check_symbol kernelsu.ko "$KDIR/vmlinux" > /result/ddk-symbol-check.txt 2>&1; then
      echo "DDK vmlinux diagnostic symbol check passed."
    else
      echo "NOTE: DDK vmlinux symbol check reported mismatches."
      echo "      This vmlinux was not rebuilt for the modified config."
      echo "      Review /result/ddk-symbol-check.txt; verify actual C3U exports."
      cat /result/ddk-symbol-check.txt
    fi
    readelf -Ws kernelsu.ko | awk "\$7 == \"UND\" && \$8 != \"\" { print \$8 }" | sort -u > /result/undefined-module-symbols.txt
    if grep -qx alloc_pages /result/undefined-module-symbols.txt; then
      echo "WARNING: module references alloc_pages; confirm it exists in C3U /proc/kallsyms before ANY load attempt."
    fi

    if readelf -Ws kernelsu.ko | grep -E "[[:space:]]UND[[:space:]].*kasan_flag_enabled"; then
      echo "ERROR: rebuilt module still requires kasan_flag_enabled. Do NOT load." >&2
      exit 1
    fi

    command -v python3 >/dev/null || { echo "Python 3 is required for offline DWARF layout validation." >&2; exit 1; }
    python3 /verify-module-layout.py kernelsu.ko | tee /result/layout-report.txt

    readelf -h kernelsu.ko | grep "Machine:" > /result/module-info.txt
    readelf -p .modinfo kernelsu.ko | grep -i "vermagic" >> /result/module-info.txt || true
    cp kernelsu.ko /result/aarch64_android14-5.15_kernelsu-c3u-permissive-v6-UNVERIFIED-DO-NOT-LOAD.ko
    sha256sum kernelsu.ko > /result/module-sha256-in-container.txt
    echo "Saved UNVERIFIED analysis module and diagnostics to /result. No device has been modified."
  '

echo "Targeted layout checks passed; symbol compatibility with the projector is NOT established. DO NOT LOAD."
