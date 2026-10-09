"""Preserve transport statuses and audit observable main lifecycle completion."""
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    by_trace = {row["trace_id"]: row for row in report["request_rows"]}
    observations = []
    for item in manifest["observations"]:
        request = by_trace.get(item["trace_id"], {})
        complete = request.get("execution_status") != "ERROR" and any(
            row.get("after", {}).get("flow_id") == "main"
            and row["after"].get("last_operation") == "main.final"
            for row in request.get("runtime_progress_events", [])
        )
        observations.append({**item, "transport_reported_status": item["status"],
                             "status": "success" if complete else "error",
                             "completion_evidence": "main.final observed" if complete else "main.final absent or turn ERROR",
                             "training_eligible": complete})
    args.output.write_text(json.dumps({
        "observations": observations, "attempted": len(observations),
        "valid_completed": sum(row["training_eligible"] for row in observations),
        "source_manifest": str(args.manifest), "source_report": str(args.report),
        "shadow_only": True, "phase3": "NO_GO",
        "caveat": "Lifecycle completion is not retrieval relevance or answer correctness.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
