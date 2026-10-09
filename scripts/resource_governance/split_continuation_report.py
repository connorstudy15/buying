"""Apply a prespecified case split without fitting or inspecting validation labels."""
import argparse
import json
from pathlib import Path


def split_report(report, specification):
    calibration = set(specification["calibration"])
    validation = set(specification["validation"])
    if calibration & validation:
        raise ValueError("calibration/validation case overlap")
    rows = report["request_rows"]
    observed = [row["case_id"] for row in rows]
    if len(observed) != len(set(observed)):
        raise ValueError("this targeted split expects one trace per case")
    if set(observed) != calibration | validation:
        raise ValueError("observed cases differ from the prespecified split")
    def completed(row):
        return row.get("execution_status") != "ERROR" and any(
            event.get("after", {}).get("flow_id") == "main"
            and event["after"].get("last_operation") == "main.final"
            for event in row.get("runtime_progress_events", [])
        )
    return {
        name: {"request_rows": [row for row in rows if row["case_id"] in ids
                                and completed(row)],
               "excluded_failed_or_incomplete_cases": [row["case_id"] for row in rows
                                                        if row["case_id"] in ids and not completed(row)],
               "shadow_only": True, "split_source": "prespecified case IDs"}
        for name, ids in (("calibration", calibration), ("validation", validation))
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    outputs = split_report(json.loads(args.input.read_text(encoding="utf-8")),
                           json.loads(args.split.read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in outputs.items():
        (args.output_dir / f"{name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir / "valid.json").write_text(json.dumps({
        "request_rows": [row for payload in outputs.values() for row in payload["request_rows"]],
        "shadow_only": True,
        "excluded_failed_or_incomplete_cases": [case for payload in outputs.values()
                                                for case in payload["excluded_failed_or_incomplete_cases"]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: len(payload["request_rows"]) for name, payload in outputs.items()}))


if __name__ == "__main__":
    main()
