from app.infrastructure.security.price_currency_guard import correct_price_currencies, correct_landed_price_comparisons


def card(amount=22.26, currency="SGD"):
    return {"hits": [{"product_id": "P3496", "source_price_major": amount, "source_currency": currency,
        "price_major": 117.98, "currency": "CNY", "skus": []}]}


def test_source_currency_correction_preserves_amount_and_other_content():
    text = "P3496 宠物包\n参考价约 USD 22.26，商品价 CNY117.98；运费65元。"
    assert correct_price_currencies(text, card()) == (text.replace("USD", "SGD"), 1)


def test_correct_and_unverified_prices_and_budget_are_untouched():
    for text in ("P3496 原价 SGD22.26", "P3496 原价 USD99", "P3496 预算 USD22.26", "P9999 原价 USD22.26", "原价 USD22.26"):
        assert correct_price_currencies(text, card()) == (text, 0)


def test_ambiguous_amount_is_never_guessed():
    data = card()
    data["hits"][0]["skus"].append({"price_major": 22.26, "currency": "EUR"})
    text = "P3496 参考价USD22.26"
    assert correct_price_currencies(text, data) == (text, 0)


def test_each_product_uses_its_own_source_currency():
    data = card()
    data["hits"].append({"product_id": "P3498", "source_price_major": 22.26, "source_currency": "USD"})
    text = "P3496 参考价USD22.26；P3498 参考价USD22.26"
    assert correct_price_currencies(text, data) == (text.replace("参考价USD", "参考价SGD", 1), 1)


def quotes():
    return {"hits": [{"product_id": product, "landed_price": {"landed_total_major": amount, "currency": "CNY", "ship_to": "CN"}}
        for product, amount in (("P3274", 216), ("P3273", 209.02), ("P3272", 202))]}


def test_incorrect_batch_extremum_is_corrected_from_complete_quotes():
    text = "P3274 推荐理由：三款中到手价最低，玻璃瓶体。P3272 三款中到手价最低。"
    corrected, count = correct_landed_price_comparisons(text, quotes())
    assert count == 1
    assert "到手价 CNY216.00（本轮最低为 P3272：CNY202.00）" in corrected
    assert corrected.endswith("P3272 三款中到手价最低。")


def test_partial_mixed_currency_or_different_destination_quotes_do_not_guess():
    for change in ({}, {"landed_total_major": 202, "currency": "USD", "ship_to": "CN"},
                   {"landed_total_major": 202, "currency": "CNY", "ship_to": "US"}):
        data = quotes()
        data["hits"][-1]["landed_price"] = change
        text = "P3274 三款中到手价最低。"
        assert correct_landed_price_comparisons(text, data) == (text, 0)


def test_different_scope_and_unknown_product_comparisons_are_untouched():
    for text in ("P3274 五款中到手价最低", "P9999 三款中到手价最低", "三款中到手价最低"):
        assert correct_landed_price_comparisons(text, quotes()) == (text, 0)

