"""Verify imported data, identity/search compatibility and historical lookup isolation."""
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.domain.catalog.product_search_spec import ProductSearchSpec
from app.infrastructure.persistence.in_memory_repositories import InMemoryProductRepository
from app.infrastructure.persistence.seed_products import build_seed_products, _CATALOG_FIXTURE
from scripts.build_abo_demo_catalog import classify

CATALOG = Path(__file__).resolve().parents[1] / "data/catalog-abo-demo.jsonl"


def test_imported_catalog_has_bounded_categories_and_honest_metadata():
    records = [json.loads(line) for line in CATALOG.read_text(encoding="utf-8").splitlines()]
    assert len(records) == len({p["product_id"] for p in records}) == 720
    assert len({p["skus"][0]["sku_id"] for p in records}) == 720
    assert set(Counter(p["category"] for p in records).values()) == {30}
    assert len({p["category"] for p in records}) == 24
    assert len(build_seed_products(_CATALOG_FIXTURE)) == 3700
    for record in records:
        provenance = json.loads(record["data_provenance"])
        assert record["origin_country"] == ""
        assert record["price_kind"] == provenance["price_kind"] == "demo"
        assert provenance["price_basis"] == "operator_estimate_not_market_calibrated"
        assert provenance["inventory_kind"] == provenance["shipping_kind"] == "simulated"
        low, high = provenance["price_band_cny"]
        assert low <= record["skus"][0]["price_major"] <= high
        assert record["image_url"].startswith("https://amazon-berkeley-objects.s3.amazonaws.com/images/small/")
        assert record["rating_summary"] is None and not record["updated_at"]
        ProductSearchSpec(product_id=record["product_id"], sku_id=record["skus"][0]["sku_id"])


@pytest.mark.parametrize(("kind", "category"), [
    ("PORTABLE_AUDIO", "数码电脑"), ("EDIBLE_OIL_VEGETABLE", "食品饮料"),
    ("STEERING_WHEEL_COVER", "汽车用品"), ("SHEET_PAN", "厨房餐具"),
    ("PAINT_BRUSH", "五金工具"), ("WASHER_DRYER_COMBINATION", "家用电器"),
    ("WRITING_INSTRUMENT", "办公文具"), ("NON_RIDING_TOY_VEHICLE", "玩具游戏"),
])
def test_ambiguous_source_types_have_explicit_categories(kind, category):
    assert classify(kind)[0] == category


async def test_catalog_can_search_each_category_and_resolve_long_ids(monkeypatch):
    monkeypatch.setenv("PRODUCT_CATALOG_PATH", str(CATALOG))
    repo = InMemoryProductRepository()
    products = await repo.list_all()
    assert len(products) == 720
    assert await repo.find_by_id("P1014") is not None  # historical order compatibility
    assert await repo.find_by_ids(["P1014"]) == []  # old vectors cannot reintroduce old catalog
    usecase = CatalogSearchUseCase(repo)
    for category in {p.category for p in products}:
        result = await usecase.execute(ProductSearchSpec(normalized_query=category, category=category))
        assert result["hits"], category
        assert all(h["category"] == category and h["price_kind"] == "demo" for h in result["hits"])
    product = products[0]
    exact = await usecase.execute(ProductSearchSpec(sku_id=product.primary_sku().sku_id))
    assert exact["hits"][0]["product_id"] == product.product_id
    assert exact["hits"][0]["image_kind"] == "catalog_photo"


async def test_imported_catalog_vectors_persist_and_reuse_without_paid_calls(tmp_path):
    from app.infrastructure.vector.index_bootstrap import bootstrap_product_index
    from app.infrastructure.vector.qdrant_product_index import QdrantProductIndex
    from tests.test_product_vector_persistence import CountingEmbedding
    from tests.test_retrieval import _settings

    repo = InMemoryProductRepository(build_seed_products(CATALOG))
    settings = replace(_settings(tmp_path), qdrant_collection="globex_products_abo_demo_v1")
    index = QdrantProductIndex(settings)
    embedder = CountingEmbedding()
    try:
        assert await bootstrap_product_index(repo, embedder, index, batch_size=30)
        assert sum(map(len, embedder.batches)) == 720
    finally:
        await index.close()
    restarted = QdrantProductIndex(settings)
    try:
        offline = CountingEmbedding(fail_batch=1)
        assert await bootstrap_product_index(repo, offline, restarted)
        assert offline.batches == []
        assert len(await restarted.search([1, 0.25, 0.5], 5)) == 5
    finally:
        await restarted.close()


async def test_each_category_can_confirm_once_and_cancel_in_isolated_sqlite(tmp_path):
    from app.application.usecases.confirmation_service import ConfirmationService
    from app.application.usecases.order_usecases import OrderItemInput
    from app.domain.order.address import Address
    from app.infrastructure.persistence.sql.repositories import bootstrap_schema, create_engine
    from app.infrastructure.persistence.sql.trade_store import SqlTradeStore

    products = build_seed_products(CATALOG)
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'abo-trade.db'}")
    store = SqlTradeStore(engine)
    service = ConfirmationService(InMemoryProductRepository(products), store)
    address = Address("演示用户", "CN", "测试省", "测试市", "虚构测试地址", "000000", "00000000000")
    try:
        await bootstrap_schema(engine)
        await store.initialize_inventory(products)
        for category in {p.category for p in products}:
            product = next(p for p in products if p.category == category)
            sku = product.primary_sku()
            prepared = await service.prepare_order("test-buyer", "test-session", [OrderItemInput(product.product_id, sku.sku_id, 1)], address)
            assert (await store.get_inventory([sku.sku_id]))[sku.sku_id] == 20
            confirmation = prepared["confirmation"]
            args = dict(confirmation_id=confirmation["confirmation_id"], buyer_id="test-buyer", session_id="test-session", snapshot_hash=confirmation["snapshot_hash"], approved=True)
            approved = await service.resolve(**args)
            assert approved == await service.resolve(**args)
            assert approved["order"]["status"] == "CONFIRMED"
            assert (await store.get_inventory([sku.sku_id]))[sku.sku_id] == 19
            cancel = await service.prepare_cancel("test-buyer", "test-session", approved["order"]["order_id"], "演示回归")
            confirmation = cancel["confirmation"]
            await service.resolve(confirmation_id=confirmation["confirmation_id"], buyer_id="test-buyer", session_id="test-session", snapshot_hash=confirmation["snapshot_hash"], approved=True)
            assert (await store.get_inventory([sku.sku_id]))[sku.sku_id] == 20
    finally:
        await engine.dispose()
