# -*- coding: utf-8 -*-
"""把 Open Icecat 商品扩充到现有 Globex 商品召回评测框架。

本脚本只负责准备数据，不另写检索器或指标实现：生成的 catalog 仍由
``build_seed_products`` 加载，benchmark 仍由 ``run_product_recall.py`` 执行。

默认产物（均含 Icecat 授权数据，已由 .gitignore 排除）：

* ``data/icecat-catalog.jsonl``：现有 500 条目录 + 900 条 Icecat 商品；
* ``eval/icecat/private/product_recall-300.jsonl``：原 67 条 regression +
  233 条 Icecat candidate 标注；
* ``eval/icecat/private/build-manifest.json``：来源、规模和校验摘要。

API token 只从环境变量或项目根目录 .env 读取，不打印、不写入产物。
价格、库存、配送和评分不是 Icecat 提供的交易事实，脚本会以确定性方式生成并在
``evaluation_provenance`` 中明确标为 synthetic，避免误当线上商品数据。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval.icecat_preflight import ICECAT_API_URL, PROJECT_ROOT, _load_config


VERTICALS = {
    "2833": "数码配件",       # Computers & Peripherals
    "2830": "家居生活",       # Home
    "1960": "户外运动",       # Sports & Recreation
}
INDEX_URL = "https://data.icecat.biz/export/freexml/EN/{vertical_id}.vertical.files.index.xml.gz"
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "catalog-v1.jsonl"
DEFAULT_REGRESSION = PROJECT_ROOT / "eval" / "product_recall.jsonl"
DEFAULT_OUTPUT_CATALOG = PROJECT_ROOT / "data" / "icecat-catalog.jsonl"
DEFAULT_OUTPUT_BENCHMARK = (
    PROJECT_ROOT / "eval" / "icecat" / "private" / "product_recall-300.jsonl"
)
DEFAULT_MANIFEST = PROJECT_ROOT / "eval" / "icecat" / "private" / "build-manifest.json"
DEFAULT_CACHE = PROJECT_ROOT / "eval" / "icecat" / "cache"

_COUNTRY_CODES = {
    "china": "CN", "people's republic of china": "CN", "united states": "US",
    "united states of america": "US", "germany": "DE", "japan": "JP",
    "south korea": "KR", "republic of korea": "KR", "vietnam": "VN",
    "singapore": "SG", "united kingdom": "GB", "france": "FR", "italy": "IT",
    "netherlands": "NL", "taiwan": "TW", "poland": "PL", "spain": "ES",
}
_MATERIAL_TERMS = {
    "合成聚合物": ("plastic", "polycarbonate", "polyester", "nylon", "abs"),
    "金属": ("metal", "aluminium", "aluminum", "steel", "titanium"),
    "天然材质": ("wood", "bamboo", "cotton", "linen", "leather", "wool"),
    "玻璃": ("glass",),
    "陶瓷": ("ceramic", "porcelain"),
}


def _stable_int(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:16], 16)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records)
    path.write_text(text, encoding="utf-8")


def _download_index(vertical_id: str, token: str, cache_dir: Path) -> Path:
    target = cache_dir / f"{vertical_id}.vertical.files.index.xml.gz"
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(INDEX_URL.format(vertical_id=vertical_id), headers={"api-token": token})
    with urlopen(request, timeout=120) as response:
        payload = response.read()
    target.write_bytes(payload)
    return target


def _select_index_rows(path: Path, *, category: str, limit: int) -> list[dict[str, str]]:
    """全量扫描 vertical index，再用稳定哈希抽样，避免总取供应商排序前 N 条。"""
    candidates: list[dict[str, str]] = []
    with gzip.open(path, "rb") as stream:
        for _, element in ET.iterparse(stream, events=("end",)):
            if not element.tag.endswith("file"):
                continue
            row = dict(element.attrib)
            element.clear()
            if row.get("On_Market") != "1" or row.get("Limited") == "Yes":
                continue
            if not row.get("Product_ID") or not row.get("Model_Name"):
                continue
            row["globex_category"] = category
            candidates.append(row)
    candidates.sort(key=lambda row: (_stable_int(row["Product_ID"]), row["Product_ID"]))

    # 控制单一供应商占比；不足时再从剩余候选补齐。
    selected: list[dict[str, str]] = []
    supplier_counts: Counter[str] = Counter()
    supplier_cap = max(5, limit // 20)
    for row in candidates:
        supplier = row.get("Supplier_id", "")
        if supplier_counts[supplier] >= supplier_cap:
            continue
        selected.append(row)
        supplier_counts[supplier] += 1
        if len(selected) == limit:
            break
    if len(selected) < limit:
        selected_ids = {row["Product_ID"] for row in selected}
        selected.extend(row for row in candidates if row["Product_ID"] not in selected_ids)
    return selected[:limit]


def _select_vertical_rows(
    vertical_id: str, token: str, cache_dir: Path, *, category: str, limit: int,
) -> list[dict[str, str]]:
    """流式读取大索引，缓存最终抽样而不是下载整包。

    某些 vertical 索引非常大；为了 300 个评测样本下载完整索引既慢也没有额外价值。
    这里读取最多 ``max(limit*12, 3000)`` 个合格候选，再执行稳定哈希抽样和供应商限额。
    """
    selection_path = cache_dir / f"{vertical_id}.selected-{limit}.json"
    if selection_path.exists():
        rows = json.loads(selection_path.read_text(encoding="utf-8"))
        if isinstance(rows, list) and len(rows) == limit:
            return rows
    full_index = cache_dir / f"{vertical_id}.vertical.files.index.xml.gz"
    if full_index.exists() and full_index.stat().st_size > 0:
        rows = _select_index_rows(full_index, category=category, limit=limit)
    else:
        request = Request(INDEX_URL.format(vertical_id=vertical_id), headers={"api-token": token})
        candidates: list[dict[str, str]] = []
        pool_size = max(limit * 12, 3000)
        with urlopen(request, timeout=120) as response, gzip.GzipFile(fileobj=response) as stream:
            for _, element in ET.iterparse(stream, events=("end",)):
                if not element.tag.endswith("file"):
                    continue
                row = dict(element.attrib)
                element.clear()
                if row.get("On_Market") != "1" or row.get("Limited") == "Yes":
                    continue
                if not row.get("Product_ID") or not row.get("Model_Name"):
                    continue
                row["globex_category"] = category
                candidates.append(row)
                if len(candidates) >= pool_size:
                    break
        candidates.sort(key=lambda row: (_stable_int(row["Product_ID"]), row["Product_ID"]))
        rows = []
        supplier_counts: Counter[str] = Counter()
        supplier_cap = max(5, limit // 20)
        for row in candidates:
            supplier = row.get("Supplier_id", "")
            if supplier_counts[supplier] >= supplier_cap:
                continue
            rows.append(row)
            supplier_counts[supplier] += 1
            if len(rows) == limit:
                break
        if len(rows) < limit:
            selected_ids = {row["Product_ID"] for row in rows}
            rows.extend(row for row in candidates if row["Product_ID"] not in selected_ids)
            rows = rows[:limit]
    selection_path.parent.mkdir(parents=True, exist_ok=True)
    selection_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def _request_detail(row: dict[str, str], config: dict[str, str], cache_dir: Path) -> dict[str, Any]:
    icecat_id = row["Product_ID"]
    cache_path = cache_dir / "products" / f"{icecat_id}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    headers = {"api-token": config["api_token"], "Accept": "application/json"}
    if config.get("content_token"):
        headers["content-token"] = config["content_token"]
    params = {
        "lang": "EN", "shopname": config["username"], "icecat_id": icecat_id,
        "content": "essentialinfo,title,featuregroups",
    }
    request = Request(f"{ICECAT_API_URL}?{urlencode(params)}", headers=headers)
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("msg") not in (None, "OK") or not isinstance(payload.get("data"), dict):
                raise ValueError(f"Icecat business error: {payload.get('msg')}")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"Icecat {icecat_id} 下载失败：{type(last_error).__name__}")


def _flatten_features(data: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for group in data.get("FeaturesGroups", []):
        for item in group.get("Features", []):
            name = item.get("Feature", {}).get("Name", {}).get("Value", "")
            value = item.get("PresentationValue") or item.get("LocalValue") or item.get("Value") or ""
            name, value = str(name).strip(), str(value).strip()
            if name and value and value not in {"N/A", "-"}:
                result.append((name, value))
    return result


def _number(value: str) -> float | None:
    match = re.search(r"-?\d+(?:[.,]\d+)?", value.replace(",", "."))
    return float(match.group()) if match else None


def _metric(features: list[tuple[str, str]], names: tuple[str, ...], fallback: float) -> float:
    for name, value in features:
        if any(candidate in name.casefold() for candidate in names):
            amount = _number(value)
            if amount is None:
                continue
            folded = value.casefold()
            if " mm" in folded:
                amount /= 10
            elif " m" in folded and "mm" not in folded and "cm" not in folded:
                amount *= 100
            return max(amount, 0.01)
    return fallback


def _weight(features: list[tuple[str, str]], fallback: float) -> float:
    for name, value in features:
        if "weight" not in name.casefold():
            continue
        amount = _number(value)
        if amount is None:
            continue
        folded = value.casefold()
        if " g" in folded and "kg" not in folded:
            amount /= 1000
        return max(amount, 0.01)
    return fallback


def _normalize(row: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    data = payload["data"]
    essential = data.get("EssentialInfo", {})
    features = _flatten_features(data)
    feature_text = " ".join(f"{name}: {value}" for name, value in features)
    title = str(data.get("Title") or essential.get("ProductName") or row["Model_Name"]).strip()
    brand = str(essential.get("Brand") or f"Supplier-{row.get('Supplier_id', 'unknown')}").strip()
    product_code = str(essential.get("ProductCode") or row.get("Prod_ID") or row["Model_Name"]).strip()
    seed = _stable_int(row["Product_ID"])
    rng = random.Random(seed)
    materials = [tag for tag, terms in _MATERIAL_TERMS.items() if any(term in feature_text.casefold() for term in terms)]
    if not materials:
        materials = ["未标注"]
    origin = "UN"
    for name, value in features:
        if "country of origin" in name.casefold():
            origin = _COUNTRY_CODES.get(value.casefold(), "UN")
            break
    updated = row.get("Updated", "")[:8]
    updated_iso = f"{updated[:4]}-{updated[4:6]}-{updated[6:8]}" if len(updated) == 8 else "1970-01-01"
    ships = ["CN"]
    if seed % 2 == 0:
        ships.append("US")
    if seed % 3 == 0:
        ships.append("EU")
    if seed % 5 == 0:
        ships.append("SG")
    price = round(49 + (seed % 495000) / 100, 2)
    stock = 0 if seed % 10 == 0 else 5 + seed % 196
    highlights = [{"label": name, "detail": value} for name, value in features[:8]]
    description = "；".join(f"{name}: {value}" for name, value in features[:20])
    if not description:
        description = f"{brand} {title} {product_code}"
    fallback_dimension = 5 + rng.random() * 45
    record = {
        "product_id": f"ICECAT-{row['Product_ID']}",
        "title": title,
        "brand": brand,
        "category": row["globex_category"],
        "origin_country": origin,
        "description": description,
        "highlights": highlights,
        "ships_to": ships,
        "skus": [{
            "sku_id": f"ICECAT-{row['Product_ID']}-S1", "spec": product_code,
            "price_major": price, "currency": "CNY", "stock": stock,
        }],
        "source_platform": "icecat",
        "external_product_id": product_code,
        "canonical_product_id": f"ICECAT-CAN-{row['Product_ID']}",
        "material_tags": materials,
        "weight_kg": round(_weight(features, 0.1 + rng.random() * 4.9), 3),
        "dimensions_cm": {
            "length": round(_metric(features, ("depth", "length"), fallback_dimension), 2),
            "width": round(_metric(features, ("width",), fallback_dimension), 2),
            "height": round(_metric(features, ("height",), fallback_dimension), 2),
        },
        "tax_category": row["globex_category"],
        "rating_summary": {"average": round(3.5 + (seed % 15) / 10, 1), "review_count": 5 + seed % 996},
        "updated_at": updated_iso,
        "evaluation_tags": ["icecat_real_product", "synthetic_commerce_fields"],
        "evaluation_provenance": {
            "identity_title_features": "icecat",
            "price_stock_shipping_rating": "deterministic_synthetic",
            "icecat_id": row["Product_ID"],
            "vertical_category": row["globex_category"],
        },
    }
    return record


def _tokens(record: dict[str, Any]) -> set[str]:
    text = f"{record['brand']} {record['title']} {record['description']}".casefold()
    return set(re.findall(r"[a-z0-9][a-z0-9.+/-]{1,}|[\u4e00-\u9fff]{2,}", text))


def _hard_negative(record: dict[str, Any], candidates: list[dict[str, Any]]) -> str | None:
    own = _tokens(record)
    scored: list[tuple[float, str]] = []
    for other in candidates:
        if other["product_id"] == record["product_id"] or other["category"] != record["category"]:
            continue
        theirs = _tokens(other)
        union = own | theirs
        score = len(own & theirs) / len(union) if union else 0.0
        scored.append((score, other["product_id"]))
    scored.sort(reverse=True)
    return scored[0][1] if scored else None


def _build_icecat_cases(products: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    eligible = [record for record in products if record["skus"][0]["stock"] > 0]
    eligible.sort(key=lambda record: _stable_int(record["product_id"] + ":benchmark"))
    if len(eligible) < count:
        raise ValueError(f"可标注的在售 Icecat 商品不足：{len(eligible)} < {count}")
    chosen = eligible[:count]
    lexical_count = round(count * 0.38)
    constraint_start = round(count * 0.78)
    cases: list[dict[str, Any]] = []
    for index, record in enumerate(chosen):
        code = record["external_product_id"]
        brand = record["brand"]
        negative = _hard_negative(record, products)
        base = {
            "relevant": [record["product_id"]],
            "subset": "icecat_candidate",
            "annotation_status": "auto_derived_needs_review",
            "source": "open_icecat",
        }
        if negative:
            base["hard_negatives"] = [negative]
        if index < lexical_count:
            query = f"{brand} {code}"
            case = {**base, "query": query, "kind": "lexical", "scenario": "brand_model_lookup"}
        else:
            highlights = record.get("highlights", [])[:2]
            traits = " ".join(item["detail"] for item in highlights if item.get("detail"))
            traits = traits[:120] or record["title"]
            original = f"我想找{record['category']}，最好有这些特点：{traits}"
            rewritten = f"{record['category']} {brand} {code} {traits}"
            case = {
                **base, "query": rewritten, "original_query": original,
                "rewritten_query": rewritten, "rewrite_must_preserve": [record["category"]],
                "kind": "semantic", "scenario": "feature_need",
            }
        if index >= constraint_start:
            price = record["skus"][0]["price_major"]
            ship_to = record["ships_to"][0]
            constraint_text = f"可寄到 {ship_to}，预算不超过 {price + 1:.2f} CNY"
            case.update({
                "category": record["category"], "ship_to": ship_to,
                "price_max_major": round(price + 1, 2), "target_currency": "CNY",
                "require_in_stock": True, "scenario": "hard_constraint",
            })
            case.setdefault("rewrite_must_preserve", []).extend([record["category"], ship_to])
            case["original_query"] = f"{case.get('original_query', case['query'])}；{constraint_text}"
            case["rewritten_query"] = f"{case.get('rewritten_query', case['query'])} {constraint_text}"
            case["query"] = case["rewritten_query"]
        cases.append(case)
    return cases


def _validate(regression: list[dict[str, Any]], combined: list[dict[str, Any]], catalog: list[dict[str, Any]], target: int) -> list[str]:
    problems: list[str] = []
    if len(regression) != 67:
        problems.append(f"旧 regression 应为 67 条，实际 {len(regression)}")
    if len(combined) != target:
        problems.append(f"benchmark 应为 {target} 条，实际 {len(combined)}")
    for index, old in enumerate(regression):
        candidate = dict(combined[index])
        subset = candidate.pop("subset", None)
        if subset != "regression" or candidate != old:
            problems.append(f"旧 regression 第 {index + 1} 条未被原样保留")
            break
    product_ids = {record["product_id"] for record in catalog}
    for index, case in enumerate(combined, start=1):
        missing = set(case.get("relevant", [])) - product_ids
        if missing:
            problems.append(f"benchmark L{index} 引用了不存在商品：{sorted(missing)}")
        if set(case.get("relevant", [])) & set(case.get("hard_negatives", [])):
            problems.append(f"benchmark L{index} hard negative 与 relevant 重叠")
    icecat_count = max(0, target - len(regression))
    required_constraints = max(1, min(25, round(icecat_count * 0.20)))
    actual_constraints = sum(case.get("scenario") == "hard_constraint" for case in combined)
    if actual_constraints < required_constraints:
        problems.append(
            f"hard constraint 样本不足 {required_constraints} 条（实际 {actual_constraints}）",
        )
    return problems


def build(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_config(None)
    regression = _jsonl(args.regression)
    existing_catalog = _jsonl(args.base_catalog)
    per_vertical = args.icecat_products // len(VERTICALS)
    remainder = args.icecat_products % len(VERTICALS)
    selected_rows: list[dict[str, str]] = []
    for offset, (vertical_id, category) in enumerate(VERTICALS.items()):
        wanted = per_vertical + (1 if offset < remainder else 0)
        rows = _select_vertical_rows(
            vertical_id, config["api_token"], args.cache_dir,
            category=category, limit=wanted,
        )
        if len(rows) < wanted:
            raise RuntimeError(f"Icecat vertical {vertical_id} 只有 {len(rows)} 条合格商品，目标 {wanted}")
        selected_rows.extend(rows)
        print(f"  index {vertical_id}/{category}: selected {len(rows)}")

    details: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_rows = {
            executor.submit(_request_detail, row, config, args.cache_dir): row for row in selected_rows
        }
        completed = 0
        for future in concurrent.futures.as_completed(future_rows):
            row = future_rows[future]
            try:
                details[row["Product_ID"]] = future.result()
            except Exception as exc:  # noqa: BLE001 - 汇总失败后统一中止，不写半份金标
                failures.append(f"{row['Product_ID']}:{type(exc).__name__}")
            completed += 1
            if completed % 100 == 0 or completed == len(selected_rows):
                print(f"  details: {completed}/{len(selected_rows)}")
    if failures:
        raise RuntimeError(f"{len(failures)} 个 Icecat 商品下载失败；示例 {failures[:5]}")

    icecat_products = [_normalize(row, details[row["Product_ID"]]) for row in selected_rows]
    combined_catalog = existing_catalog + icecat_products
    icecat_case_count = args.benchmark_size - len(regression)
    if icecat_case_count <= 0:
        raise ValueError("benchmark_size 必须大于旧 regression 条数")
    icecat_cases = _build_icecat_cases(icecat_products, icecat_case_count)
    hard_negative_ids = {
        product_id
        for case in icecat_cases
        for product_id in case.get("hard_negatives", [])
    }
    for record in icecat_products:
        if record["product_id"] in hard_negative_ids:
            record["evaluation_tags"].append("hard_negative")
    combined_benchmark = [{**case, "subset": "regression"} for case in regression] + icecat_cases
    problems = _validate(regression, combined_benchmark, combined_catalog, args.benchmark_size)
    if problems:
        raise ValueError("数据自检失败：\n- " + "\n- ".join(problems))

    _write_jsonl(args.output_catalog, combined_catalog)
    _write_jsonl(args.output_benchmark, combined_benchmark)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_catalog_count": len(existing_catalog),
        "icecat_product_count": len(icecat_products),
        "combined_catalog_count": len(combined_catalog),
        "regression_count": len(regression),
        "icecat_candidate_count": len(icecat_cases),
        "combined_benchmark_count": len(combined_benchmark),
        "benchmark_kind_counts": dict(Counter(case.get("kind", "lexical") for case in combined_benchmark)),
        "scenario_counts": dict(Counter(case.get("scenario", "legacy") for case in combined_benchmark)),
        "vertical_counts": dict(Counter(record["category"] for record in icecat_products)),
        "outputs": {
            "catalog": str(args.output_catalog.relative_to(PROJECT_ROOT)),
            "benchmark": str(args.output_benchmark.relative_to(PROJECT_ROOT)),
        },
        "provenance_note": "Icecat identity/title/features are real; commerce fields are deterministic synthetic evaluation fixtures.",
        "validation": "passed",
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="构建 Icecat 商品召回扩展评测集")
    parser.add_argument("--base-catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--regression", type=Path, default=DEFAULT_REGRESSION)
    parser.add_argument("--output-catalog", type=Path, default=DEFAULT_OUTPUT_CATALOG)
    parser.add_argument("--output-benchmark", type=Path, default=DEFAULT_OUTPUT_BENCHMARK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--icecat-products", type=int, default=900)
    parser.add_argument("--benchmark-size", type=int, default=300)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    try:
        manifest = build(args)
    except (ValueError, RuntimeError, OSError, HTTPError, URLError) as exc:
        print(f"构建失败：{exc}")
        raise SystemExit(1) from exc
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("候选标注已生成；annotation_status=auto_derived_needs_review，正式门禁前仍需人工复核。")


if __name__ == "__main__":
    main()
