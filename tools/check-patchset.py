#!/usr/bin/env python3
"""Validate that the pinned DFRoot C3U overlay patchset is internally complete."""
import json
from pathlib import Path
BASE = Path(__file__).resolve().parents[1]
series = json.loads((BASE/'patches/dfroot/patchset/series.json').read_text())
assert series['schema_version'] == 1
assert series['upstream']['repository'] == 'diabl0w/DFRoot'
assert series['upstream']['ref'] == 'v3.1'
assert series['service_owned_exploit_status'] == 'IMPLEMENTED_SOURCE_REVIEWED_DEVICE_UNTESTED'
for stage in series['stages']:
    path = BASE / stage['entrypoint']
    assert path.is_file(), f"Missing patchset component {stage['id']}: {path}"
    print(stage['id'], stage['scope'], path.relative_to(BASE))
print('Patchset consistent (service worker source reviewed; current patch not device-tested)')
