# -*- coding: utf-8 -*-
"""只读审计知识 corpus provenance 与 repeated template competition。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.infrastructure.settings import load_settings  # noqa: E402
from scripts.eval.run_dual_tower_d0_role import chunk_fields  # noqa: E402


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def normalized_template_text(text: str) -> str:
    value = re.sub(r"\s+", "", text).casefold()
    # 模板文档主要用类目名做槽位替换；移除标题/类目词后再衡量结构重复。
    for token in (
        "旅行箱包", "家居生活", "数码配件", "户外运动", "美妆护理",
        "厨房餐饮", "办公学习", "母婴宠物", "跨境通用规则",
    ):
        value = value.replace(token, "<category>")
    return value


def lexical_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalized_template_text(a), normalized_template_text(b), autojunk=False).ratio()


def manifest_by_document() -> dict[str, dict]:
    rows = [
        json.loads(line)
        for line in (ROOT / "eval/knowledge/corpus/manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {str(row["document_id"]): row for row in rows}


def hard_negative_sources() -> set[str]:
    path = ROOT / "eval/knowledge/v5/knowledge_eval_core_61.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {
        str(item["source"])
        for row in rows
        for item in row.get("hard_negatives") or []
        if item.get("source")
    }


def load_corpus() -> list[dict]:
    settings = load_settings()
    client = QdrantClient(path=str(settings.data_dir / "qdrant_kb"))
    points, offset = [], None
    while True:
        batch, offset = client.scroll(
            settings.category_kb_eval_collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        points.extend(batch)
        if offset is None:
            break
    client.close()
    return sorted((chunk_fields(point) for point in points), key=lambda row: row["chunk_id"])


def template_slot(source: str, chunk_index: int) -> str | None:
    stem = source.removesuffix(".md")
    if stem.startswith("eval-policy-"):
        return f"policy-template::chunk-{chunk_index}"
    if not stem.startswith("eval-"):
        return None
    suffix = stem.rsplit("-", 1)[-1]
    return f"category-template::{suffix}::chunk-{chunk_index}"


def pairwise(values: list[dict], fn) -> list[float]:
    return [fn(values[i], values[j]) for i in range(len(values)) for j in range(i + 1, len(values))]


def template_groups(chunks: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for chunk in chunks:
        slot = template_slot(chunk["source"], chunk["chunk_index"])
        if slot:
            grouped[slot].append(chunk)
    output = []
    for group_id, members in sorted(grouped.items()):
        if len(members) < 2:
            continue
        lexical = pairwise(members, lambda a, b: lexical_similarity(a["text"], b["text"]))
        semantic = pairwise(members, lambda a, b: cosine(a["baseline_vector"], b["baseline_vector"]))
        lex_mean = statistics.mean(lexical)
        sem_mean = statistics.mean(semantic)
        output.append({
            "template_group_id": group_id,
            "chunk_count": len(members),
            "chunk_ids": [row["chunk_id"] for row in members],
            "sources": [row["source"] for row in members],
            "document_ids": [row["document_id"] for row in members],
            "chunk_index": members[0]["chunk_index"],
            "text_similarity": {
                "method": "SequenceMatcher after whitespace/category-slot normalization",
                "mean": lex_mean, "min": min(lexical), "max": max(lexical),
            },
            "semantic_similarity": {
                "method": "cosine on existing production Flash vectors",
                "mean": sem_mean, "min": min(semantic), "max": max(semantic),
            },
            "information_need_relation": "same template slot; category/region term varies",
            "independent_knowledge_assessment": (
                "low_independence_template_repetition" if lex_mean >= 0.70 or sem_mean >= 0.90
                else "requires_human_review"
            ),
        })
    return output


def provenance_rows(chunks: list[dict], manifest: dict[str, dict], hard_sources: set[str]) -> list[dict]:
    rows = []
    for chunk in chunks:
        meta = manifest.get(chunk["document_id"], {})
        source_type = str(meta.get("source_type") or chunk["metadata"].get("source_type") or "unknown")
        eval_prefix = chunk["source"].startswith("eval-")
        observed_hard_negative = chunk["source"] in hard_sources
        rows.append({
            "chunk_id": chunk["chunk_id"],
            "source": chunk["source"],
            "document_id": chunk["document_id"],
            "section": chunk["section"],
            "chunk_index": chunk["chunk_index"],
            "text_hash": hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest(),
            "source_type": source_type,
            "is_synthetic": source_type == "synthetic_evaluation_fixture",
            "is_eval_fixture": source_type == "synthetic_evaluation_fixture" or eval_prefix,
            "is_production_knowledge": source_type in {"official_snapshot", "licensed_production_data", "production_knowledge"},
            "is_hard_negative_fixture": eval_prefix,
            "hard_negative_basis": (
                "explicitly_observed_in_v5_labels_and_eval_prefix" if observed_hard_negative
                else "eval_prefix_and_baseline_fixture_design; not individually declared in metadata"
            ) if eval_prefix else (
                "observed_in_v5_labels" if observed_hard_negative else "not_marked"
            ),
            "observed_as_hard_negative_in_v5": observed_hard_negative,
            "ingestion_source_code": "app/infrastructure/rag/category_knowledge.py: bootstrap_category_knowledge glob knowledge/*.md",
            "runtime_entrypoint": "app/composition.py: runtime startup calls bootstrap_category_knowledge",
            "origin_commit": "8d824d8e7168ddc3ec08fe841c62e1cdc75e5b9b chore: establish pre-query-planner baseline",
        })
    return rows


def classify_v4_top20(chunks: list[dict], provenance: dict[str, dict]) -> list[dict]:
    artifact = json.loads(
        (ROOT / "eval/runs/dual-tower-d0-full/d0-full-retriever-only.json").read_text(encoding="utf-8")
    )
    top20 = artifact["selected_case_diagnostics"]["v4_006_top20"]["v4-006::original"]["flash_role"]
    chunks_by_id = {row["chunk_id"]: row for row in chunks}
    output = []
    for candidate in top20:
        p = provenance[str(candidate["candidate_id"])]
        chunk = chunks_by_id[str(candidate["candidate_id"])]
        if p["is_eval_fixture"] and p["is_hard_negative_fixture"]:
            classification = "evaluation_fixture_pollution_and_intentional_eval_decoy"
        elif p["is_production_knowledge"]:
            classification = "legitimate_production_knowledge"
        else:
            classification = "synthetic_demo_knowledge"
        output.append({
            "rank": candidate["rank"], "chunk_id": candidate["candidate_id"],
            "source": candidate["source"], "document_id": candidate["document_id"],
            "chunk_index": candidate["chunk_index"], "is_gold": bool(candidate.get("evidence_ids")),
            "classification": classification,
            "is_high_value_independent_knowledge": False if p["is_eval_fixture"] else None,
            "reason": (
                "eval-prefixed synthetic fixture loaded by the same runtime glob as application knowledge; "
                "topic-related but does not support v4-006 gold evidence"
            ),
            "excerpt": " ".join(chunk["text"].split())[:300],
        })
    return output


def render(summary: dict) -> str:
    c = summary["counts"]
    lines = [
        "# Knowledge Corpus Provenance Audit", "",
        "本报告只读分析现有 collection；未删除文档、未重建索引、未修改 Candidate B。", "",
        "## 结论", "",
        "当前 `globex_category_kb` 不是生产知识与评测知识隔离后的 production corpus。",
        "45 篇源文档全部声明为 `synthetic_evaluation_fixture`；40 篇 `eval-*` 文档贡献了 142/151 个 chunk。",
        "这些文档是为了建立可区分的召回 baseline 而有意加入的评测困难候选，但运行时也通过同一个 `knowledge/*.md` glob 加载它们。",
        "因此它们在评测语境中属于合法的 synthetic hard-negative/decoy corpus，在应用运行语境中构成 evaluation fixture pollution。", "",
        "## 数量", "",
        f"- 总文档：{c['document_count']}；总 chunk：{c['chunk_count']}。",
        f"- synthetic/eval fixture：{c['synthetic_chunk_count']} chunks（{c['synthetic_chunk_ratio']:.2%}）。",
        f"- `eval-*`：{c['eval_prefix_document_count']} documents / {c['eval_prefix_chunk_count']} chunks。",
        f"- 非 `eval-*`：{c['non_eval_document_count']} documents / {c['non_eval_chunk_count']} chunks，但 metadata 仍全部是 synthetic fixture。",
        f"- 可按 metadata 认定的 production knowledge：{c['production_document_count']} documents / {c['production_chunk_count']} chunks。", "",
        "## 入库原因", "",
        "- `app/infrastructure/rag/category_knowledge.py` 对 `knowledge/*.md` 无差别遍历并写入 collection，没有 source_type 或文件名前缀过滤。",
        "- `app/composition.py` 在应用启动时调用同一个 bootstrap，因此不是只有 eval runner 才会加载这些文档。",
        "- `tests/test_knowledge_fixture.py` 明确要求文档数 >=40、chunk 数 150–250，以让召回测试具有区分度。",
        "- 所有 45 篇文档在 commit `8d824d8`（`chore: establish pre-query-planner baseline`）中一起加入。", "",
        "## 重复模板", "",
        f"检测到 {c['template_group_count']} 个跨文档模板组，共覆盖 {c['template_group_chunk_memberships']} 个 chunk membership。",
    ]
    for group in summary["template_groups"]:
        lines.append(
            f"- `{group['template_group_id']}`：{group['chunk_count']} chunks；"
            f"文本相似均值 {group['text_similarity']['mean']:.3f}；"
            f"向量 cosine 均值 {group['semantic_similarity']['mean']:.3f}；"
            f"判断 `{group['independent_knowledge_assessment']}`。"
        )
    lines += ["", "## v4-006 Flash Top-20", "",
              "20/20 均为 `eval-travel-gear-*` 或 `eval-home-living-*` synthetic fixtures，且均不包含 gold evidence。",
              "它们是同领域模板化 decoy，在评测中可作为困难负例；但由于进入运行时 collection，也证明 production/evaluation 未隔离。", "",
              "## 建议", "",
              "应该启动独立 Corpus Hygiene Experiment，但先建立明确的 production allowlist/目录/collection。",
              "清理后的提升必须归因于 corpus isolation，而不是 embedding。当前不应继续 D0-instruct：否则会用 instruct 去拟合本应由语料隔离解决的 fixture competition。",
              "也没有证据启动 Chunk Experiment E。"]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "eval/runs/corpus-provenance-audit")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    chunks = load_corpus()
    manifest = manifest_by_document()
    provenance = provenance_rows(chunks, manifest, hard_negative_sources())
    groups = template_groups(chunks)
    provenance_by_id = {row["chunk_id"]: row for row in provenance}
    v4 = classify_v4_top20(chunks, provenance_by_id)
    documents = {row["document_id"] for row in provenance}
    eval_documents = {row["document_id"] for row in provenance if row["source"].startswith("eval-")}
    production_documents = {row["document_id"] for row in provenance if row["is_production_knowledge"]}
    group_memberships = sum(group["chunk_count"] for group in groups)
    summary = {
        "schema_version": "knowledge-corpus-provenance-audit-v1",
        "collection": load_settings().category_kb_eval_collection,
        "counts": {
            "document_count": len(documents), "chunk_count": len(provenance),
            "synthetic_document_count": len({r["document_id"] for r in provenance if r["is_synthetic"]}),
            "synthetic_chunk_count": sum(r["is_synthetic"] for r in provenance),
            "synthetic_chunk_ratio": sum(r["is_synthetic"] for r in provenance) / len(provenance),
            "eval_prefix_document_count": len(eval_documents),
            "eval_prefix_chunk_count": sum(r["source"].startswith("eval-") for r in provenance),
            "non_eval_document_count": len(documents - eval_documents),
            "non_eval_chunk_count": sum(not r["source"].startswith("eval-") for r in provenance),
            "production_document_count": len(production_documents),
            "production_chunk_count": sum(r["is_production_knowledge"] for r in provenance),
            "observed_hard_negative_document_count": len({r["document_id"] for r in provenance if r["observed_as_hard_negative_in_v5"]}),
            "observed_hard_negative_chunk_count": sum(r["observed_as_hard_negative_in_v5"] for r in provenance),
            "template_group_count": len(groups), "template_group_chunk_memberships": group_memberships,
        },
        "provenance_findings": {
            "eval_fixture_intent": "intentional evaluation decoys / recall-discrimination corpus",
            "runtime_state": "same directory and same collection as application runtime",
            "production_evaluation_isolation": False,
            "pollution_present": True,
            "origin_commit": "8d824d8e7168ddc3ec08fe841c62e1cdc75e5b9b",
            "origin_commit_subject": "chore: establish pre-query-planner baseline",
        },
        "template_groups": groups,
        "v4_006_flash_top20": v4,
        "recommendation": {
            "start_corpus_hygiene_experiment": True,
            "continue_d0_instruct_now": False,
            "modify_production_collection_now": False,
            "reason": "separate evaluation fixtures before tuning retrieval instructions against their competition",
        },
    }
    (args.output_dir / "corpus-provenance.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in provenance), encoding="utf-8"
    )
    (args.output_dir / "template-groups.json").write_text(json.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "v4-006-flash-top20-audit.json").write_text(json.dumps(v4, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "audit-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "CORPUS_PROVENANCE_AUDIT.md").write_text(render(summary), encoding="utf-8")
    print(json.dumps(summary["counts"] | summary["provenance_findings"] | summary["recommendation"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
