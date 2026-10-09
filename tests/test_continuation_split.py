import pytest

from scripts.resource_governance.split_continuation_report import split_report


def test_prespecified_split_requires_exact_disjoint_cases():
    terminal = {"after": {"flow_id": "main", "last_operation": "main.final"}}
    a = {"case_id": "a", "runtime_progress_events": [terminal]}
    b = {"case_id": "b", "runtime_progress_events": [terminal]}
    report = {"request_rows": [a, b]}
    specification = {"calibration": ["a"], "validation": ["b"]}
    result = split_report(report, specification)
    assert result["calibration"]["request_rows"] == [a]
    assert result["validation"]["request_rows"] == [b]
    with pytest.raises(ValueError, match="overlap"):
        split_report(report, {"calibration": ["a"], "validation": ["a", "b"]})
    with pytest.raises(ValueError, match="differ"):
        split_report({"request_rows": [{"case_id": "a"}]}, specification)
    with pytest.raises(ValueError, match="one trace"):
        split_report({"request_rows": [{"case_id": "a"}, {"case_id": "a"}]}, specification)


def test_failed_request_is_not_a_completed_training_example():
    result = split_report({"request_rows": [
        {"case_id": "a", "execution_status": "ERROR"},
        {"case_id": "b", "execution_status": "SUCCESS"},
    ]}, {"calibration": ["a"], "validation": ["b"]})
    assert result["calibration"]["request_rows"] == []
    assert result["calibration"]["excluded_failed_or_incomplete_cases"] == ["a"]
