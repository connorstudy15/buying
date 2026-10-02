# -*- coding: utf-8 -*-
"""只暴露无答案知识索引，生成 v3 的两条多跳 Query 增补集。

本脚本与正文、候选池和已有标注隔离。生成结果先冻结，再由阶段 B
读取正文完成逐跳证据和 hard-negative 标注。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from app.infrastructure.settings import PROJECT_ROOT, _load_environment


INDEX = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "query_generation_index.json"
OUTPUT = PROJECT_ROOT / "eval" / "knowledge" / "v3" / "blind_multihop_queries.jsonl"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _extract_array(text: str) -> list[dict[str, Any]]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start < 0 or end < start:
        raise ValueError("模型没有返回 JSON 数组")
    value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, list):
        raise ValueError("模型输出不是数组")
    return value


def _prompt(index: dict[str, Any]) -> str:
    return f"""你是跨境电商知识检索评测的问题设计员。你只能看到无答案知识索引，绝对看不到知识正文。

知识索引：
{json.dumps(index, ensure_ascii=False)}

请生成恰好 2 个中文、口语化、真实买家风格的“顺序多跳”问题。严格要求：
- 第一跳需要查出一个中间属性、分类、口径或适用条件；第二跳必须依赖这个中间结果才能继续判断。
- 不能只是两个可以并行回答的问题，不能使用“分别、同时查两方面”伪装成多跳。
- 问题本身不要写出中间答案，也不要猜测正文里的具体数值或结论。
- 两题尽量覆盖不同主题；允许最终因语料不足而被阶段 B 拒绝，但问题必须合理。
- 像用户聊天，不出现“多跳、子查询、证据、文档、字段、召回、评测”等术语。
- 只输出字段 id、kind、query、scenario_hint、dependency_hint。
- kind 固定为 sequential_multi_hop；id 固定为 blind-mh-001、blind-mh-002。
- scenario_hint 只描述用户场景；dependency_hint 只描述“先确认什么类型的信息，再据此判断什么”，不得包含答案。
- 不得输出 answer、evidence、relevant、graded_relevance、hard_negatives 或具体答案。

只输出 JSON 数组，不要 Markdown。"""


def _validate(rows: list[dict[str, Any]]) -> None:
    problems: list[str] = []
    expected_ids = ["blind-mh-001", "blind-mh-002"]
    allowed = {"id", "kind", "query", "scenario_hint", "dependency_hint"}
    forbidden_words = re.compile(r"多跳|子查询|证据|文档|字段|召回|评测", re.IGNORECASE)
    if len(rows) != 2:
        problems.append(f"数量应为2，实际{len(rows)}")
    if [row.get("id") for row in rows] != expected_ids:
        problems.append("id 必须为 blind-mh-001、blind-mh-002")
    for row in rows:
        if set(row) != allowed:
            problems.append(f"{row.get('id')}: 字段集合非法")
        if row.get("kind") != "sequential_multi_hop":
            problems.append(f"{row.get('id')}: kind 非法")
        query = row.get("query")
        if not isinstance(query, str) or not 8 <= len(query) <= 120:
            problems.append(f"{row.get('id')}: query 长度非法")
        elif forbidden_words.search(query):
            problems.append(f"{row.get('id')}: query 含评测术语")
    if len({row.get("query") for row in rows}) != len(rows):
        problems.append("存在重复 Query")
    if problems:
        raise ValueError("盲多跳 Query 自检失败：" + "；".join(problems))


def main() -> None:
    _load_environment(PROJECT_ROOT / ".env")
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    prompt = _prompt(index)
    base_url = os.environ.get("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
    api_key = os.environ.get("LLM_API_KEY", "")
    model = os.environ.get("LLM_MODEL", "qwen3-max")
    if not api_key:
        raise RuntimeError("缺少 LLM_API_KEY")
    response = httpx.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.8},
        timeout=120,
    )
    response.raise_for_status()
    rows = _extract_array(response.json()["choices"][0]["message"]["content"])
    _validate(rows)
    OUTPUT.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    manifest = {
        "stage": "blind_multihop_query_addendum",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": model,
        "knowledge_body_exposed": False,
        "public_index_sha256": _sha256(INDEX.read_bytes()),
        "prompt_sha256": _sha256(prompt.encode()),
        "output_sha256": _sha256(OUTPUT.read_bytes()),
        "case_count": 2,
        "kind_counts": {"sequential_multi_hop": 2},
    }
    OUTPUT.with_suffix(".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output": str(OUTPUT), **manifest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
