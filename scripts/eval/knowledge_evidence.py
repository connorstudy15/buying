# -*- coding: utf-8 -*-
"""知识评测的稳定证据标识与 chunk 命中判定。

金标不使用易随切块参数变化的 chunk id，而使用 source + section + 原文 quote 的哈希。
检索时只要返回 chunk 确实包含该段原文，就算命中对应证据。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Iterable


def normalize_text(value: str) -> str:
    """消除 Markdown/切块常见空白差异，但不改写文字。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def quote_sha256(quote: str) -> str:
    return hashlib.sha256(normalize_text(quote).encode("utf-8")).hexdigest()


def evidence_id(source: str, section: str, quote: str) -> str:
    section_slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", section).strip("-") or "root"
    return f"{source}#{section_slug}#{quote_sha256(quote)[:12]}"


def section_for_quote(markdown: str, quote: str) -> tuple[str | None, int]:
    """返回 quote 所在最近 Markdown 标题及出现次数。"""
    normalized_quote = normalize_text(quote)
    lines = markdown.splitlines()
    current_section: str | None = None
    matches: list[str | None] = []
    for line in lines:
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if heading:
            current_section = normalize_text(heading.group(1).rstrip("#").strip())
        if normalized_quote and normalized_quote in normalize_text(line):
            matches.append(current_section)
    if not matches and normalized_quote in normalize_text(markdown):
        # quote 跨行：通过原始起点前最后一个标题定位。
        compact = normalize_text(markdown)
        occurrence_count = compact.count(normalized_quote)
        raw_start = markdown.find(str(quote))
        if raw_start >= 0:
            headings = re.findall(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$", markdown[:raw_start])
            return (normalize_text(headings[-1].rstrip("#").strip()) if headings else None, occurrence_count)
        return None, occurrence_count
    return (matches[0] if matches else None, len(matches))


def chunk_text(item: Any) -> str:
    chunk = getattr(item, "chunk", item)
    if isinstance(chunk, str):
        return chunk
    if isinstance(chunk, dict):
        return str(chunk.get("text") or chunk.get("content") or "")
    text = getattr(chunk, "text", None)
    if text is not None:
        return str(text)
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    nested_text = getattr(content, "text", None)
    if nested_text is not None:
        return str(nested_text)
    if isinstance(content, dict):
        return str(content.get("text") or content)
    return str(content or "")


def matched_evidence_ids(hits: Iterable[Any], evidence: Iterable[dict]) -> tuple[list[str], dict[str, int]]:
    """按命中顺序返回证据 ID，并保留每条证据首次命中的 1-based rank。"""
    ordered: list[str] = []
    ranks: dict[str, int] = {}
    for rank, hit in enumerate(hits, start=1):
        metadata = getattr(getattr(hit, "chunk", None), "metadata", None) or {}
        source = metadata.get("source", getattr(hit, "document_id", ""))
        text = normalize_text(chunk_text(hit))
        for gold in evidence:
            eid = gold["evidence_id"]
            if eid in ranks or source != gold["source"]:
                continue
            if normalize_text(gold["quote"]) in text:
                ranks[eid] = rank
                ordered.append(eid)
    return ordered, ranks


def inspect_evidence(project_root: Path, item: dict) -> list[str]:
    """返回需要人工审核的问题；空列表代表可稳定回指。"""
    source = str(item.get("source") or "")
    quote = str(item.get("quote") or "")
    declared_section = normalize_text(item.get("section") or "")
    path = project_root / "eval" / "knowledge" / "corpus" / source
    if not path.is_file():
        return ["source_missing"]
    actual_section, occurrences = section_for_quote(path.read_text(encoding="utf-8"), quote)
    issues: list[str] = []
    if occurrences == 0:
        issues.append("quote_missing")
    elif occurrences > 1:
        issues.append("quote_not_unique")
    if declared_section and actual_section and declared_section != normalize_text(actual_section):
        issues.append(f"section_mismatch:{actual_section}")
    if not declared_section:
        issues.append("section_missing")
    return issues
