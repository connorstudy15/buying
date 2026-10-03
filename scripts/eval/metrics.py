# -*- coding: utf-8 -*-
"""recall metrics —— 召回评测的三个核心指标 + 聚合 + 发版门禁

指标口径与 13-1 章一致：

    Recall@K   Top-K 覆盖了多少标注项      —— 任何召回环节的底线
    Precision@K Top-K 中有多少是真正相关项 —— 防止塞满无关候选
    MRR        首条命中的倒数排名          —— Top-1 直接影响主 Agent 精挑
    NDCG@K     考虑位置 + 标注序的 gain    —— 不只看命中，还看好的是否靠前

三者都只依赖「召回出来的 id 序列」与「标注的 id 序列」，因此纯函数、零依赖、可单测，
商品检索与品类知识库两条链路共用同一套实现。

标注序即重要性序：`relevant[0]` 最相关。NDCG 用线性 gain（`len(relevant) - i`），
比二元相关更能区分「命中了但排在最后」和「命中且排第一」。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence


def _dedup_keep_order(items: Iterable[str]) -> list[str]:
    """去重但保序。

    召回结果理论上不该有重复 id，但真实链路里（多路合并、降级重试）可能出现；
    不去重会让 Recall 虚高、MRR 失真，故在指标入口统一清洗。
    """
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def recall_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Top-K 召回里覆盖了多少标注。

    注意：标注数大于 K 时，本指标天然取不到 1.0（这是 Recall@K 的定义，不是 bug）。
    因此选 K 时应让 K >= 单条 query 的常见标注数。
    """
    if k <= 0:
        return 0.0
    rel = set(relevant)
    if not rel:
        return 0.0
    top_k = set(_dedup_keep_order(retrieved)[:k])
    return len(top_k & rel) / len(rel)


