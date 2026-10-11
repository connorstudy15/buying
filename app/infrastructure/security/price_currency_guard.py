"""Correct only uniquely proven currency labels; never infer an amount."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re

_PRODUCT = re.compile(r"(?<![A-Za-z0-9])P\d{4,}(?:-S\d+)?(?![A-Za-z0-9])")
_AMOUNT = r"\d+(?:,\d{3})*(?:\.\d+)?"
_MONEY = re.compile(rf"(?P<prefix>(?<![A-Za-z])[A-Z]{{3}})(?P<gap>\s*)(?P<amount>{_AMOUNT})(?![\d.])|(?<![\w.])(?P<amount_last>{_AMOUNT})(?P<gap_last>\s*)(?P<suffix>[A-Z]{{3}})(?![A-Za-z])")


def correct_price_currencies(text: str, result: dict | None) -> tuple[str, int]:
    if not text or not result:
        return text, 0
    known = {}
    for card in result.get("hits", []):
        values = defaultdict(set)
        def add(value, currency):
            if value is None or not isinstance(currency, str):
                return
            try:
                number = Decimal(str(value))
                if number.is_finite():
                    values[number].add(currency)
            except InvalidOperation:
                pass
        add(card.get("price_major"), card.get("currency"))
        add(card.get("source_price_major"), card.get("source_currency"))
        for sku in card.get("skus", []):
            add(sku.get("price_major"), sku.get("currency"))
            target = sku.get("target_price") or {}
            add(target.get("price_major"), target.get("currency"))
        for quote in [card.get("landed_price"), *[s.get("landed_price") for s in card.get("skus", [])]]:
            if isinstance(quote, dict):
                for field in ("subtotal_major", "freight_major", "tariff_major", "landed_total_major"):
                    add(quote.get(field), quote.get("currency"))
        known[card.get("product_id")] = values
    count = 0
    parts, end = [], 0
    identifiers = list(_PRODUCT.finditer(text))
    for index, identifier in enumerate(identifiers):
        stop = identifiers[index + 1].start() if index + 1 < len(identifiers) else len(text)
        parts.append(text[end:identifier.end()])
        segment = text[identifier.end():stop]
        values = known.get(identifier.group().split("-S")[0], {})
        def replace(match):
            nonlocal count
            label = segment[max(0, match.start() - 20):match.start()]
            if not any(word in label for word in ("原价", "源价", "参考价", "平台价")):
                return match.group()
            value = Decimal((match["amount"] or match["amount_last"]).replace(",", ""))
            currencies = values.get(value, set())
            claimed = match["prefix"] or match["suffix"]
            if len(currencies) != 1 or claimed in currencies:
                return match.group()
            # Only ISO currencies seen in the catalogue are eligible labels.
            if claimed not in {"CNY", "USD", "EUR", "GBP", "JPY", "SGD", "HKD", "AUD", "CAD"}:
                return match.group()
            correct = next(iter(currencies))
            count += 1
            return (correct + match["gap"] + match["amount"] if match["prefix"]
                else match["amount_last"] + match["gap_last"] + correct)
        parts.append(_MONEY.sub(replace, segment))
        end = stop
    parts.append(text[end:])
    return "".join(parts), count


def correct_landed_price_comparisons(text: str, result: dict | None) -> tuple[str, int]:
    """Correct a scoped batch extremum only when every comparable quote is known."""
    cards = (result or {}).get("hits", [])
    if len(cards) < 2:
        return text, 0
    quotes = {}
    for card in cards:
        quote = card.get("landed_price") or {}
        try:
            amount = Decimal(str(quote["landed_total_major"]))
            currency, destination = quote["currency"], quote["ship_to"]
        except (KeyError, InvalidOperation):
            return text, 0
        if not amount.is_finite() or not currency or not destination:
            return text, 0
        quotes[card["product_id"]] = (amount, currency, destination)
    if len(quotes) != len(cards) or len({value[1:] for value in quotes.values()}) != 1:
        return text, 0
    counts = {str(len(cards)), {2: "两", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九", 10: "十"}.get(len(cards), "")}
    claims = re.compile(r"(?P<count>[一二两三四五六七八九十\d]+)款中到手价最(?P<kind>低|高)")
    identifiers = list(_PRODUCT.finditer(text))
    parts, end, corrections = [], 0, 0
    for index, identifier in enumerate(identifiers):
        stop = identifiers[index + 1].start() if index + 1 < len(identifiers) else len(text)
        parts.append(text[end:identifier.end()])
        segment = text[identifier.end():stop]
        current = quotes.get(identifier.group().split("-S")[0])
        def replace(match):
            nonlocal corrections
            if current is None or match["count"] not in counts:
                return match.group()
            extreme = (min if match["kind"] == "低" else max)(value[0] for value in quotes.values())
            winners = [product for product, value in quotes.items() if value[0] == extreme]
            if current[0] == extreme or len(winners) != 1:
                return match.group()
            corrections += 1
            return f"到手价 {current[1]}{current[0]:.2f}（本轮最{match['kind']}为 {winners[0]}：{current[1]}{extreme:.2f}）"
        parts.append(claims.sub(replace, segment))
        end = stop
    parts.append(text[end:])
    return "".join(parts), corrections
