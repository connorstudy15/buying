"""Select at most 30 distinct listings per source product type; never import live data.

Input: official archives/abo-listings.tar. Output: raw sample, category counts,
license and provenance. Monetary, stock and shipping fields remain unassigned.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import json
import tarfile
from pathlib import Path


def values(row: dict, field: str) -> list[str]:
    raw = row.get(field) or []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    return [str(v["value"]).strip() for v in raw if isinstance(v, dict) and v.get("value")]


def kind_of(row: dict) -> str:
    kinds = values(row, "product_type")
    return kinds[0] if kinds else "UNKNOWN"


def priority(row: dict) -> tuple:
    langs = {v.get("language_tag", "") for v in row.get("item_name", []) if isinstance(v, dict)}
    fields = ("brand", "material", "bullet_point", "product_description", "item_dimensions", "item_weight")
    completeness = sum(bool(row.get(field)) for field in fields)
    return (
        -completeness,
        -int("zh_CN" in langs),
        -int("en_US" in langs),
        -int(row.get("country") == "US"),
        str(row.get("item_id", "")),
        str(row.get("domain_name", "")),
    )


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--per-category", type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.per_category <= 30:
        parser.error("--per-category must be between 1 and 30")
    if args.output.exists():
        parser.error("output directory already exists; choose a new destination")

    counts = collections.Counter()
    eligible = collections.Counter()
    candidates: dict[str, dict[tuple[str, str], dict]] = collections.defaultdict(dict)
    seen = set()
    total = rejected = duplicates = 0
    license_text = None
    with tarfile.open(args.archive) as archive:
        for member in archive:
            if member.isfile() and member.name.endswith("LICENSE-CC-BY-4.0.txt"):
                license_text = archive.extractfile(member).read()
            if not member.isfile() or not member.name.endswith(".json.gz"):
                continue
            with gzip.GzipFile(fileobj=archive.extractfile(member)) as stream:
                for line in stream:
                    row = json.loads(line)
                    total += 1
                    kind = kind_of(row)
                    counts[kind] += 1
                    identity = (str(row.get("item_id", "")), str(row.get("domain_name", "")))
                    if identity in seen:
                        duplicates += 1
                        continue
                    seen.add(identity)
                    if (
                        not all(identity) or kind == "UNKNOWN"
                        or not values(row, "item_name") or not row.get("main_image_id")
                        or not any(row.get(f) for f in ("bullet_point", "product_description", "material", "item_dimensions"))
                    ):
                        rejected += 1
                        continue
                    eligible[kind] += 1
                    pool = candidates[kind]
                    pool[identity] = row
                    # Bound memory while retaining a larger pool for brand diversity.
                    if len(pool) > args.per_category * 4:
                        worst = max(pool, key=lambda key: priority(pool[key]))
                        del pool[worst]

    if license_text is None:
        raise ValueError("official archive license is missing")
    selected: dict[str, list[dict]] = {}
    for kind, pool in sorted(candidates.items()):
        brands: dict[str, list[dict]] = collections.defaultdict(list)
        for row in sorted(pool.values(), key=priority):
            brands["|".join(values(row, "brand")).casefold()].append(row)
        result = []
        titles_seen = set()
        queues = list(brands.values())
        while queues and len(result) < args.per_category:
            remaining = []
            for queue in queues:
                if not queue or len(result) == args.per_category:
                    break
                row = queue.pop(0)
                # Drop exact multilingual title duplicates within a type, even across markets.
                title_key = tuple(sorted({" ".join(v.casefold().split()) for v in values(row, "item_name")}))
                if title_key not in titles_seen:
                    titles_seen.add(title_key)
                    result.append(row)
                if queue:
                    remaining.append(queue)
            queues = remaining
        if result:
            selected[kind] = result

    args.output.mkdir(parents=True)
    sample = args.output / "abo-sample.jsonl"
    with sample.open("w", encoding="utf-8", newline="\n") as dest:
        for rows in selected.values():
            for row in rows:
                dest.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output / "category-counts.csv").open("w", encoding="utf-8-sig", newline="") as dest:
        writer = csv.writer(dest)
        writer.writerow(["source_product_type", "raw_listings", "eligible_listings", "selected_listings"])
        for kind in sorted(counts):
            writer.writerow([kind, counts[kind], eligible[kind], len(selected.get(kind, []))])
    (args.output / "LICENSE-CC-BY-4.0.txt").write_bytes(license_text)
    summary = {
        "source": "https://amazon-berkeley-objects.s3.amazonaws.com/index.html",
        "archive_sha256": sha256_file(args.archive),
        "sample_sha256": sha256_file(sample),
        "license": "CC-BY-4.0",
        "raw_listings": total,
        "source_product_types": len(counts),
        "eligible_product_types": len(eligible),
        "selected_product_types": len(selected),
        "selected_listings": sum(map(len, selected.values())),
        "per_type_cap": args.per_category,
        "rejected_listings": rejected,
        "duplicate_marketplace_ids": duplicates,
        "important": [
            "Source product types include generic and overlapping labels, not a clean retail taxonomy.",
            "Source marketplace country is not manufacturing origin or shipping eligibility.",
            "Price, stock and shipping rules have not been fabricated or assigned.",
            "No live catalog, database or server was modified.",
        ],
    }
    (args.output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "ATTRIBUTION.md").write_text(
        "# Amazon Berkeley Objects sample\n\n"
        "Data © Amazon.com. Dataset builders: Matthieu Guillaumin, Thomas Dideriksen, "
        "Kenan Deng, Himanshu Arora, Jasmine Collins and Jitendra Malik.\n\n"
        "Source: https://amazon-berkeley-objects.s3.amazonaws.com/index.html\n\n"
        "License: https://creativecommons.org/licenses/by/4.0/\n\n"
        "Changes: filtered and sampled listings, at most 30 per source product type; "
        "original record fields preserved. No endorsement is implied.\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
