"""Apply the post-Stage-B human adjudication for implicit-query strategy labels.

The frozen Stage-A query file and its manifest are intentionally not changed.
This script only updates reviewed Stage-B artifacts and writes an explicit audit trail.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
V4_DIR = ROOT / "eval" / "knowledge" / "v4"

POLICY = (
    "即使用户只有一个最终判断目标，如果该判断必须组合两个可独立检索、"
    "可独立失败的 gold evidence needs，也应标为 DECOMPOSE。"
)

ADJUDICATIONS = {
    "v4-043": "必须组合移动电源航空携带限制与含电池露营灯航空携带限制；两项需求可独立检索、独立失败。",
    "v4-044": "必须组合粗陶茶具行李运输的易碎风险与日本目的地当前权威规则核验；两项需求可独立检索、独立失败。",
    "v4-045": "必须组合折叠双肩包自身重量/尺寸属性与廉航免费随身行李限额；两项需求可独立检索、独立失败。",
    "v4-046": "必须组合美国插头/插脚适配要求与小电器输入电压兼容性；两项需求可独立检索、独立失败。",
    "v4-047": "必须组合竹木陶餐具的材料属性与澳大利亚植物制品寄送/检疫限制；两项需求可独立检索、独立失败。",
    "v4-048": "必须组合包裹体积重与实重的计费规则，以及多件物品合并寄送的运费规则；两项需求可独立检索、独立失败。",
    "v4-051": "必须组合天幕的重量/体积属性与大件包裹体积重计费规则；两项需求可独立检索、独立失败。",
    "v4-r014": "必须组合含电池露营灯的航空携带限制与海边使用所需防水能力；两项需求可独立检索、独立失败。",
}


def update_jsonl(path: Path) -> tuple[int, dict[str, int]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    seen: set[str] = set()
    distribution: dict[str, int] = {}
    for row in rows:
        case_id = row.get("id")
        if case_id in ADJUDICATIONS:
            existing_adjudication = row.get("strategy_adjudication") or {}
            prior = existing_adjudication.get("prior_strategy", row.get("expected_query_strategy"))
            row["expected_query_strategy"] = "DECOMPOSE"
            row["decomposition_reason"] = ADJUDICATIONS[case_id]
            row["strategy_adjudication"] = {
                "prior_strategy": prior,
                "final_strategy": "DECOMPOSE",
                "decided_by": "user",
                "decision_date": "2026-10-03",
                "policy": POLICY,
            }
            seen.add(case_id)
        strategy = str(row.get("expected_query_strategy") or "MISSING")
        distribution[strategy] = distribution.get(strategy, 0) + 1

    missing = set(ADJUDICATIONS) - seen
    if missing:
        raise ValueError(f"{path.name} 缺少待裁决 ID: {sorted(missing)}")
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return len(rows), distribution


def update_csv(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    seen: set[str] = set()
    for row in rows:
        case_id = row.get("id")
        if case_id not in ADJUDICATIONS:
            continue
        row["expected_query_strategy"] = "DECOMPOSE"
        row["decomposition_reason"] = ADJUDICATIONS[case_id]
        note = "策略经用户终审改为 DECOMPOSE；依据：" + POLICY
        existing = str(row.get("reviewer_notes") or "").strip()
        if note not in existing:
            row["reviewer_notes"] = f"{existing} | {note}" if existing else note
        seen.add(case_id)

    missing = set(ADJUDICATIONS) - seen
    if missing:
        raise ValueError(f"{path.name} 缺少待裁决 ID: {sorted(missing)}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_audit_trail() -> None:
    jsonl_path = V4_DIR / "query_strategy_adjudication.jsonl"
    records = [
        {
            "id": case_id,
            "prior_strategy": "DIRECT",
            "final_strategy": "DECOMPOSE",
            "reason": reason,
            "decided_by": "user",
            "decision_date": "2026-10-03",
            "policy": POLICY,
        }
        for case_id, reason in ADJUDICATIONS.items()
    ]
    jsonl_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

    md_path = V4_DIR / "QUERY_STRATEGY_ADJUDICATION.md"
    lines = [
        "# Query Strategy 人工终审记录",
        "",
        "> 本记录是阶段 B 之后的人工裁决。阶段 A 已冻结的 Query 与 manifest 哈希不回写。",
        "",
        "## 最终判定口径",
        "",
        f"> {POLICY}",
        "",
        "## DIRECT → DECOMPOSE",
        "",
        "| ID | 终审理由 |",
        "|---|---|",
    ]
    lines.extend(f"| `{case_id}` | {reason} |" for case_id, reason in ADJUDICATIONS.items())
    lines.extend([
        "",
        "`v4-049` 保持 DIRECT；`v4-050` 保持 DIRECT，但它仍是阶段 B rejected case。",
        "",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    reviewed_count, reviewed_dist = update_jsonl(V4_DIR / "stage_b_reviewed_labels.jsonl")
    merged_count, merged_dist = update_jsonl(V4_DIR / "knowledge_eval_candidates.reviewed.jsonl")
    csv_count = update_csv(V4_DIR / "human_review_increment.csv")
    write_audit_trail()
    print(f"stage_b_reviewed_labels: {reviewed_count}, {reviewed_dist}")
    print(f"knowledge_eval_candidates.reviewed: {merged_count}, {merged_dist}")
    print(f"human_review_increment: {csv_count}")


if __name__ == "__main__":
    main()
