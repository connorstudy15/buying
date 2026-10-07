from scripts.eval.audit_knowledge_corpus_provenance import template_slot


def test_template_slot_groups_category_and_policy_documents():
    assert template_slot("eval-travel-gear-overview.md", 2) == "category-template::overview::chunk-2"
    assert template_slot("eval-home-living-overview.md", 2) == "category-template::overview::chunk-2"
    assert template_slot("eval-policy-us.md", 1) == "policy-template::chunk-1"
    assert template_slot("travel-gear.md", 0) is None
