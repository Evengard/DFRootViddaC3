#!/usr/bin/env python3
"""Offline comparison: newly built KernelSU module vs device-tested reference.

This utility inspects files only. The subsequent CI stage will embed the new
module into an opt-in APK and separately verify those packaged bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

KNOWN_GOOD_SHA = '7b5374327b316ccb4e0c4271b938b664f193b7aeb3dd25bd9428976a6c08a38b'
TESTED_SOURCE = '78ed5d1f5b5041a197f0b55291876d62a6bd7c67'
DDK_IMAGE = 'ghcr.io/ylarod/ddk-min:android14-5.15-20260828'


def sha256(file: Path) -> str:
    h = hashlib.sha256()
    with file.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


# Parse only the ELF structures needed for the comparison. This deliberately uses
# the Python standard library, so the offline tests run on macOS as well as Linux
# without Homebrew's binutils/llvm tools.
_ELF_HEADER = struct.Struct('<16sHHIQQQIHHHHHH')
_SECTION_HEADER = struct.Struct('<IIQQQQIIQQ')
_SYMBOL = struct.Struct('<IBBHQQ')


def _unpack(fmt: struct.Struct, data: bytes, offset: int, source: Path):
    if offset < 0 or offset + fmt.size > len(data):
        raise ValueError(f'{source}: truncated ELF structure at offset {offset}')
    return fmt.unpack_from(data, offset)


def _null_string(data: bytes, offset: int, source: Path) -> str:
    if not (0 <= offset < len(data)):
        raise ValueError(f'{source}: invalid ELF string-table offset {offset}')
    end = data.find(b'\0', offset)
    if end < 0:
        raise ValueError(f'{source}: unterminated ELF string at offset {offset}')
    return data[offset:end].decode('utf-8', errors='replace')


def metadata(path: Path) -> dict:
    data = path.read_bytes()
    (
        ident, elf_type, machine, version, _entry, _phoff, shoff, _flags,
        ehsize, _phentsize, _phnum, shentsize, shnum, shstrndx,
    ) = _unpack(_ELF_HEADER, data, 0, path)
    if (ident[:4] != b'\x7fELF' or ident[4] != 2 or ident[5] != 1
            or elf_type != 1 or machine != 183 or version != 1):
        raise ValueError(f'{path}: expected little-endian ELF64 AArch64 relocatable module')
    if ehsize != _ELF_HEADER.size or shentsize != _SECTION_HEADER.size or shnum == 0:
        raise ValueError(f'{path}: unsupported or malformed ELF section headers')
    if shnum > (len(data) - shoff) // shentsize or not (0 < shstrndx < shnum):
        raise ValueError(f'{path}: invalid ELF section-header table')

    sections = [
        _unpack(_SECTION_HEADER, data, shoff + i * shentsize, path)
        for i in range(shnum)
    ]

    def section_bytes(sh):
        # An SHT_NOBITS section has no contents in the file.
        if sh[1] == 8 or sh[4] > len(data) or sh[5] > len(data) - sh[4]:
            raise ValueError(f'{path}: missing or out-of-bounds ELF section')
        return data[sh[4]:sh[4] + sh[5]]

    names = section_bytes(sections[shstrndx])
    named = {_null_string(names, sh[0], path): sh for sh in sections[1:]}
    modinfo = named.get('.modinfo')
    if modinfo is None:
        raise ValueError(f'{path}: missing .modinfo section')
    vermagic = next(
        (item[len(b'vermagic='):].decode('utf-8', errors='replace')
         for item in section_bytes(modinfo).split(b'\0')
         if item.startswith(b'vermagic=')),
        'unavailable',
    )

    symtab = named.get('.symtab')
    if symtab is None or symtab[1] != 2 or symtab[9] != _SYMBOL.size:
        raise ValueError(f'{path}: missing or invalid .symtab section')
    strtab_index = symtab[6]  # sh_link references the symbol string table
    if not (0 < strtab_index < len(sections)) or sections[strtab_index][1] != 3:
        raise ValueError(f'{path}: invalid symbol string-table link')
    strings = section_bytes(sections[strtab_index])
    symbols = section_bytes(symtab)
    if len(symbols) % _SYMBOL.size:
        raise ValueError(f'{path}: malformed ELF symbol table')
    undefined = set()
    for offset in range(0, len(symbols), _SYMBOL.size):
        name_offset, _info, _other, section_index, _value, _size = _SYMBOL.unpack_from(symbols, offset)
        if section_index == 0 and name_offset != 0:  # SHN_UNDEF
            name = _null_string(strings, name_offset, path)
            if name:
                undefined.add(name)
    if not undefined:
        raise ValueError(f'{path}: no undefined symbols parsed from ELF .symtab')
    return {
        'sha256': sha256(path),
        'size': len(data),
        'vermagic': vermagic,
        'undefined_symbols': sorted(undefined),
        'undefined_count': len(undefined),
    }


def compare(known: Path, candidate: Path) -> dict:
    good = metadata(known)
    if good['sha256'] != KNOWN_GOOD_SHA:
        raise ValueError(f'Reference module is not the device-tested binary: {good["sha256"]}')
    built = metadata(candidate)
    good_syms = set(good['undefined_symbols'])
    new_syms = set(built['undefined_symbols'])
    match = good['sha256'] == built['sha256']
    return {
        'status': 'byte_identical_to_tested_module' if match else 'candidate_differs_UNVERIFIED',
        'source_revision': TESTED_SOURCE,
        'ddk_image_tag': DDK_IMAGE,
        'device_tested_known_good': good,
        'rebuilt_candidate': built,
        'candidate_matches_known_good_bytes': match,
        'candidate_only_undefined_symbols': sorted(new_syms - good_syms),
        'known_good_only_undefined_symbols': sorted(good_syms - new_syms),
        'comparison_is_read_only': True,
        'uploads_to_projector': False,
        'runtime_validation': 'rebuilt candidate requires on-device validation if bytes differ',
    }


def markdown(result: dict) -> str:
    good, cand = result['device_tested_known_good'], result['rebuilt_candidate']
    return '\n'.join([
        '# C3U KernelSU reference rebuild comparison',
        '',
        f'**Result:** `{result["status"]}`',
        '',
        f'Pinned KernelSU source: `{result["source_revision"]}`',
        f'DDK image tag: `{result["ddk_image_tag"]}`',
        '',
        '| Property | Device-tested original | Rebuilt candidate |',
        '|---|---|---|',
        f'| SHA-256 | `{good["sha256"]}` | `{cand["sha256"]}` |',
        f'| Size (bytes) | {good["size"]} | {cand["size"]} |',
        f'| Vermagic | `{good["vermagic"]}` | `{cand["vermagic"]}` |',
        f'| Undefined symbols | {good["undefined_count"]} | {cand["undefined_count"]} |',
        '',
        '## Candidate-only undefined symbols',
        *(f'- `{s}`' for s in result['candidate_only_undefined_symbols']),
        '' if result['candidate_only_undefined_symbols'] else 'None.',
        '',
        '## Known-good-only undefined symbols',
        *(f'- `{s}`' for s in result['known_good_only_undefined_symbols']),
        '' if result['known_good_only_undefined_symbols'] else 'None.',
        '',
        '**Safety boundary:** The next CI stage embeds the newly compiled module in',
        'an APK with opt-in loading. Build-time checks cannot establish device stability.',
        'Successful ABI checks cannot establish kernel stability if the bytes differ.',
        '',
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--known', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for f in (args.known, args.candidate):
        if not f.is_file() or f.stat().st_size < 1024:
            parser.error(f'Missing or suspiciously small ELF module: {f}')
    result = compare(args.known, args.candidate)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'module-comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.output / 'module-comparison.md').write_text(markdown(result))
    print('PASS: known-good module hash verified; candidate examined offline')
    print(f'Comparison: {result["status"]}')
    if not result['candidate_matches_known_good_bytes']:
        print('WARNING: new module differs from tested bytes; compiled-mode APK requires device validation.')


if __name__ == '__main__':
    main()
