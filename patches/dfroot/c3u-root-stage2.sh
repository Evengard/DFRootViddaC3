#!/system/bin/sh
# Headless KernelSU Next bootstrap ONLY AFTER temporary root is already available.
# It does NOT perform DirtyFrag and cannot turn an unprivileged launcher into root.
# Use an exact validated v6 .ko; no boot partition modifications.
set -eu
KO=${1:?Usage: c3u-root-stage2.sh /path/to/working-v6.ko SHA256}
EXPECTED_HASH=${2:?Usage: c3u-root-stage2.sh /path/to/working-v6.ko SHA256}
KERNEL='5.15.148-android14-11-g7b7674251b5d-dirty'
FP='Hisense/VIDAA_TV/MT9655:14/UQ1A.240105.004.A1/07.02.70.202512281739:user/release-keys'

msg() { /system/bin/log -t C3U-KSU "${1}" 2>/dev/null || true; printf '%s\n' "${1}"; }
fail() { msg "FAIL: $1"; exit 1; }
[ "$(/system/bin/id -u)" = 0 ] || fail 'temporary root is required; this is only stage 2'
[ "$(uname -r)" = "$KERNEL" ] || fail 'kernel release changed'
[ "$(getprop ro.build.fingerprint)" = "$FP" ] || fail 'firmware fingerprint changed'
[ "$(getenforce)" = 'Permissive' ] || fail 'expected baseline SELinux Permissive'
[ -f "$KO" ] || fail 'supplied .ko file is missing'
actual=$(sha256sum "$KO" | cut -d' ' -f1)
[ "$actual" = "$EXPECTED_HASH" ] || fail 'module SHA256 mismatch; refusing unsafe module'
KSUD=/data/adb/ksud
[ -x "$KSUD" ] || fail 'KernelSU Next /data/adb/ksud not installed'

# Detect a partial load before doing anything. /proc/modules line format
# puts the module state in field 5 on Linux 5.15.
line=$(grep '^kernelsu ' /proc/modules || true)
if [ -z "$line" ]; then
    msg 'Loading the validated C3U v6 module via symbol-aware ksud insmod...'
    "$KSUD" insmod "$KO" || fail 'ksud insmod failed (do not retry repeatedly)'
    line=$(grep '^kernelsu ' /proc/modules || true)
fi
printf '%s\n' "$line" | grep -q ' Live ' || fail 'kernelsu not Live; aborting'
[ "$(getenforce)" = 'Permissive' ] || fail 'SELinux enforcement changed after insmod'
msg 'Module is Live. Initializing KernelSU late-load userspace...'
"$KSUD" late-load || fail 'late-load returned failure'
[ "$(getenforce)" = 'Permissive' ] || fail 'SELinux enforcement unexpectedly changed'
line=$(grep '^kernelsu ' /proc/modules || true)
printf '%s\n' "$line" | grep -q ' Live ' || fail 'module is no longer Live'
msg 'KernelSU is Live and SELinux remains Permissive.'
