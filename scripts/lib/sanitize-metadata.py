"""Make the catalogue mirror's metadata name this platform, not another project.

    python3 scripts/lib/sanitize-metadata.py catalog/mirror/**/ai4-metadata.yml

Run by scripts/mirror-catalogue.sh after every fetch. Idempotent: a clean file
is left byte-for-byte alone. Edits lines rather than re-dumping the YAML, so a
refreshed mirror's diff shows only what changed upstream and what this changed.

  tags        every "vo.<name>" tag is dropped. Upstream tags modules with the
              Virtual Organisation that funds them, and `vo.imagine-ai.eu` on
              our marketplace names a marine-science project as the owner of a
              model a clinician is reading about.
  categories  NOT touched, and must not be. The AI4OS metadata schema
              enumerates them ("AI4 trainable", "AI4 pre trained", ...), PAPI
              validates every entry against it, and one renamed category makes
              the whole entry invalid: measured 2026-09-28, all eight modules
              served as "invalid metadata", titled by their ids. Their chips
              are relabelled at display time instead, by dashboard patch 0017.
  title       "AI4OS Development Environment" -> "Development Environment".

The result is checked by parsing both versions and comparing them with the
intended transformation, so an edit that damaged the YAML fails here rather
than as a marketplace that PAPI cannot parse.
"""

import re
import sys

import yaml

CATEGORIES = {}  # see the docstring: the schema owns these
TITLES = {"AI4OS Development Environment": "Development Environment"}
ITEM = re.compile(r"^(\s*-\s*)(['\"]?)(.*?)\2\s*$")


def expected(doc):
    doc = dict(doc)
    if isinstance(doc.get("tags"), list):
        doc["tags"] = [t for t in doc["tags"] if not str(t).startswith("vo.")]
    if isinstance(doc.get("categories"), list):
        doc["categories"] = [CATEGORIES.get(c, c) for c in doc["categories"]]
    if doc.get("title") in TITLES:
        doc["title"] = TITLES[doc["title"]]
    return doc


def sanitise(text):
    out, block = [], None
    for line in text.splitlines(keepends=True):
        top = re.match(r"^([A-Za-z_][\w-]*):", line)
        if top:
            block = top.group(1)
            m = re.match(r"^title:\s*(['\"]?)(.*?)\1\s*$", line)
            if m and m.group(2) in TITLES:
                line = f"title: {TITLES[m.group(2)]}\n"
        else:
            item = ITEM.match(line)
            if item and block == "tags" and item.group(3).startswith("vo."):
                continue
            if item and block == "categories" and item.group(3) in CATEGORIES:
                line = f"{item.group(1)}{CATEGORIES[item.group(3)]}\n"
        out.append(line)
    return "".join(out)


def main(paths):
    changed = 0
    for path in paths:
        before = open(path, encoding="utf-8").read()
        after = sanitise(before)
        if after == before:
            continue
        if yaml.safe_load(after) != expected(yaml.safe_load(before)):
            sys.exit(f"{path}: sanitising changed more than it should — left untouched")
        open(path, "w", encoding="utf-8").write(after)
        changed += 1
        print(f"  sanitised {path}")
    print(f"  {changed} of {len(paths)} metadata files needed sanitising")


if __name__ == "__main__":
    main(sys.argv[1:])
