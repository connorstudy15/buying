"""小目录 BM25：保留词频，英文型号完整匹配，中文二元词项。"""
from __future__ import annotations
from collections import Counter
import math
import re


def terms(text: str) -> list[str]:
    value = text.casefold()
    tokens = re.findall(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*", value)
    for segment in re.findall(r"[\u4e00-\u9fff]+", value):
        tokens.extend(segment[i:i+2] for i in range(len(segment)-1))
        if len(segment) == 1:
            tokens.append(segment)
    return tokens


def bm25_rank(query: str, products: list, *, k1: float = 1.2, b: float = .75) -> list[tuple[float, object]]:
    documents = [Counter(terms(p.searchable_text())) for p in products]
    lengths = [sum(doc.values()) for doc in documents]
    average = sum(lengths) / max(1, len(documents))
    frequencies = Counter(term for doc in documents for term in doc)
    query_terms = set(terms(query))
    scored = []
    for product, document, length in zip(products, documents, lengths):
        score = 0.0
        for term in query_terms:
            frequency = document[term]
            if not frequency:
                continue
            idf = math.log(1 + (len(documents) - frequencies[term] + .5) / (frequencies[term] + .5))
            score += idf * frequency * (k1 + 1) / (frequency + k1 * (1-b + b*length/max(average, 1)))
        if score > 0:
            scored.append((score, product))
    return sorted(scored, key=lambda pair: (-pair[0], pair[1].product_id))


def reciprocal_rank_fusion(
    *rankings: list,
    k: int = 60,
    weights: tuple[float, ...] | None = None,
) -> list:
    """按名次融合多路结果；原始分数不可比，因此只使用 rank。

    ``weights`` 与 ``rankings`` 一一对应。省略时保持历史行为：所有通道等权。
    """
    if k < 0:
        raise ValueError("RRF k 不能为负数")
    if weights is None:
        weights = tuple(1.0 for _ in rankings)
    if len(weights) != len(rankings):
        raise ValueError("RRF weights 数量必须与 rankings 一致")
    if any(weight < 0 for weight in weights) or not any(weights):
        raise ValueError("RRF weights 必须非负且至少一个大于 0")
    scores, products = {}, {}
    for ranking, weight in zip(rankings, weights):
        seen = set()
        for rank, (_, product) in enumerate(ranking, start=1):
            key = product.product_id
            if key in seen:
                continue
            seen.add(key)
            products[key] = product
            scores[key] = scores.get(key, 0) + weight/(k+rank)
    return [(scores[key], products[key]) for key in sorted(scores, key=lambda key: (-scores[key], key))]
