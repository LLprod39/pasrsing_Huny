"""
Самопроверка AI-провайдера (Grok/xAI и др.) для всех форматов,
которые используются при прохождении тестов.

Запуск:
  python scripts/ai_selftest.py

Перед запуском убедись, что в .env задано:
  TEST_STRATEGY=ai
  AI_PROVIDER=grok
  GROK_API_KEY=...
  GROK_MODEL=...
  (опционально) GROK_BASE_URL=https://api.x.ai/v1
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from synergy_lms.config import Config
from synergy_lms.ai_providers import (
    AIChoiceRequest,
    AITextRequest,
    AIOrderRequest,
    AIMatchRequest,
    get_ai_provider,
)


def _fail(msg: str, code: int = 2) -> int:
    print(f"[FAIL] {msg}")
    return code


def _ok(msg: str) -> None:
    print(f"[ OK ] {msg}")


def _validate_choices(choices: List[int], n: int, multi: bool) -> None:
    if not choices:
        raise ValueError("choices пустой")
    for c in choices:
        if not isinstance(c, int):
            raise ValueError(f"choice не int: {c!r}")
        if c < 1 or c > n:
            raise ValueError(f"choice вне диапазона 1..{n}: {c}")
    if not multi and len(choices) != 1:
        raise ValueError(f"для single-select ожидался 1 choice, получено: {choices}")


def _validate_texts(texts: List[str], fields: int) -> None:
    if not texts:
        raise ValueError("texts пустой")
    if len(texts) < fields:
        raise ValueError(f"texts меньше чем fields ({len(texts)} < {fields})")
    for t in texts[:fields]:
        if not isinstance(t, str):
            raise ValueError(f"text не str: {t!r}")


def _validate_order(order: List[int], n: int) -> None:
    if not order:
        raise ValueError("order пустой")
    cleaned = [x for x in order if isinstance(x, int) and 1 <= x <= n]
    if len(cleaned) < n:
        raise ValueError(f"order не покрывает все элементы 1..{n}: {order}")
    # допускаем хвост, но первые n должны быть перестановкой
    head = cleaned[:n]
    if sorted(head) != list(range(1, n + 1)):
        raise ValueError(f"order (первые {n}) не является перестановкой 1..{n}: {head}")


def _validate_pairs(pairs: List[List[int]], nl: int, nr: int) -> None:
    if not pairs:
        raise ValueError("pairs пустой")
    for p in pairs:
        if not isinstance(p, list) or len(p) != 2:
            raise ValueError(f"пара должна быть [li, ri], получено: {p!r}")
        li, ri = p
        if not isinstance(li, int) or not isinstance(ri, int):
            raise ValueError(f"индексы пары должны быть int: {p!r}")
        if li < 1 or li > nl or ri < 1 or ri > nr:
            raise ValueError(f"индексы пары вне диапазона left=1..{nl}, right=1..{nr}: {p!r}")


def main() -> int:
    ap = argparse.ArgumentParser(description="AI self-test for all test formats")
    ap.add_argument("--timeout", type=int, default=None, help="Override AI timeout seconds")
    args = ap.parse_args()

    if args.timeout is not None:
        # переопределение только на время запуска
        Config.AI_TIMEOUT_SECONDS = int(args.timeout)

    try:
        provider = get_ai_provider()
    except Exception as e:
        return _fail(f"Не удалось инициализировать AI provider: {e}")

    _ok(f"Провайдер инициализирован: {Config.AI_PROVIDER}")
    _ok(f"Модель: {getattr(Config, 'GROK_MODEL', '') or '(n/a)'}")

    # 1) Single choice (radio)
    try:
        req = AIChoiceRequest(
            question="Тест single-choice: выбери вариант 'Синий'.",
            options=["Красный", "Синий", "Зелёный"],
            multi_select=False,
        )
        resp = provider.choose(req)
        _validate_choices(resp.choices, n=len(req.options), multi=False)
        _ok(f"choose(single) -> choices={resp.choices} raw={bool(resp.raw_text)}")
    except Exception as e:
        return _fail(f"choose(single) не прошёл: {e}")

    # 2) Multi choice (checkbox)
    try:
        req = AIChoiceRequest(
            question="Тест multi-choice: выбери ВСЕ варианты, которые являются простыми числами.",
            options=["2", "3", "4", "5", "6"],
            multi_select=True,
        )
        resp = provider.choose(req)
        _validate_choices(resp.choices, n=len(req.options), multi=True)
        _ok(f"choose(multi)  -> choices={resp.choices} raw={bool(resp.raw_text)}")
    except Exception as e:
        return _fail(f"choose(multi) не прошёл: {e}")

    # 3) Text answer
    try:
        req = AITextRequest(
            question="Тест text: кратко ответь одним предложением: что такое философия?",
            fields=1,
        )
        resp = provider.text(req)
        _validate_texts(resp.texts, fields=req.fields)
        _ok(f"text(fields=1) -> text='{resp.texts[0][:80]}' raw={bool(resp.raw_text)}")
    except Exception as e:
        return _fail(f"text(fields=1) не прошёл: {e}")

    # 4) Order (sorting)
    try:
        items = ["второй", "первый", "третий"]
        req = AIOrderRequest(
            question="Тест order: отсортируй элементы по смысловому порядку: первый, второй, третий.",
            items=items,
        )
        resp = provider.order(req)
        _validate_order(resp.order, n=len(items))
        _ok(f"order(n=3)     -> order={resp.order} raw={bool(resp.raw_text)}")
    except Exception as e:
        return _fail(f"order не прошёл: {e}")

    # 5) Match (pairs)
    try:
        left = ["2+2", "3+3", "5+5"]
        right = ["10", "4", "6"]
        req = AIMatchRequest(
            question="Тест match: сопоставь выражение слева с правильным значением справа.",
            left_items=left,
            right_items=right,
        )
        resp = provider.match(req)
        _validate_pairs(resp.pairs, nl=len(left), nr=len(right))
        _ok(f"match          -> pairs={resp.pairs} raw={bool(resp.raw_text)}")
    except Exception as e:
        return _fail(f"match не прошёл: {e}")

    _ok("Все проверки AI успешно пройдены.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

