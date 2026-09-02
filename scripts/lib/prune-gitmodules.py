#!/usr/bin/env python3
"""Prune a mirrored .gitmodules down to the entries in catalog/keep.txt.

    python3 scripts/lib/prune-gitmodules.py <.gitmodules> <keep.txt>

Rewrites the file in place. Called by scripts/mirror-catalogue.sh.

WHY THIS EXISTS

The marketplace comes from a fork whose contents are curated by
`scripts/curate-catalogue.sh`, which needs push access to that fork. Filtering
here as well makes `catalog/keep.txt` authoritative regardless of whether the
fork has caught up, so removing a module from the marketplace is a one-line
edit plus a mirror refresh rather than a push to another repository.

It only ever *removes*. An entry in keep.txt that the fork does not carry is
reported and ignored — inventing a submodule stanza would produce a card whose
metadata could never be fetched.
"""

import configparser
import sys


def read_keep(path: str) -> list[str]:
    names = []
    for line in open(path, encoding="utf-8"):
        line = line.split("#")[0].strip()
        if line:
            names.append(line)
    return names


def main() -> int:
    gitmodules, keep_file = sys.argv[1], sys.argv[2]
    keep = set(read_keep(keep_file))

    cfg = configparser.ConfigParser()
    cfg.read_string(open(gitmodules, encoding="utf-8").read())

    kept, dropped = [], []
    out = []
    for section in cfg.sections():
        items = dict(cfg.items(section))
        name = items.get("path")
        if name in keep:
            kept.append(name)
            body = "".join(f"\t{k} = {v}\n" for k, v in items.items())
            out.append(f"[{section}]\n{body}")
        else:
            dropped.append(name)

    missing = sorted(keep - set(kept))
    if missing:
        # Not fatal: keep.txt is a wish list, the fork is the source of truth
        # for what exists. Saying so beats silently serving fewer modules.
        print(f"  [warn] in keep.txt but not in the catalogue: {missing}")

    if not kept:
        print("  [FAIL] pruning would leave the marketplace empty — refusing")
        return 1

    with open(gitmodules, "w", encoding="utf-8") as f:
        f.write("".join(out))

    if dropped:
        print(f"  [ ok ] pruned to keep.txt, dropped: {sorted(dropped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
