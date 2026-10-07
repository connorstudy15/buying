from scripts.eval.run_dual_tower_d0_full import hard_negative_group


def test_hard_negative_group_maps_requested_diagnostic_families():
    assert "same_product_wrong_need" in hard_negative_group("same_attribute_wrong_product", "x.md")
    assert "same_domain_wrong_rule" in hard_negative_group("same_topic_wrong_scope", "x.md")
    assert "keyword_overlap_wrong_answer" in hard_negative_group("title_match_missing_fact", "x.md")
    assert "generic_vs_specific" in hard_negative_group("same_topic_generic", "x.md")
    assert "repeated_template_competition" in hard_negative_group("other", "eval-template.md")
