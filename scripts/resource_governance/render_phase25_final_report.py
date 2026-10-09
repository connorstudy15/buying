"""Render the required 24-section Phase 2.5 Go/No-Go report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _metrics_table(metrics: dict[str, Any] | None) -> list[str]:
    metrics = metrics or {}
    keys = (
        "n", "actual_p50", "actual_p80", "actual_p95", "predicted_p50",
        "predicted_p80", "predicted_p95", "mae", "mape",
        "underprediction_rate", "underprediction_p50", "underprediction_p80",
        "underprediction_p95", "underprediction_max", "overprediction_rate",
        "overprediction_p50", "overprediction_p95", "latency_p50", "latency_p95",
    )
    return ["| Metric | Value |", "|---|---:|", *[f"| {key} | {_value(metrics.get(key))} |" for key in keys]]


def render(report: dict[str, Any]) -> str:
    golden = report.get("golden_tokenizer_parity") or {}
    quality = report.get("retrieval_quality") or {}
    quality_summary = quality.get("metrics") or quality.get("execution") or {
        "runs": [
            {
                "repetition": run.get("repetition"),
                "candidate_b": (run.get("decompose_per_need_rerank") or {}).get("metrics"),
                "paired_vs_legacy": (run.get("decompose_per_need_rerank") or {}).get("paired_vs_legacy"),
            }
            for run in quality.get("runs", [])
        ],
    }
    sections: list[tuple[str, list[str]]] = []
    sections.append(("1. Golden Prompt/Token parity 结果", [
        f"- Gate: **{'PASS' if report.get('golden_tokenizer_parity_passed') else 'FAIL/BLOCKED'}**",
        f"- Official comparable cases: {_value((golden.get('summary') or {}).get('n'))}/14",
        f"- PRIMARY: `{golden.get('primary_enabled', False)}`",
    ]))
    sections.append(("2. DeepSeek V4.1 tokenizer vs fallback vs Provider actual", [
        f"- Official tokenizer: `{(golden.get('tokenizer_status') or {}).get('high_confidence_ready')}`",
        f"- Fallback MAE: {_value((golden.get('fallback_summary') or {}).get('mae'))}",
        f"- Fallback MAPE: {_value((golden.get('fallback_summary') or {}).get('mape'))}",
        f"- Fallback P95 delta ratio: {_value((golden.get('fallback_summary') or {}).get('delta_ratio_p95'))}",
    ]))
    sections.append(("3. Tokenizer calibration sample/confidence", [
        f"- Distribution: `{json.dumps(report.get('profile_confidence_distribution') or {}, ensure_ascii=False)}`",
        "- HIGH requires >=100 observations *and* an approved parity/residual gate.",
    ]))
    accounting = report.get("accounting") or {}
    sections.append(("4. Accounting reconciliation", [
        f"- Errors: {_value(accounting.get('error_count'))}",
        f"- Reservation leaks: {_value(accounting.get('reservation_leak_count'))}",
        f"- Duplicate attempts: {_value(accounting.get('duplicate_attempt_count'))}",
        f"- Stale executions: {_value(accounting.get('stale_plan_execution_count'))}",
    ]))
    sections.append(("5. 67×2 总体结果", [
        f"- Traces: {_value(report.get('trace_count'))}",
        f"- Unique cases: {_value(report.get('unique_case_count'))}",
        f"- Minimum repetitions: {_value(report.get('minimum_case_repetitions'))}",
        *_metrics_table(report.get("request_prediction")),
    ]))
    buckets = report.get("benchmark_buckets") or {}
    for number, name in ((6, "Single Evidence"), (7, "Cross Evidence"), (8, "Multi-hop"),
                         (9, "DIRECT / REWRITE / DECOMPOSE")):
        if number == 9:
            body = []
            for item in ("DIRECT", "REWRITE", "DECOMPOSE"):
                body += [f"### {item}", *_metrics_table(buckets.get(item))]
        else:
            body = _metrics_table(buckets.get(name))
        sections.append((f"{number}. {name}", body))
    sections.append(("10. Operation-level prediction error", [
        f"```json\n{json.dumps(report.get('operation_error_attribution') or {}, ensure_ascii=False, indent=2)}\n```",
    ]))
    sections.append(("11. Main Plan error", _metrics_table(report.get("main_plan_prediction"))))
    sections.append(("12. Main Final error", _metrics_table(report.get("main_final_prediction"))))
    sections.append(("13. Context growth error", [
        f"```json\n{json.dumps(report.get('context_projection_error') or {}, ensure_ascii=False, indent=2)}\n```",
    ]))
    attribution = report.get("operation_error_attribution") or {}
    sections.append(("14. Route / operation-count error", [
        f"- route_selection_error: `{json.dumps(attribution.get('route_selection_error'), ensure_ascii=False)}`",
        f"- operation_count_error: `{json.dumps(attribution.get('operation_count_error'), ensure_ascii=False)}`",
        f"- missing_operation_count: `{json.dumps(attribution.get('missing_operation_count'), ensure_ascii=False)}`",
        f"- unexpected_operation_count: `{json.dumps(attribution.get('unexpected_operation_count'), ensure_ascii=False)}`",
    ]))
    request = report.get("request_prediction") or {}
    sections.append(("15. Underprediction rate", [f"- {_value(request.get('underprediction_rate'))}"]))
    sections.append(("16. P95 underprediction shortfall", [
        f"- Overall tokens: {_value(request.get('underprediction_p95'))}",
        f"- Overall ratio: {_value(request.get('underprediction_ratio_p95'))}",
        f"- Main Final ratio: {_value((report.get('main_final_prediction') or {}).get('underprediction_ratio_p95'))}",
    ]))
    sections.append(("17. Planned Budget exceed rate", [f"- {_value(report.get('planned_budget_exceed_rate'))}"]))
    sections.append(("18. 80K hard-cap shadow exceed rate", [f"- {_value(report.get('hard_cap_80k_exceed_rate'))}"]))
    sections.append(("19. Retrieval Quality Regression", [
        f"- Gate: **{'PASS' if report.get('retrieval_quality_regression_passed') else 'FAIL/NOT_RUN'}**",
        f"```json\n{json.dumps(quality_summary, ensure_ascii=False, indent=2)}\n```",
    ]))
    sections.append(("20. Profile confidence distribution", [
        f"```json\n{json.dumps(report.get('profile_confidence_distribution') or {}, ensure_ascii=False, indent=2)}\n```",
    ]))
    sections.append(("21. 哪些 Profile 已可 action-driving", [
        "- 只有 parity/residual Gate 通过且标记 HIGH 的 profile；本轮 Phase 3 未开启。",
    ]))
    sections.append(("22. 哪些必须继续 shadow", [
        "- BOOTSTRAP/LOW 全部；MEDIUM 仅可用于未来 optional/speculative reservation；Main Final 与 mandatory 始终保护。",
    ]))
    primary_go = bool(report.get("golden_tokenizer_parity_passed")) and (
        (golden.get("tokenizer_status") or {}).get("high_confidence_ready") is True
    )
    sections.append(("23. DEEPSEEK_V41_TOKENIZER_PRIMARY 是否可以 0 → 1", [
        f"- **{'YES' if primary_go else 'NO'}**",
    ]))
    phase3 = report.get("phase3_gate") or {}
    sections.append(("24. Phase 3：GO / NO_GO", [
        f"- **{phase3.get('decision', 'NO_GO')}**",
        f"```json\n{json.dumps(phase3.get('conditions') or {}, ensure_ascii=False, indent=2)}\n```",
        "- 即使未来 GO，第一阶段也只允许影响 optional/speculative，不控制 mandatory flow。",
    ]))
    lines = ["# Token Budget × Context Governance Phase 2.5 最终报告", "", "Governor mode: **shadow-only**", ""]
    for title, body in sections:
        lines.extend([f"## {title}", "", *body, ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.input.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(report), encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