def precision_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Top-K 已返回结果中的相关项占比。

    分母使用实际返回条数：检索链路因硬约束只返回一条且该条相关时，不应被
    人为补齐到 K 个空位而罚分。
    """
    if k <= 0 or not relevant:
        return 0.0
    top_k = _dedup_keep_order(retrieved)[:k]
    if not top_k:
        return 0.0
    return len(set(top_k) & set(relevant)) / len(top_k)


def mrr(retrieved: Sequence[str], relevant: Sequence[str]) -> float:
    """首条相关项的倒数排名；一条都没命中记 0。"""
    rel = set(relevant)
    if not rel:
        return 0.0
    for index, item in enumerate(_dedup_keep_order(retrieved), start=1):
        if item in rel:
            return 1.0 / index
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """NDCG@K：按标注序给线性 gain，按位置打折。"""
    if k <= 0 or not relevant:
        return 0.0
    # 标注序越靠前 gain 越大：第 0 位得 len(relevant)，末位得 1
    gain = {item: len(relevant) - i for i, item in enumerate(relevant)}
    ranked = _dedup_keep_order(retrieved)[:k]
    dcg = sum(gain.get(item, 0) / math.log2(i + 2) for i, item in enumerate(ranked))
    ideal = sum(
        gain[item] / math.log2(i + 2) for i, item in enumerate(list(relevant)[:k])
    )
    return dcg / ideal if ideal else 0.0


def graded_ndcg_at_k(retrieved: Sequence[str], relevance_grades: Mapping[str, int], k: int) -> float:
    """使用 0..3 人工等级的标准 graded nDCG，gain = 2^grade - 1。"""
    if k <= 0 or not relevance_grades:
        return 0.0
    grades = {item: int(grade) for item, grade in relevance_grades.items() if int(grade) > 0}
    if not grades:
        return 0.0
    ranked = _dedup_keep_order(retrieved)[:k]
    dcg = sum(((2 ** grades.get(item, 0)) - 1) / math.log2(index + 2) for index, item in enumerate(ranked))
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    ideal = sum(((2 ** grade) - 1) / math.log2(index + 2) for index, grade in enumerate(ideal_grades))
    return dcg / ideal if ideal else 0.0


@dataclass
class QueryResult:
    """单条 query 的评测结果。"""

    query: str
    retrieved: list[str]
    relevant: list[str]
    recall: float
    mrr: float
    ndcg: float
    precision: float = 0.0
    # 硬约束过滤是否正确：None = 该 query 未声明约束，不参与统计
    filter_ok: bool | None = None
    note: str = ""
    # query 类型（lexical / semantic），用于拆分统计
    kind: str = "lexical"
    # 原始候选中跨平台同款的占比；指标按 canonical 去重后计算，但该值保留暴露多样性问题。
    canonical_duplicate_rate: float | None = None
    # 单条真实检索链路耗时；由 runner 在 usecase.execute 外围计时。
    latency_ms: float | None = None
    # 命中中违反结构化硬约束的商品数/参与检查的命中数。filter_ok 继续保留“泄漏+误杀”总判断。
    hard_constraint_violations: int = 0
    hard_constraint_checked_hits: int = 0
    # None = 本题没有原始 query/改写证据，不参与漂移率统计。
    rewrite_drift: bool | None = None
    rewrite_note: str = ""
    # 同一真实链路在 rerank 前的一阶段候选召回；None 表示该链路未提供阶段证据。
    candidate_recall: float | None = None
    candidate_depth: int | None = None
    # candidate_generation_miss / rerank_miss / hard_constraint_filter / none
    miss_stage: str = "none"
    # 正式评测必须能按场景与业务约束拆分；缺失的维度由运行器显式填为 ALL。
    dimensions: dict[str, str] = field(default_factory=dict)
    # 知识库 v3：稳定证据（source + section + quote）粒度指标。
    evidence_recall: float | None = None
    all_evidence_recall: float | None = None
    hop_recall: float | None = None
    path_success: bool | None = None
    # 只有 Query Planner/Agent trace 能证明隐含约束已识别并传递；裸检索时必须为 None。
    constraint_recall: float | None = None
    hard_negative_hit: bool | None = None
    hard_negative_above_positive: bool | None = None
    graded_ndcg: float | None = None
    pre_fusion_information_need_coverage: float | None = None
    post_fusion_information_need_coverage: float | None = None
    # Partial Coverage 专项：只对 KB 当前确实存在的正证据算 Recall；分母不包含缺失证据。
    available_evidence_recall: float | None = None
    # 所有必要 information needs 中，最终被有效证据覆盖的比例；缺失 gold 的 need 固定记 0。
    information_need_coverage: float | None = None
    # 以下三个指标需要观察 Agent 最终回答/动作。裸检索 runner 必须保持 None，不能伪造。
    missing_need_detected: bool | None = None
    false_complete_answer: bool | None = None
    correct_escalation: bool | None = None


@dataclass
class Aggregate:
    """整个标注集的平均指标。"""

    k: int
    count: int
    recall: float
    mrr: float
    ndcg: float
    precision: float = 0.0
    filter_accuracy: float | None = None
    # 无结果/不可回答类不应被当作“空 relevant 的正例”混进 Recall，单独统计。
    empty_count: int = 0
    empty_accuracy: float | None = None
    # 政策题不能把无来源/过期材料包装成确定事实，单独统计拒答证据。
    policy_count: int = 0
    policy_rejection_accuracy: float | None = None
    canonical_duplicate_rate: float | None = None
    hard_constraint_violation_count: int = 0
    hard_constraint_checked_hits: int = 0
    hard_constraint_violation_rate: float | None = None
    latency_count: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    rewrite_count: int = 0
    rewrite_drift_rate: float | None = None
    candidate_recall_count: int = 0
    candidate_recall: float | None = None
    candidate_depth: int | None = None
    miss_stage_counts: dict[str, int] = field(default_factory=dict)
    # 本轮实际走到的召回策略；正式主链不能把静默降级当作向量+精排的成绩。
    recall_strategies: frozenset[str] = field(default_factory=frozenset)
    per_query: list[QueryResult] = field(default_factory=list)
    evidence_recall_count: int = 0
    evidence_recall: float | None = None
    all_evidence_count: int = 0
    all_evidence_recall: float | None = None
    hop_recall_count: int = 0
    hop_recall: float | None = None
    path_success_count: int = 0
    path_success_rate: float | None = None
    constraint_recall_count: int = 0
    constraint_recall: float | None = None
    hard_negative_count: int = 0
    hard_negative_hit_rate: float | None = None
    hard_negative_above_positive_rate: float | None = None
    # primary_kind -> 指标。值保持 JSON 可序列化，便于写入 manifest/report。
    bucket_metrics: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    graded_ndcg_count: int = 0
    graded_ndcg: float | None = None
    information_need_coverage_count: int = 0
    pre_fusion_information_need_coverage: float | None = None
    post_fusion_information_need_coverage: float | None = None
    fusion_information_need_loss: float | None = None
    partial_coverage_count: int = 0
    available_evidence_recall: float | None = None
    partial_information_need_coverage: float | None = None
    missing_need_detection_count: int = 0
    missing_need_detection_accuracy: float | None = None
    false_complete_answer_count: int = 0
    false_complete_answer_rate: float | None = None
    correct_escalation_count: int = 0
    correct_escalation_rate: float | None = None
    partial_per_query: list[QueryResult] = field(default_factory=list)


def evaluate(
    results: Sequence[QueryResult],
    k: int,
    empty_results: Sequence[bool] = (),
    policy_results: Sequence[bool] = (),
    recall_strategies: Sequence[str] = (),
    latencies_ms: Sequence[float] = (),
) -> Aggregate:
    """把逐条结果聚合成平均指标（宏平均：每条 query 等权）。"""
    empty_count = len(empty_results)
    empty_accuracy = round(sum(empty_results) / empty_count, 4) if empty_count else None
    policy_count = len(policy_results)
    policy_rejection_accuracy = round(sum(policy_results) / policy_count, 4) if policy_count else None
    observed_latencies = list(latencies_ms) or [
        float(result.latency_ms) for result in results if result.latency_ms is not None
    ]

    def percentile(values: Sequence[float], q: float) -> float | None:
        if not values:
            return None
        ordered = sorted(float(value) for value in values)
        # 最近秩（nearest-rank）：小样本也不会插值出未实际观测的延迟。
        index = max(0, math.ceil(q * len(ordered)) - 1)
        return round(ordered[index], 3)

    if not results:
        return Aggregate(
            k=k, count=0, recall=0.0, mrr=0.0, ndcg=0.0, precision=0.0,
            empty_count=empty_count, empty_accuracy=empty_accuracy,
            policy_count=policy_count, policy_rejection_accuracy=policy_rejection_accuracy,
            recall_strategies=frozenset(recall_strategies), per_query=[],
            latency_count=len(observed_latencies),
            latency_p50_ms=percentile(observed_latencies, 0.50),
            latency_p95_ms=percentile(observed_latencies, 0.95),
        )

    count = len(results)
    checked = [r for r in results if r.filter_ok is not None]
    duplicate_rates = [r.canonical_duplicate_rate for r in results if r.canonical_duplicate_rate is not None]
    checked_hits = sum(result.hard_constraint_checked_hits for result in results)
    violation_count = sum(result.hard_constraint_violations for result in results)
    constrained_results = [result for result in results if result.filter_ok is not None]
    rewrite_results = [result for result in results if result.rewrite_drift is not None]
    candidate_results = [result for result in results if result.candidate_recall is not None]
    miss_stage_counts: dict[str, int] = {}
    for result in results:
        miss_stage_counts[result.miss_stage] = miss_stage_counts.get(result.miss_stage, 0) + 1
    filter_accuracy = (
        sum(1 for r in checked if r.filter_ok) / len(checked) if checked else None
    )
    def optional_mean(field_name: str) -> tuple[int, float | None]:
        values = [getattr(result, field_name) for result in results if getattr(result, field_name) is not None]
        return len(values), (None if not values else round(sum(float(value) for value in values) / len(values), 4))

    evidence_count, evidence_recall = optional_mean("evidence_recall")
    all_evidence_count, all_evidence_recall = optional_mean("all_evidence_recall")
    hop_count, hop_recall = optional_mean("hop_recall")
    path_count, path_success_rate = optional_mean("path_success")
    constraint_count, constraint_recall = optional_mean("constraint_recall")
    graded_ndcg_count, graded_ndcg = optional_mean("graded_ndcg")
    need_coverage_count, pre_need_coverage = optional_mean("pre_fusion_information_need_coverage")
    _, post_need_coverage = optional_mean("post_fusion_information_need_coverage")
    hard_negative_results = [result for result in results if result.hard_negative_hit is not None]
    hard_negative_above_results = [result for result in results if result.hard_negative_above_positive is not None]

    def summarize_bucket(bucket_results: Sequence[QueryResult]) -> dict[str, float | int | None]:
        size = len(bucket_results)
        summary: dict[str, float | int | None] = {
            "count": size,
            "recall": round(sum(item.recall for item in bucket_results) / size, 4),
            "mrr": round(sum(item.mrr for item in bucket_results) / size, 4),
            "ndcg": round(sum(item.ndcg for item in bucket_results) / size, 4),
        }
        for field_name in (
            "evidence_recall", "all_evidence_recall", "hop_recall", "constraint_recall", "graded_ndcg",
            "pre_fusion_information_need_coverage", "post_fusion_information_need_coverage",
        ):
            values = [getattr(item, field_name) for item in bucket_results if getattr(item, field_name) is not None]
            summary[field_name] = None if not values else round(sum(float(value) for value in values) / len(values), 4)
        paths = [item.path_success for item in bucket_results if item.path_success is not None]
        summary["path_success_rate"] = None if not paths else round(sum(bool(value) for value in paths) / len(paths), 4)
        negative_hits = [item.hard_negative_hit for item in bucket_results if item.hard_negative_hit is not None]
        summary["hard_negative_hit_rate"] = None if not negative_hits else round(sum(bool(value) for value in negative_hits) / len(negative_hits), 4)
        return summary

    buckets: dict[str, list[QueryResult]] = {}
    for result in results:
        bucket = result.dimensions.get("primary_kind", result.kind or "ALL")
        buckets.setdefault(bucket, []).append(result)
        plan_mode = result.dimensions.get("query_plan_mode")
        if plan_mode:
            buckets.setdefault(f"query_plan:{plan_mode}", []).append(result)
    bucket_metrics = {name: summarize_bucket(items) for name, items in sorted(buckets.items())}
    if empty_count:
        bucket_metrics["unanswerable"] = {"count": empty_count, "rejection_accuracy": empty_accuracy}

    return Aggregate(
        k=k,
        count=count,
        recall=round(sum(r.recall for r in results) / count, 4),
        mrr=round(sum(r.mrr for r in results) / count, 4),
        ndcg=round(sum(r.ndcg for r in results) / count, 4),
        precision=round(sum(r.precision for r in results) / count, 4),
        filter_accuracy=None if filter_accuracy is None else round(filter_accuracy, 4),
        empty_count=empty_count,
        empty_accuracy=empty_accuracy,
        policy_count=policy_count,
        policy_rejection_accuracy=policy_rejection_accuracy,
        canonical_duplicate_rate=(
            None if not duplicate_rates else round(sum(duplicate_rates) / len(duplicate_rates), 4)
        ),
        hard_constraint_violation_count=violation_count,
        hard_constraint_checked_hits=checked_hits,
        hard_constraint_violation_rate=(
            None if not constrained_results else round(violation_count / checked_hits, 4) if checked_hits else 0.0
        ),
        latency_count=len(observed_latencies),
        latency_p50_ms=percentile(observed_latencies, 0.50),
        latency_p95_ms=percentile(observed_latencies, 0.95),
        rewrite_count=len(rewrite_results),
        rewrite_drift_rate=(
            None if not rewrite_results else round(
                sum(1 for result in rewrite_results if result.rewrite_drift) / len(rewrite_results), 4,
            )
        ),
        candidate_recall_count=len(candidate_results),
        candidate_recall=(
            None if not candidate_results else round(
                sum(float(result.candidate_recall) for result in candidate_results) / len(candidate_results), 4,
            )
        ),
        candidate_depth=(
            None if not candidate_results else max(
                int(result.candidate_depth or k) for result in candidate_results
            )
        ),
        miss_stage_counts=miss_stage_counts,
        recall_strategies=frozenset(recall_strategies),
        per_query=list(results),
        evidence_recall_count=evidence_count,
        evidence_recall=evidence_recall,
        all_evidence_count=all_evidence_count,
        all_evidence_recall=all_evidence_recall,
        hop_recall_count=hop_count,
        hop_recall=hop_recall,
        path_success_count=path_count,
        path_success_rate=path_success_rate,
        constraint_recall_count=constraint_count,
        constraint_recall=constraint_recall,
        hard_negative_count=len(hard_negative_results),
        hard_negative_hit_rate=(
            None if not hard_negative_results else round(
                sum(bool(result.hard_negative_hit) for result in hard_negative_results) / len(hard_negative_results), 4,
            )
        ),
        hard_negative_above_positive_rate=(
            None if not hard_negative_above_results else round(
                sum(bool(result.hard_negative_above_positive) for result in hard_negative_above_results)
                / len(hard_negative_above_results), 4,
            )
        ),
        bucket_metrics=bucket_metrics,
        graded_ndcg_count=graded_ndcg_count,
        graded_ndcg=graded_ndcg,
        information_need_coverage_count=need_coverage_count,
        pre_fusion_information_need_coverage=pre_need_coverage,
        post_fusion_information_need_coverage=post_need_coverage,
        fusion_information_need_loss=(
            None if pre_need_coverage is None or post_need_coverage is None
            else round(pre_need_coverage - post_need_coverage, 4)
        ),
    )


def attach_partial_coverage_metrics(
    aggregate: Aggregate,
    partial_results: Sequence[QueryResult],
) -> Aggregate:
    """把 Partial Coverage 指标附加到普通召回聚合，不污染标准 Recall/MRR/nDCG。

    `partial_results` 的普通 recall 字段仅供逐题诊断；它们不会加入 aggregate.count，
    也不会改变完整可回答题的发布门禁。
    """
    items = list(partial_results)
    aggregate.partial_coverage_count = len(items)
    aggregate.partial_per_query = items
    if not items:
        return aggregate

    def mean_optional(field_name: str) -> tuple[int, float | None]:
        values = [getattr(item, field_name) for item in items if getattr(item, field_name) is not None]
        return len(values), (None if not values else round(sum(float(value) for value in values) / len(values), 4))

    _, aggregate.available_evidence_recall = mean_optional("available_evidence_recall")
    _, aggregate.partial_information_need_coverage = mean_optional("information_need_coverage")
    aggregate.missing_need_detection_count, aggregate.missing_need_detection_accuracy = mean_optional(
        "missing_need_detected",
    )
    aggregate.false_complete_answer_count, aggregate.false_complete_answer_rate = mean_optional(
        "false_complete_answer",
    )
    aggregate.correct_escalation_count, aggregate.correct_escalation_rate = mean_optional(
        "correct_escalation",
    )
    aggregate.bucket_metrics["partial_coverage"] = {
        "count": len(items),
        "available_evidence_recall": aggregate.available_evidence_recall,
        "information_need_coverage": aggregate.partial_information_need_coverage,
        "missing_need_detection_accuracy": aggregate.missing_need_detection_accuracy,
        "false_complete_answer_rate": aggregate.false_complete_answer_rate,
        "correct_escalation_rate": aggregate.correct_escalation_rate,
    }
    return aggregate


@dataclass(frozen=True)
class Thresholds:
    """发版门禁阈值。

    召回、精度与排序任一退化都判 BLOCK。电商检索里“召回到了但排得很后”或
    “候选塞满无关商品”都会直接伤害买家体验，不能只做告警。
    """

    recall: float = 0.75
    # 当金标尚未穷举时，Precision@K 只能作为观察指标，不能设置不可达的硬门槛。
    precision: float | None = 0.45
    mrr: float = 0.65
    ndcg: float = 0.70
    empty_accuracy: float | None = None
    filter_accuracy: float | None = None
    policy_rejection_accuracy: float | None = None
    required_recall_strategies: frozenset[str] | set[str] | None = None
    max_hard_constraint_violation_rate: float | None = None
    max_latency_p95_ms: float | None = None
    max_rewrite_drift_rate: float | None = None


def gate(
    agg: Aggregate,
    thresholds: Thresholds,
    baseline: Mapping[str, float] | None = None,
    max_baseline_drop: float = 0.02,
) -> tuple[str, list[str]]:
    """返回 (verdict, 原因列表)；verdict ∈ PASS / WARN / BLOCK。"""
    blocks: list[str] = []
    if agg.count == 0:
        if agg.partial_coverage_count:
            return "WARN", ["仅包含 Partial Coverage 专项；未执行普通 Recall/MRR/nDCG 发布门禁"]
        return "BLOCK", ["标注集为空，无法评测"]

    if agg.recall < thresholds.recall:
        blocks.append(f"Recall@{agg.k} {agg.recall} < {thresholds.recall}")
    if thresholds.precision is not None and agg.precision < thresholds.precision:
        blocks.append(f"Precision@{agg.k} {agg.precision} < {thresholds.precision}")
    if agg.mrr < thresholds.mrr:
        blocks.append(f"MRR {agg.mrr} < {thresholds.mrr}")
    if agg.ndcg < thresholds.ndcg:
        blocks.append(f"NDCG@{agg.k} {agg.ndcg} < {thresholds.ndcg}")
    if thresholds.empty_accuracy is not None:
        if agg.empty_accuracy is None:
            blocks.append("无结果准确率未统计")
        elif agg.empty_accuracy < thresholds.empty_accuracy:
            blocks.append(f"无结果准确率 {agg.empty_accuracy} < {thresholds.empty_accuracy}")
    if thresholds.filter_accuracy is not None:
        if agg.filter_accuracy is None:
            blocks.append("硬约束准确率未统计")
        elif agg.filter_accuracy < thresholds.filter_accuracy:
            blocks.append(f"硬约束准确率 {agg.filter_accuracy} < {thresholds.filter_accuracy}")
    if thresholds.policy_rejection_accuracy is not None:
        if agg.policy_rejection_accuracy is None:
            blocks.append("政策拒答准确率未统计")
        elif agg.policy_rejection_accuracy < thresholds.policy_rejection_accuracy:
            blocks.append(
                f"政策拒答准确率 {agg.policy_rejection_accuracy} < {thresholds.policy_rejection_accuracy}",
            )
    if thresholds.required_recall_strategies is not None:
        required_strategies = set(thresholds.required_recall_strategies)
        actual_strategies = set(agg.recall_strategies)
        if actual_strategies != required_strategies:
            blocks.append(
                f"实际召回策略 {sorted(actual_strategies)} != 要求 {sorted(required_strategies)}",
            )
    if thresholds.max_hard_constraint_violation_rate is not None:
        if agg.hard_constraint_violation_rate is None:
            blocks.append("硬约束违规率未统计")
        elif agg.hard_constraint_violation_rate > thresholds.max_hard_constraint_violation_rate:
            blocks.append(
                f"硬约束违规率 {agg.hard_constraint_violation_rate} > "
                f"{thresholds.max_hard_constraint_violation_rate}",
            )
    if thresholds.max_latency_p95_ms is not None:
        if agg.latency_p95_ms is None:
            blocks.append("P95 延迟未统计")
        elif agg.latency_p95_ms > thresholds.max_latency_p95_ms:
            blocks.append(f"P95 延迟 {agg.latency_p95_ms}ms > {thresholds.max_latency_p95_ms}ms")
    if thresholds.max_rewrite_drift_rate is not None:
        if agg.rewrite_drift_rate is None:
            blocks.append("改写漂移率未统计")
        elif agg.rewrite_drift_rate > thresholds.max_rewrite_drift_rate:
            blocks.append(
                f"改写漂移率 {agg.rewrite_drift_rate} > {thresholds.max_rewrite_drift_rate}",
            )

    if baseline:
        current = {
            "recall": agg.recall,
            "precision": agg.precision,
            "mrr": agg.mrr,
            "ndcg": agg.ndcg,
        }
        for metric, approved in baseline.items():
            if metric not in current:
                blocks.append(f"批准基线包含未知指标：{metric}")
                continue
            if current[metric] < float(approved) - max_baseline_drop:
                blocks.append(
                    f"{metric} 相比批准基线下降 {float(approved) - current[metric]:.3f} > {max_baseline_drop:.3f}",
                )

    if blocks:
        return "BLOCK", blocks
    return "PASS", []
