#!/usr/bin/env python3
"""Read-only check of KernelSU .ko DWARF types against observed C3U kernel layout.

This deliberately does NOT claim full module ABI compatibility or load modules.
Requires `readelf` and DWARF info in the ELF module.
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

TAG = re.compile(r'^\s*<(\d+)><[0-9a-fA-F]+>: Abbrev Number: \d+ \((DW_TAG_\w+)\)')
ATTR = re.compile(r'^\s*<[0-9a-fA-F]+>\s+DW_AT_(name|byte_size|data_member_location)\s*:\s*(.*)$')


def parse_int(s):
    s = s.strip().split()[0]
    try:
        return int(s, 0)
    except ValueError:
        return int(s)


def parse_dwarf(module):
    cmd = ['readelf', '--debug-dump=info', str(module)]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding='utf-8', errors='replace')
    except FileNotFoundError:
        raise RuntimeError('readelf is required (available in the DDK container)')
    results = []
    st = None
    mem = None
    die_type = None
    die_depth = None

    def finish_member():
        nonlocal mem
        if st is not None and mem is not None and mem.get('name') is not None:
            st['members'][mem['name']] = mem.get('offset')
        mem = None

    def finish_struct():
        nonlocal st
        if st is not None and st.get('name') in ('selinux_state', 'mutex', 'task_struct'):
            results.append(st)
        st = None

    for line in proc.stdout:
        tm = TAG.match(line)
        if tm:
            depth, kind = int(tm.group(1)), tm.group(2)
            if mem is not None and depth <= mem['depth']:
                finish_member()
            if st is not None and depth <= st['depth']:
                finish_struct()
            if kind == 'DW_TAG_structure_type':
                st = dict(depth=depth, name=None, size=None, members={})
            elif kind == 'DW_TAG_member' and st is not None and depth == st['depth'] + 1:
                mem = dict(depth=depth)
            die_type, die_depth = kind, depth
            continue
        am = ATTR.match(line)
        if not am:
            continue
        attr, value = am.groups()
        if attr == 'name':
            value = value.rsplit(': ', 1)[-1].strip() if '(indirect string' in value else value.strip()
            if st is not None and die_type == 'DW_TAG_structure_type' and die_depth == st['depth']:
                st['name'] = value
            if mem is not None and die_type == 'DW_TAG_member' and die_depth == mem['depth']:
                mem['name'] = value
        elif attr == 'byte_size' and st is not None and die_type == 'DW_TAG_structure_type' and die_depth == st['depth']:
            st['size'] = parse_int(value)
        elif attr == 'data_member_location' and mem is not None and die_type == 'DW_TAG_member' and die_depth == mem['depth']:
            mem['offset'] = parse_int(value)
    finish_member()
    finish_struct()
    err = proc.stderr.read()
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f'readelf failed with status {code}: {err[:1500]}')
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', type=Path)
    parser.add_argument('--show-only', action='store_true', help='print offsets without checking expected C3U values')
    args = parser.parse_args()
    if not args.module.is_file():
        parser.error(f'Module not found: {args.module}')
    layouts = parse_dwarf(args.module)
    if not layouts:
        sys.exit('ERROR: No DWARF structure metadata. Cannot certify even the targeted layout.')

    expected = {
        'selinux_state': dict(size=104, members={'status_lock': 0x18, 'policy': 0x40, 'policy_mutex': 0x48}),
        'mutex': dict(size=32, members={'owner': 0, 'wait_lock': 8, 'osq': 12, 'wait_list': 16}),
        'task_struct': dict(size=3840, members={
            'tasks': 0x4b8,
            'mm': 0x508,
            'pid': 0x5c0,
            'group_leader': 0x600,
            'thread_pid': 0x628,
            'thread_node': 0x680,
            'real_cred': 0x778,
            'cred': 0x780,
            'comm': 0x790,
            'nsproxy': 0x7c0,
            'signal': 0x7c8,
        }),
    }
    failures = []
    for ty, exp in expected.items():
        variants = [x for x in layouts if x['name'] == ty and x['size'] is not None]
        unique = {}
        for x in variants:
            unique[(x['size'], tuple(sorted(x['members'].items())))] = x
        variants = list(unique.values())
        if not variants:
            failures.append(f'{ty}: no complete DWARF definition')
            continue
        for x in variants:
            print(f'{ty}: sizeof={x["size"]} bytes, checked fields=' +
                  ', '.join(f'{k}@0x{v:x}' for k, v in x['members'].items()
                            if k in exp['members'] and v is not None))
            if x['size'] != exp['size']:
                failures.append(f'{ty} size {x["size"]}, expected {exp["size"]}')
            for field, off in exp['members'].items():
                if x['members'].get(field) != off:
                    failures.append(f'{ty}.{field} offset {x["members"].get(field)}, expected {off}')
            if 'android_oem_data1' in x['members']:
                failures.append(f'{ty} includes android_oem_data1, absent in C3U kernel build')
            if ty == 'task_struct' and any(k.startswith('android_kabi_reserved') for k in x['members']):
                failures.append('task_struct still contains Android KABI reservations')
    if failures:
        print('\nTargeted ABI check does NOT match:')
        for item in sorted(set(failures)):
            print(' - ' + item)
        if not args.show_only:
            sys.exit(1)
    else:
        print('\nTargeted SELinux, mutex and task_struct layout checks PASSED.')
        print('This is NOT a general kernel ABI or module-safety guarantee.')


if __name__ == '__main__':
    main()
