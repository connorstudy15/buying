from __future__ import annotations

import copy
import json
from scripts.eval.build_icecat_product_eval import (
    PROJECT_ROOT,
    _build_icecat_cases,
    _normalize,
)


def _payload(index: int) -> dict:
    return {
        "data": {
            "Title": f"Acme Trail Device {index}",
            "EssentialInfo": {
                "Brand": "Acme",
                "ProductCode": f"MODEL-{index:04d}",
                "ProductName": f"Trail Device {index}",
            },
            "FeaturesGroups": [{
                "Features": [
                    {
                        "PresentationValue": "Aluminium",
                        "Feature": {"Name": {"Value": "Material"}},
                    },
                    {
                        "PresentationValue": f"{100 + index} g",
                        "Feature": {"Name": {"Value": "Weight"}},
                    },
                ],
            }],
        },
    }


def _record(index: int) -> dict:
    return _normalize(
        {
            "Product_ID": str(900000 + index),
            "Prod_ID": f"MODEL-{index:04d}",
            "Model_Name": f"Trail Device {index}",
            "Supplier_id": str(index % 7),
            "Updated": "20260901000000",
            "globex_category": ["数码配件", "家居生活", "户外运动"][index % 3],
        },
        _payload(index),
    )


def test_normalized_icecat_record_separates_real_and_synthetic_fields():
    record = _record(1)
    assert record["source_platform"] == "icecat"
    assert record["title"] == "Acme Trail Device 1"
    assert record["material_tags"] == ["金属"]
    assert record["evaluation_provenance"]["identity_title_features"] == "icecat"
    assert record["evaluation_provenance"]["price_stock_shipping_rating"] == "deterministic_synthetic"


def test_generated_cases_cover_buckets_constraints_hard_negatives_and_rewrite_evidence():
    products = [_record(index) for index in range(160)]
    # Deterministic stock generation can mark 10% out of stock; 100 cases remain available.
    cases = _build_icecat_cases(products, 100)
    assert len(cases) == 100
    assert {case["kind"] for case in cases} == {"lexical", "semantic"}
    assert sum(case["scenario"] == "hard_constraint" for case in cases) >= 20
    assert all(case.get("hard_negatives") for case in cases)
    constrained = [case for case in cases if case["scenario"] == "hard_constraint"]
    assert all(case["ship_to"] in case["rewritten_query"] for case in constrained)
    assert all(case["category"] in case["rewrite_must_preserve"] for case in constrained)


def test_original_67_remain_exact_regression_prefix():
    path = PROJECT_ROOT / "eval" / "product_recall.jsonl"
    regression = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(regression) == 67
    combined = [{**copy.deepcopy(case), "subset": "regression"} for case in regression]
    for old, copied in zip(regression, combined, strict=True):
        assert copied.pop("subset") == "regression"
        assert copied == old
