# -*- coding: utf-8 -*-
"""为 knowledge-eval-v2 增量集盲生成 60 条 Query；只暴露无答案目录索引。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.infrastructure.settings import PROJECT_ROOT, _load_environment


COUNTS = {
    "single_evidence": 22,
    "cross_evidence": 20,
    "implicit_constraint": 10,
    "unanswerable": 7,
    "policy_boundary": 1,
}
DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "knowledge" / "v4" / "blind_increment_queries.jsonl"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract_array(text: str) -> list[dict]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        raise ValueError("模型没有返回 JSON 数组")
    value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, list):
        raise ValueError("模型输出不是数组")
    return value


def _prompt(index: dict) -> str:
    return f"""你是跨境电商 Search Agent 的评测问题设计员。你只能看到知识目录索引，看不到知识正文；不得猜答案、引用结论或生成相关文档标签。

无答案知识索引：
{json.dumps(index, ensure_ascii=False)}

生成 60 个互不重复的中文买家问题，分布必须精确为：
- single_evidence 22：一个主要知识需求；
- cross_evidence 20：一个购买决策明确需要两个或更多独立知识点共同回答；
- implicit_constraint 10：买家没说专业限制，但场景中隐含运输、航空、目的国、尺寸、电压、材质或安全约束；
- unanswerable 7：需要实时库存、订单物流、未来事实、未知 SKU 参数或范围外事实；
- policy_boundary 1：测试静态演示资料不能冒充当前权威政策。

要求：
1. 必须口语化，像真实买家对导购说话，句式和商品主题要多样；
2. cross_evidence 不能只是同一问题换两种说法，必须包含两个可独立检索的信息需求；
3. implicit_constraint 不要直接说“隐含约束”“合规”，让系统主动识别；
4. 不得出现“文档、证据、字段、召回、single、cross、hard negative”等评测术语；
5. 不输出答案、relevant、evidence、grade、hard negative；
6. 每条仅含 id、kind、query、scenario_hint；scenario_hint 只概括使用场景，不泄露答案；
7. id 从 v4-001 连续到 v4-060。

只输出 JSON 数组。"""


def _validate(rows: list[dict]) -> list[str]:
    issues: list[str] = []
    expected_ids = [f"v4-{index:03d}" for index in range(1, 61)]
    if len(rows) != 60:
        issues.append(f"数量应为60，实际{len(rows)}")
    if [row.get("id") for row in rows] != expected_ids:
        issues.append("ID 必须从 v4-001 连续到 v4-060")
    actual = Counter(str(row.get("kind")) for row in rows)
    if actual != Counter(COUNTS):
        issues.append(f"分布错误：{dict(actual)}")
    forbidden_fields = {"answer", "relevant", "evidence", "graded_relevance", "hard_negatives"}
    forbidden_words = re.compile(r"文档|证据|字段|召回|single|cross|hard.?negative", re.IGNORECASE)
    seen: set[str] = set()
    for row in rows:
        query = str(row.get("query") or "").strip()
        if set(row) != {"id", "kind", "query", "scenario_hint"}:
            issues.append(f"{row.get('id')}: 字段不符合约定")
        if set(row) & forbidden_fields:
            issues.append(f"{row.get('id')}: 泄漏答案字段")
        if not 6 <= len(query) <= 120:
            issues.append(f"{row.get('id')}: Query 长度非法")
        if forbidden_words.search(query):
            issues.append(f"{row.get('id')}: 出现评测术语")
        normalized = re.sub(r"\s+", "", query).casefold()
        if normalized in seen:
            issues.append(f"{row.get('id')}: Query 重复")
        seen.add(normalized)
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="盲生成 knowledge-eval-v2 增量 Query")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    _load_environment(PROJECT_ROOT / ".env")
    index_path = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "query_generation_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    prompt = _prompt(index)
    base_url = os.environ.get("LLM_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "")
    if not base_url or not api_key or not model:
        raise RuntimeError("缺少 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL")
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.85,
            "max_tokens": 12000,
        },
        timeout=180,
    )
    response.raise_for_status()
    rows = _extract_array(response.json()["choices"][0]["message"]["content"])
    issues = _validate(rows)
    if issues:
        raise ValueError("盲 Query 自检失败：" + "；".join(issues))
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    usage = response.json().get("usage") or {}
    manifest = {
        "schema_version": "knowledge-v4-blind-query-v1",
        "stage": "query_generation_only",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model,
        "knowledge_body_exposed": False,
        "public_index_sha256": _sha256(index_path.read_bytes()),
        "prompt_sha256": _sha256(prompt.encode()),
        "output_sha256": _sha256(output.read_bytes()),
        "case_count": len(rows),
        "kind_counts": COUNTS,
        "api_usage": usage,
    }
    output.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps({"output": str(output), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
