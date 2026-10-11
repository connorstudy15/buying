import copy
import json

from app.application.usecases.catalog_search import CatalogSearchUseCase
from app.application.tools.product_search_tool import build_product_search_tool
from app.domain.catalog.product_search_spec import ProductSearchSpec
from app.infrastructure.persistence.in_memory_repositories import InMemoryProductRepository
from app.infrastructure.eventbus import TradeEventBus


async def test_full_title_resolves_authoritative_entity_without_fuzzy_recall():
    usecase = CatalogSearchUseCase(InMemoryProductRepository())
    result = await usecase.execute(ProductSearchSpec(normalized_query="Atlas 宠物出行包 263", ship_to="EU"))
    assert result["recall_strategy"] == "exact_id_lookup"
    assert [card["product_id"] for card in result["hits"]] == ["P2263"]


async def test_partial_titles_and_numeric_suffixes_are_not_entity_keys():
    usecase = CatalogSearchUseCase(InMemoryProductRepository())
    for query in ("263", "Atlas 宠物出行包", "Atlas 宠物出行包 263 便宜一点"):
        assert await usecase.resolve_exact_title(query) is None


async def test_duplicate_full_titles_remain_ambiguous():
    repo = InMemoryProductRepository()
    first = await repo.find_by_id("P2263")
    second = copy.deepcopy(first)
    second.product_id = "P9999"
    usecase = CatalogSearchUseCase(InMemoryProductRepository([first, second]))
    assert await usecase.resolve_exact_title(first.title) is None


async def test_full_title_still_obeys_explicit_material_constraints():
    usecase = CatalogSearchUseCase(InMemoryProductRepository())
    result = await usecase.execute(ProductSearchSpec(normalized_query="Atlas 宠物出行包 263", required_material_tags=["不存在的材料"]))
    assert result["hits"] == []


async def test_numeric_identifier_requires_matching_verified_full_title():
    tool = build_product_search_tool(CatalogSearchUseCase(InMemoryProductRepository()), TradeEventBus())
    response = await tool(product_id="263", normalized_query="Atlas 宠物出行包 263", ship_to="EU")
    assert json.loads(response.content[0].text)["hits"][0]["product_id"] == "P2263"
    for query in ("263", "Atlas 宠物出行包", "Atlas 宠物出行包 287"):
        rejected = await tool(product_id="263", normalized_query=query)
        assert "[error]" in rejected.content[0].text
