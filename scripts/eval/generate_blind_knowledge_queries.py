# -*- coding: utf-8 -*-
"""只向独立 LLM 请求暴露知识索引，生成不带答案的口语化 Query。

阶段 A 不读取 knowledge/*.md 正文；输出中禁止出现 evidence/relevant/grade。
阶段 B 必须在 Query 文件冻结后另行执行，以正文检索和人工审核完成标注。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.infrastructure.settings import PROJECT_ROOT, _load_environment


DEFAULT_OUTPUT = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "blind_queries.jsonl"
COUNTS = {"single_evidence": 18, "cross_evidence": 8, "unanswerable": 3, "policy_boundary": 1}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def load_public_index() -> dict[str, Any]:
    """只读取独立维护的无答案目录卡片；绝不打开 Markdown 正文。"""
    path = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "query_generation_index.json"
    return json.loads(path.read_text(encoding="utf-8"))


def build_prompt(index: dict[str, Any]) -> str:
    return f"""你是跨境电商搜索产品的评测问题设计员。你只能看到知识库索引，看不到正文，也不允许猜测或复述正文中的具体答案。

知识索引：
{json.dumps(index, ensure_ascii=False)}

生成 30 个中文用户问题，严格满足：
- single_evidence 18 条：用户只提出一个主要知识需求；
- cross_evidence 8 条：一个真实决策同时涉及两个主题，需要两类证据；
- unanswerable 3 条：明显需要实时库存、订单物流、未知参数或知识库范围外事实；
- policy_boundary 1 条：询问静态/演示政策资料能否作为当前权威结论。
- 必须口语化，像真实买家聊天；不要使用“证据、文档、字段、快照、召回、single、cross”等评测术语（policy_boundary 为表达资料时效可例外使用“资料”）。
- 不要照抄文件名，不要写“应该优先核对哪些可验证字段”一类模板句。
- 问题可以有错别字式口语、省略和具体场景，但必须可理解。
- 只依据索引选择大概主题，不得输出答案、相关文档、证据、相关性等级或 hard negative。
- 每条提供 id、kind、query、scenario_hint；scenario_hint 只描述用户场景，不得包含答案。

只输出 JSON 数组，不要 Markdown。id 使用 blind-001 到 blind-030。"""


def _extract_array(text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        raise ValueError("模型没有返回 JSON 数组")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, list):
        raise ValueError("模型输出不是数组")
    return data


def validate_queries(rows: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    if len(rows) != 30:
        problems.append(f"数量应为30，实际{len(rows)}")
    expected_ids = [f"blind-{index:03d}" for index in range(1, 31)]
    if [row.get("id") for row in rows] != expected_ids:
        problems.append("id 必须从 blind-001 连续到 blind-030")
    kinds: dict[str, int] = {}
    forbidden_fields = {"evidence", "relevant", "graded_relevance", "hard_negatives", "answer"}
    forbidden_words = re.compile(r"证据|文档|字段|快照|召回|single|cross", re.IGNORECASE)
    for row in rows:
        kind, query = row.get("kind"), row.get("query")
        kinds[str(kind)] = kinds.get(str(kind), 0) + 1
        if set(row) & forbidden_fields:
            problems.append(f"{row.get('id')}: 泄漏答案字段")
        if not isinstance(query, str) or not 8 <= len(query) <= 100:
            problems.append(f"{row.get('id')}: query 长度非法")
        elif forbidden_words.search(query) and kind != "policy_boundary":
            problems.append(f"{row.get('id')}: query 含评测/语料术语")
    if kinds != COUNTS:
        problems.append(f"问题类型分布错误：{kinds}")
    if len({row.get("query") for row in rows}) != len(rows):
        problems.append("存在重复 query")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="盲生成知识召回 Query（只看索引）")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    _load_environment(PROJECT_ROOT / ".env")
    base_url = os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "qwen3-max")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY")
    index = load_public_index()
    prompt = build_prompt(index)
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.9},
        timeout=120,
    )
    response.raise_for_status()
    rows = _extract_array(response.json()["choices"][0]["message"]["content"])
    problems = validate_queries(rows)
    if problems:
        raise ValueError("盲 Query 自检失败：" + "；".join(problems))
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "stage": "query_generation_only",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model,
        "knowledge_body_exposed": False,
        "public_index_sha256": _sha256(json.dumps(index, ensure_ascii=False, sort_keys=True).encode()),
        "prompt_sha256": _sha256(prompt.encode()),
        "output_sha256": _sha256(output.read_bytes()),
        "case_count": len(rows),
        "kind_counts": COUNTS,
        "forbidden_answer_fields": sorted({"evidence", "relevant", "graded_relevance", "hard_negatives", "answer"}),
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
