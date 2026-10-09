"""Fit separate calibration traces and evaluate heldout causal snapshots."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.infrastructure.resource_governance.continuation import (
    ContinuationDiagnostics, TransitionProfileStore, training_samples,
)


def _requests(payload):
    if isinstance(payload, list):
        return payload
    if "request_rows" in payload:
        return payload["request_rows"]
    return payload["requests"]


def evaluate(store: TransitionProfileStore, requests: list[dict]) -> dict:
    samples = training_samples(requests)
    if ({sample.group_id for sample in samples} & store.groups
            or {sample.trace_id for sample in samples} & store.trace_ids):
        raise ValueError("calibration/validation overlap: trace or case group")
    predictor = ContinuationDiagnostics(store)
    rows = []
    for sample in samples:
        if sample.state.get("last_operation") in {"main.final", "search.final", "trade.final"}:
            continue  # Do not inflate accuracy with trivial protocol END labels.
        prediction = predictor.predict(sample.state)
        next_prediction = prediction["next_operation"]
        ranking = sorted(next_prediction["distribution"], key=lambda key: (-next_prediction["distribution"][key], key))
        row = {"trace_id": sample.trace_id, "case_id": sample.group_id, "flow_id": sample.flow_id,
               "sequence": sample.sequence, "prediction": prediction, "actual_next_operation": sample.next_operation,
               "next_top1_correct": ranking[0] == sample.next_operation if sample.next_operation else None,
               "next_top3_correct": sample.next_operation in ranking[:3] if sample.next_operation else None,
               "confidence": next_prediction["confidence"], "last_operation": sample.state["last_operation"]}
        for role, actual in (("main", sample.remaining_main_plan_rounds), ("search", sample.remaining_search_plan_rounds)):
            predicted = prediction["remaining_rounds"][role]
            row[role] = {"actual": actual, **predicted,
                         "absolute_error": abs(predicted["expected"] - actual) if predicted["expected"] is not None and actual is not None else None}
        rows.append(row)

    def summary(group):
        labeled = [row for row in group if row["next_top1_correct"] is not None]
        output = {"N": len(group), "next_labeled_N": len(labeled),
                  "next_top1_accuracy": sum(row["next_top1_correct"] for row in labeled) / len(labeled) if labeled else None,
                  "next_top3_recall": sum(row["next_top3_correct"] for row in labeled) / len(labeled) if labeled else None}
        for role in ("main", "search"):
            measured = [row[role] for row in group if row[role]["absolute_error"] is not None]
            bins = defaultdict(list)
            for row in measured:
                p = row["probability_another"]
                if p is not None:
                    bins[min(9, int(p * 10))].append(row)
            output[role] = {"round_count_evaluable_N": len(measured),
                            "remaining_round_count_MAE": sum(row["absolute_error"] for row in measured) / len(measured) if measured else None,
                            "continuation_calibration": [{"decile": key, "N": len(values),
                                "predicted_probability_mean": sum(row["probability_another"] for row in values) / len(values),
                                "actual_continuation_rate": sum(row["actual"] > 0 for row in values) / len(values)} for key, values in sorted(bins.items())]}
            for quantile in ("p50", "p80", "p95"):
                supported = [row for row in measured if row[quantile] is not None]
                output[role][f"{quantile}_coverage_N"] = len(supported)
                output[role][f"{quantile}_empirical_coverage"] = sum(row["actual"] <= row[quantile] for row in supported) / len(supported) if supported else None
        return output

    return {"phase3_decision": "NO_GO", "shadow_only": True, "action_driving": False,
            "scope": "same_flow_observable_completion; not HTTP invocation order or request-wide graph",
            "validation_trace_count": len({s.trace_id for s in samples}),
            "calibration_trace_count": len(store.trace_ids),
            "summary": summary(rows),
            "confidence_buckets": {key: summary([row for row in rows if row["confidence"] == key])
                                   for key in ("BOOTSTRAP", "LOW", "MEDIUM", "HIGH")},
            "operation_buckets": {key: summary([row for row in rows if row["last_operation"] == key])
                                  for key in sorted({row["last_operation"] for row in rows})},
            "case_buckets": {key: summary([row for row in rows if row["case_id"] == key])
                             for key in sorted({row["case_id"] for row in rows})},
            "rows": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile-output", type=Path, required=True)
    args = parser.parse_args()
    calibration = _requests(json.loads(args.calibration.read_text(encoding="utf-8")))
    validation = _requests(json.loads(args.validation.read_text(encoding="utf-8")))
    # Guard even traces without usable instrumentation; don't silently allow overlap.
    def groups(requests):
        return {str(r.get("case_id") or r.get("group_id") or r.get("trace_id")) for r in requests}
    if groups(calibration) & groups(validation):
        raise ValueError("case/group overlap before feature extraction")
    store = TransitionProfileStore()
    store.fit(training_samples(calibration))
    report = evaluate(store, validation)
    baseline = evaluate(TransitionProfileStore(), validation)
    report["bootstrap_baseline_summary"] = baseline["summary"]
    report["bootstrap_baseline_case_buckets"] = baseline["case_buckets"]
    if not store.trace_ids or not report["validation_trace_count"]:
        report["status"] = "NOT_AVAILABLE_NO_COMPLETE_INSTRUMENTATION"
    else:
        report["status"] = "OFFLINE_DIAGNOSTIC_ONLY"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.profile_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.profile_output.write_text(json.dumps(store.write_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "phase3": "NO_GO", "summary": report["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
