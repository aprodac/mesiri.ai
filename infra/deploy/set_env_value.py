#!/usr/bin/env python3
"""Set one KEY=value line in an env file, the value read from stdin (SA-16).

Used by .github/workflows/deploy.yml to put a GitHub secret into
/opt/mesiri/.env without the value ever appearing in a command line or a
log. Replaces the key's line if present, appends it otherwise; keeps the
file's mode. Prints only whether it changed.

    printf '%s' "$VALUE" | python3 set_env_value.py /opt/mesiri/.env MESIRI_CLAUDE_OPS_TOKEN
"""

from __future__ import annotations

import os
import re
import sys


def main() -> None:
    path, key = sys.argv[1], sys.argv[2]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
        sys.exit(f"bad key {key!r}")
    value = sys.stdin.read().strip()
    if not value or "\n" in value:
        sys.exit("empty or multi-line value; nothing changed")
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    line = f"{key}={value}"
    found = [i for i, existing in enumerate(lines) if existing.split("=", 1)[0].strip() == key]
    if found and all(lines[i] == line for i in found):
        print(f"{key}: unchanged")
        return
    lines = [existing for i, existing in enumerate(lines) if i not in found] + [line]
    mode = os.stat(path).st_mode
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    print(f"{key}: {'updated' if found else 'added'}")


if __name__ == "__main__":
    main()
