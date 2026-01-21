from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


_CURRENCY_SYMBOLS: dict[str, str] = {
    "rub": "₽",
    "rur": "₽",
    "usd": "$",
    "eur": "€",
    "gbp": "£",
}


@register.filter(name="money_from_cents")
def money_from_cents(value, currency: str | None = None) -> str:
    """
    Format integer cents into human readable amount with currency symbol.

    Examples:
      9900, "rub" -> "99 ₽"
      1050, "usd" -> "10,50 $"
    """
    try:
        cents = int(value or 0)
    except Exception:
        cents = 0

    try:
        major = (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))
    except (InvalidOperation, Exception):
        major = Decimal("0.00")

    if cents % 100 == 0:
        amount = f"{int(major):,}".replace(",", " ")
    else:
        amount = f"{major:,.2f}".replace(",", " ").replace(".", ",")

    cur = (currency or "").strip().lower()
    symbol = _CURRENCY_SYMBOLS.get(cur)
    if not symbol:
        symbol = (currency or "").strip().upper()

    if symbol:
        return f"{amount} {symbol}"
    return amount

