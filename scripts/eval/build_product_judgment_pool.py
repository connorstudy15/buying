# -*- coding: utf-8 -*-
"""为旧 67 条商品 Query 构建多策略 pooled-judgment 候选集。

只复用真实 ``CatalogSearchUseCase``，不生成相关性答案。输出会隐藏策略排名之外的
系统结论，供独立 judge 对 ``query × product`` 逐项标 grade/eligible/hard-negative。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.domain.catalog.product_search_spec import ProductSearchSpec  # noqa: E402
from app.infrastructure.persistence.seed_products import build_seed_products  # noqa: E402
from scripts.eval.run_product_recall import build_usecase, load_dataset  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = ROOT / "eval" / "product_recall.jsonl"
DEFAULT_CATALOG = ROOT / "data" / "catalog-v1.jsonl"
DEFAULT_OUTPUT = ROOT / "eval" / "product_recall_candidates.jsonl"
STRATEGIES = ("keyword_2gram", "bm25", "embedding_only")


def _product_fact(product: Any) -> dict[str, Any]:
    prices = [sku.price.to_major_units() for sku in product.skus]
    currencies = sorted({sku.price.currency for sku in product.skus})
    return {
        "product_id": product.product_id,
        "title": product.title,
        "brand": product.brand,
        "category": product.category,
        "origin_country": product.origin_country,
        "description": product.description,
        "highlights": [
            {"label": item.label, "detail": item.detail} for item in product.highlights
        ],
        "material_tags": list(product.material_tags),
        "ships_to": list(product.ships_to),
        "price_min": min(prices) if prices else None,
        "price_max": max(prices) if prices else None,
        "currencies": currencies,
        "in_stock": any(sku.stock > 0 for sku in product.skus),
    }


async def build_pool(
    dataset: Path, catalog: Path, output: Path, *, top_n: int,
) -> list[dict[str, Any]]:
    cases = load_dataset(dataset)
    products = build_seed_products(catalog)
    products_by_id = {product.product_id: product for product in products}
    rankings: dict[str, dict[int, list[str]]] = defaultdict(dict)
    actual_strategies: dict[str, str] = {}

    for strategy in STRATEGIES:
        print(f"[{strategy}] 构建真实检索链路……", flush=True)
        usecase, _, _ = await build_usecase(strategy, catalog)
        for index, case in enumerate(cases):
            # Pooling 阶段故意不施加硬约束：语义相似但违反约束的商品正是重要 hard negative。
            payload = await usecase.execute(ProductSearchSpec(
                normalized_query=case["query"], top_k=top_n,
            ))
            rankings[strategy][index] = [hit["product_id"] for hit in payload.get("hits", [])]
            actual_strategies[strategy] = str(payload.get("recall_strategy", "unknown"))

    rows: list[dict[str, Any]] = []
    for index, case in enumerate(cases):
        sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
        candidate_ids: list[str] = []
        for strategy in STRATEGIES:
            for rank, product_id in enumerate(rankings[strategy][index], start=1):
                sources[product_id].append({"strategy": strategy, "rank": rank})
                if product_id not in candidate_ids:
                    candidate_ids.append(product_id)
        for product_id in [*case.get("relevant", []), *case.get("hard_negatives", [])]:
            if product_id not in candidate_ids:
                candidate_ids.append(product_id)
            sources[product_id].append({"strategy": "existing_annotation", "rank": None})

        candidates = []
        for product_id in candidate_ids:
            product = products_by_id.get(product_id)
            if product is None:
                continue
            candidates.append({
                **_product_fact(product),
                "retrieved_by": sources[product_id],
                "judgment": None,
            })
        rows.append({
            "query_id": f"PR-{index + 1:03d}",
            "query": case["query"],
            "kind": case.get("kind", "lexical"),
            "constraints": {
                key: case[key] for key in (
                    "category", "price_max_major", "ship_to", "target_currency",
                    "excluded_material_tags", "required_material_tags", "require_in_stock",
                ) if key in case
            },
            "existing_relevant": list(case.get("relevant", [])),
            "candidate_count": len(candidates),
            "candidates": candidates,
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = output.with_suffix(".manifest.json")
    manifest.write_text(json.dumps({
        "dataset": str(dataset), "catalog": str(catalog), "query_count": len(rows),
        "top_n_per_strategy": top_n, "requested_strategies": list(STRATEGIES),
        "actual_strategies": actual_strategies,
        "candidate_pairs": sum(row["candidate_count"] for row in rows),
        "note": "unjudged pool; judgment must be independent of retrieved_by ranks",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser(description="构建商品相关性 pooled-judgment 候选集")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--top-n", type=int, default=8)
    args = parser.parse_args()
    rows = await build_pool(args.dataset, args.catalog, args.output, top_n=args.top_n)
    counts = [row["candidate_count"] for row in rows]
    print(
        f"完成：{len(rows)} queries，{sum(counts)} query-product pairs，"
        f"每题候选 min/avg/max={min(counts)}/{sum(counts)/len(counts):.1f}/{max(counts)}",
    )


if __name__ == "__main__":
    asyncio.run(main())
