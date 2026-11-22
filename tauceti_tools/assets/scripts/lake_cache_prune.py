#!/usr/bin/env python3
"""Drop Lake cache mappings whose artifacts never arrived, keeping every verified artifact.

Usage: python3 scripts/lake_cache_prune.py <project>/.lake/cache

lake-cache-get.sh calls this under LAKE_CACHE_INCOMPLETE=prune after every attempt of an
incomplete transfer. Lake installs an artifact only after verifying its hash, so every artifact
file present is sound; a mapping record (outputs/<scope>/<input hash>.json) that names an absent
artifact would be unresolvable and fail the offline build under `--iofail`. Removing exactly those
records makes Lake treat the affected modules as cache misses and build them from source, while
the rest of the package still restores from the cache. A record this cannot read is removed too.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

ARTIFACT = re.compile(r"[0-9a-f]{16}(?:\.[A-Za-z0-9.]+)?")


def references(value):
    """Artifact names a mapping record refers to: its archive, or the hashes in its descriptors."""
    if isinstance(value, str):
        return [value] if ARTIFACT.fullmatch(value) else []
    if isinstance(value, dict):
        return [name for item in value.values() for name in references(item)]
    if isinstance(value, list):
        return [name for item in value for name in references(item)]
    return []


def present(artifacts: Path, name: str) -> bool:
    if (artifacts / name).is_file():
        return True
    return "." not in name and any(path.is_file() for path in artifacts.glob(name + ".*"))


def prune(cache: Path) -> tuple[int, int]:
    """Remove unresolvable mapping records; return (kept, removed)."""
    artifacts = cache / "artifacts"
    kept = removed = 0
    for record in sorted((cache / "outputs").glob("*/*.json")):
        try:
            names = references(json.loads(record.read_text()).get("data"))
        except (OSError, ValueError, AttributeError):
            names = []
        if names and all(present(artifacts, name) for name in names):
            kept += 1
        else:
            record.unlink(missing_ok=True)
            removed += 1
    return kept, removed


def main(cache: Path) -> int:
    kept, removed = prune(cache)
    print(f"Lake cache: kept {kept} mappings with verified artifacts; dropped {removed} whose artifacts "
          f"are missing, so only those modules build from source", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
