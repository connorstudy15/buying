from scripts.eval.run_dual_tower_native_symmetric_control import top20_comparison


def test_top20_comparison_keeps_three_arms_separate():
    queries = [{"query_id": "v4-006::original", "case_id": "v4-006"}]
    def ranking(label):
        return [{"query_id": "v4-006::original", "candidates": [{"candidate_id": label}]}]
    result = top20_comparison("v4-006", queries, ranking("legacy"), ranking("symmetric"), ranking("role"))
    assert result["arms"]["B0-compatible"]["v4-006::original"][0]["candidate_id"] == "legacy"
    assert result["arms"]["B0-native-symmetric"]["v4-006::original"][0]["candidate_id"] == "symmetric"
    assert result["arms"]["D0-role"]["v4-006::original"][0]["candidate_id"] == "role"
