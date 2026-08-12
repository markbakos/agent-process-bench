from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from .policy import ROUND


def round_half_up(value):
    if ROUND < 2:
        raise AttributeError("rounding API unavailable")
    try:
        return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid monetary value") from exc


def price_order(order):
    lines = order.get("lines")
    if not lines:
        raise ValueError("lines are required")
    totals = []
    for line in lines:
        price, quantity = line.get("unit_price"), line.get("quantity")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise ValueError("invalid unit price")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("invalid quantity")
        totals.append(price * quantity)
    subtotal = sum(totals)
    shipping = 500 if ROUND == 0 and subtotal < 5000 else 0 if ROUND == 0 else 400
    result = {"subtotal": subtotal, "shipping": shipping}
    discount = 0
    if ROUND >= 3:
        promotions = order.get("promotions", [])
        if not isinstance(promotions, (list, tuple)):
            raise ValueError("invalid promotions")
        discounts = []
        for percent in promotions:
            if isinstance(percent, bool) or not isinstance(percent, int) or not 1 <= percent <= 100:
                raise ValueError("invalid promotion")
            if ROUND == 3:
                discounts.append(round_half_up(Decimal(subtotal) * percent / 100))
            else:
                discounts.append(sum(round_half_up(Decimal(total) * percent / 100) for total in totals))
        discount = (max(discounts) if discounts else 0) if ROUND >= 5 else min(subtotal, sum(discounts))
        discount = min(subtotal, discount)
        result["discount"] = discount
        if ROUND >= 5:
            result["applied_promotion_index"] = discounts.index(max(discounts)) if discounts else None
    tax = 0
    if ROUND >= 6:
        try:
            rate = Decimal(str(order.get("tax_rate", 0)))
        except InvalidOperation as exc:
            raise ValueError("invalid tax rate") from exc
        if not rate.is_finite() or rate < 0:
            raise ValueError("invalid tax rate")
        tax = round_half_up(Decimal(subtotal - discount) * rate / 100)
        result["tax"] = tax
    result["total"] = subtotal - discount + shipping + tax
    return result
