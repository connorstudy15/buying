# -*- coding: utf-8 -*-
"""正式知识评测的拒答与政策来源门禁。"""
from types import SimpleNamespace

from scripts.eval.run_category_recall import run_dataset


class FakeKnowledgeBase:
    async def search(self, queries, top_k):
        return self.hits_by_query[queries[0]][:top_k]

    def __init__(self, hits_by_query):
        self.hits_by_query = hits_by_query


def _hit(source: str, score: float, metadata: dict | None = None, text: str = ""):
    return SimpleNamespace(
        document_id=source,
        score=score,
        chunk=SimpleNamespace(metadata={"source": source, **(metadata or {})}, text=text),
    )


async def test_knowledge_runner_scores_score_based_abstention_and_invalid_policy_rejection():
    knowledge_base = FakeKnowledgeBase({
        "没有证据的问题": [_hit("noise.md", 0.19)],
        "过期政策": [_hit("policy.md", 0.9, {
            "topic": "policy", "source_reference": "合成快照",
            "source_type": "synthetic_evaluation_fixture", "effective_from": "2025-01-01",
            "effective_to": "2026-12-31",
        })],
    })
    cases = [
        {"query": "没有证据的问题", "relevant": [], "expected_unanswerable": True},
        {"query": "过期政策", "relevant": ["policy.md"], "expected_behavior": "拒绝确定事实", "kind": "conflict_or_expired"},
    ]

    observations = []
    aggregate = await run_dataset(knowledge_base, cases, top_k=3, observations=observations)

    assert aggregate.empty_accuracy == 1.0
    assert aggregate.policy_rejection_accuracy == 1.0
    assert aggregate.recall == 1.0
    assert len(observations) == 2
    assert observations[0]["unanswerable_pass"] is True
    assert observations[1]["policy_pass"] is True


async def test_document_hit_can_still_miss_the_gold_evidence_chunk_and_tracks_hard_negative():
    knowledge_base = FakeKnowledgeBase({
        "证据问题": [
            _hit("right.md", 0.9, text="同一文档里另一段不相关内容"),
            _hit("distractor.md", 0.8, text="很像答案但不能支持结论"),
        ],
    })
    case = {
        "id": "evidence-1", "query": "证据问题", "relevant": ["right.md"],
        "primary_kind": "cross_evidence", "graded_relevance": {"right.md": 3, "distractor.md": 1},
        "evidence_ground_truth": [{
            "evidence_id": "right.md#规则#abc", "source": "right.md", "section": "规则",
            "quote": "真正支持答案的原文", "grade": 3, "supports": ["answer"],
        }],
        "hard_negatives": [{"source": "distractor.md", "type": "near", "grade": 1}],
    }

    observations = []
    aggregate = await run_dataset(knowledge_base, [case], top_k=3, observations=observations)

    assert aggregate.recall == 1.0  # 文档粒度看似成功
    assert aggregate.evidence_recall == 0.0  # 但实际没有命中答案所在 chunk
    assert aggregate.all_evidence_recall == 0.0
    assert aggregate.hard_negative_hit_rate == 1.0
    assert observations[0]["retrieved_evidence_ids"] == []


async def test_multi_hop_path_is_na_when_a_later_hop_belongs_to_product_search():
    knowledge_base = FakeKnowledgeBase({"旅行": [_hit("travel.md", 0.9, text="航空容量限制原文")]})
    case = {
        "id": "mh-1", "query": "旅行", "relevant": ["travel.md"],
        "primary_kind": "implicit_constraint_multi_hop", "graded_relevance": {"travel.md": 3},
        "evidence_ground_truth": [{
            "evidence_id": "travel.md#规则#abc", "source": "travel.md", "section": "规则",
            "quote": "航空容量限制原文", "grade": 3, "supports": ["hop_1"],
        }],
        "hops": [
            {"id": "hop_1", "relevant": ["travel.md"]},
            {"id": "hop_2", "relevant": []},
        ],
    }

    aggregate = await run_dataset(knowledge_base, [case], top_k=3)

    assert aggregate.hop_recall == 1.0
    assert aggregate.path_success_rate is None
    assert aggregate.constraint_recall is None


async def test_information_need_coverage_distinguishes_candidate_pool_from_final_top_k():
    knowledge_base = FakeKnowledgeBase({
        "双证据": [
            _hit("a.md", 0.9, text="证据甲"),
            _hit("b.md", 0.8, text="证据乙"),
        ],
    })
    case = {
        "id": "cross-1", "query": "双证据", "relevant": ["a.md", "b.md"],
        "primary_kind": "cross_evidence", "graded_relevance": {"a.md": 3, "b.md": 3},
        "evidence_ground_truth": [
            {"evidence_id": "a#x", "source": "a.md", "quote": "证据甲", "grade": 3, "supports": ["answer"]},
            {"evidence_id": "b#x", "source": "b.md", "quote": "证据乙", "grade": 3, "supports": ["answer"]},
        ],
    }
    observations = []
    aggregate = await run_dataset(knowledge_base, [case], top_k=1, observations=observations)
    assert aggregate.pre_fusion_information_need_coverage == 1.0
    assert aggregate.post_fusion_information_need_coverage == 0.5
    assert aggregate.fusion_information_need_loss == 0.5
    assert observations[0]["pre_fusion_retrieved_evidence_ids"] == ["a#x", "b#x"]
