#!/usr/bin/env python3
"""Read an already verified apksigner report, regardless of signer-line format.

Run `apksigner verify --verbose --print-certs apk` *first*, checking its exit
status. This parser handles text emitted by Android Build Tools <=36 and 37+.
It fails closed on missing, malformed, or conflicting signing certificates.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re

# Build Tools <=36: "Signer #1 certificate SHA-256 digest: ..."
# Build Tools 37:  "V2 Signer: certificate SHA-256 digest: ..."
#                  "V3.0 Signer: certificate SHA-256 digest: ..."
# The digest is printed once for each signature scheme; repeated identical
# digests still indicate one signing identity.
CERT_LINE = re.compile(
    r"(?im)^\s*[^\r\n]*?\bcertificate\s+SHA-256\s+digest:\s*([0-9a-fA-F]{64})\s*$"
)


def fingerprint(report: str) -> str:
    values = {match.lower() for match in CERT_LINE.findall(report)}
    if not values:
        raise ValueError(
            'Verified APK report does not include a recognized certificate SHA-256 digest'
        )
    if len(values) != 1:
        raise ValueError('APK report contains conflicting signer certificate SHA-256 digests')
    return next(iter(values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path, help='Output of apksigner verify --print-certs')
    args = parser.parse_args()
    try:
        print(fingerprint(args.report.read_text(encoding='utf-8')))
    except (OSError, UnicodeError, ValueError) as exc:
        parser.exit(1, f'ERROR: Could not verify APK signing certificate: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
