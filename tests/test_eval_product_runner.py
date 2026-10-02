# -*- coding: utf-8 -*-
"""正式商品评测运行器的结构化槽位回归。"""
from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.domain.catalog.money import Money
from app.domain.catalog.product import Product
from app.domain.catalog.sku import Sku
from app.infrastructure.persistence.in_memory_repositories import InMemoryProductRepository
from scripts.eval.run_product_recall import by_dimension, check_rewrite_drift, run_dataset


async def test_formal_runner_passes_category_to_search_spec():
    """评测样本声明的品类槽位必须真正进入搜索链路。"""
    repo = InMemoryProductRepository(
        [
            Product(
                product_id="P-OTHER", title="家居露营灯", brand="A", category="家居生活", origin_country="CN",
                description="露营灯", ships_to=["CN"],
                skus=[Sku("P-OTHER-S1", "标准", Money.from_major_units(50, "CNY"), 5)],
            ),
            Product(
                product_id="P-OUTDOOR", title="户外露营灯", brand="B", category="户外运动", origin_country="CN",
                description="露营灯", ships_to=["CN"],
                skus=[Sku("P-OUTDOOR-S1", "标准", Money.from_major_units(50, "CNY"), 5)],
            ),
        ],
    )
    cases = [{
        "query": "露营灯", "kind": "composite", "category": "户外运动", "target_currency": "CNY",
        "relevant": ["P-OUTDOOR"], "template_family": "category-slot",
    }]

    aggregate = await run_dataset(CatalogSearchUseCase(repo), repo, cases, top_k=1)

    assert aggregate.recall == 1.0
    assert aggregate.mrr == 1.0


async def test_formal_runner_scores_cross_platform_duplicates_by_canonical_entity():
    """同款跨平台候选不能靠重复 product_id 改变检索指标。"""
    repo = InMemoryProductRepository(
        [
            Product(
                product_id="P-A", title="同款露营灯 A", brand="A", category="户外运动", origin_country="CN",
                description="露营灯", ships_to=["CN"], canonical_product_id="CAN-LAMP",
                skus=[Sku("P-A-S1", "标准", Money.from_major_units(50, "CNY"), 5)],
            ),
            Product(
                product_id="P-B", title="同款露营灯 B", brand="B", category="户外运动", origin_country="US",
                description="露营灯", ships_to=["CN"], canonical_product_id="CAN-LAMP",
                skus=[Sku("P-B-S1", "标准", Money.from_major_units(60, "CNY"), 5)],
            ),
        ],
    )
    cases = [{
        "query": "露营灯", "kind": "literal", "target_currency": "CNY", "relevant": ["P-A"],
        "relevant_canonical_ids": ["CAN-LAMP"], "template_family": "canonical-entity",
    }]

    aggregate = await run_dataset(CatalogSearchUseCase(repo), repo, cases, top_k=2)

    assert aggregate.precision == 1.0
    assert aggregate.canonical_duplicate_rate == 0.5


async def test_formal_runner_keeps_split_and_constraint_dimensions_for_reports():
    repo = InMemoryProductRepository([
        Product(
            product_id="P-DIM", title="露营灯", brand="A", category="户外运动", origin_country="CN",
            description="露营灯", ships_to=["US"], material_tags=["金属"],
            skus=[Sku("P-DIM-S1", "标准", Money.from_major_units(10, "USD"), 5)],
        ),
    ])
    cases = [{
        "query": "露营灯", "kind": "composite", "split": "release", "category": "户外运动",
        "ship_to": "US", "target_currency": "USD", "required_material_tags": ["金属"],
        "relevant": ["P-DIM"], "relevant_canonical_ids": ["P-DIM"], "template_family": "dimensions",
    }]

    aggregate = await run_dataset(CatalogSearchUseCase(repo), repo, cases, top_k=1)

    assert by_dimension(aggregate, "split")["release"].count == 1
    assert by_dimension(aggregate, "target_currency")["USD"].count == 1
    assert by_dimension(aggregate, "ship_to")["US"].count == 1


def test_rewrite_drift_protects_explicit_terms_and_stable_ids():
    case = {
        "query": "轻便耳机 P12345",
        "original_query": "不要塑料，比较 P12345",
        "rewritten_query": "轻便耳机 P12345",
        "rewrite_must_preserve": ["不要塑料"],
    }

    drift, note = check_rewrite_drift(case)

    assert drift is True
    assert "不要塑料" in note
    assert "P12345" not in note


async def test_runner_records_latency_and_zero_constraint_violations():
    repo = InMemoryProductRepository([
        Product(
            product_id="P-METRIC", title="金属露营灯", brand="A", category="户外运动", origin_country="CN",
            description="金属露营灯", ships_to=["CN"], material_tags=["金属"],
            skus=[Sku("P-METRIC-S1", "标准", Money.from_major_units(50, "CNY"), 5)],
        ),
    ])
    cases = [{
        "query": "金属露营灯", "original_query": "我要金属露营灯", "rewritten_query": "金属露营灯",
        "rewrite_must_preserve": ["金属"], "category": "户外运动", "required_material_tags": ["金属"],
        "relevant": ["P-METRIC"],
    }]

    aggregate = await run_dataset(CatalogSearchUseCase(repo), repo, cases, top_k=1)

    assert aggregate.latency_count == 1
    assert aggregate.latency_p95_ms is not None
    assert aggregate.hard_constraint_violation_rate == 0.0
    assert aggregate.rewrite_drift_rate == 0.0


async def test_runner_attributes_a_candidate_hit_removed_before_final_top_k():
    product = Product(
        product_id="P-CANDIDATE", title="目标露营灯", brand="A", category="户外运动",
        origin_country="CN", description="目标露营灯", ships_to=["CN"],
        skus=[Sku("P-CANDIDATE-S1", "标准", Money.from_major_units(50, "CNY"), 5)],
    )
    repo = InMemoryProductRepository([product])

    class ObservedUseCase:
        async def execute(self, spec):
            return {
                "hits": [], "filtered_out": [], "recall_strategy": "embedding_rerank",
                "rerank_applied": True,
                "retrieval_evidence": {
                    "candidate_product_ids": ["P-CANDIDATE"],
                    "candidate_metric_depth": 8,
                    "post_rank_product_ids": [],
                    "final_product_ids": [],
                },
            }

    aggregate = await run_dataset(
        ObservedUseCase(), repo,
        [{"query": "目标露营灯", "kind": "semantic", "relevant": ["P-CANDIDATE"]}],
        top_k=8,
    )

    assert aggregate.candidate_recall == 1.0
    assert aggregate.recall == 0.0
    assert aggregate.miss_stage_counts["rerank_miss"] == 1
