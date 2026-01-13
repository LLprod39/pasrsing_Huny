from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from synergy_lms.ai_providers.base import (
    AIChoiceRequest,
    AIChoiceResponse,
    AITextRequest,
    AITextResponse,
    AIOrderRequest,
    AIOrderResponse,
    AIMatchRequest,
    AIMatchResponse,
)


@dataclass(frozen=True)
class GrokConfig:
    api_key: str
    model: str
    base_url: str = "https://api.x.ai/v1"
    timeout_seconds: int = 60


class GrokProvider:
    """Grok (xAI) провайдер. Реализован в OpenAI-compatible формате.

    По умолчанию использует:
      POST {base_url}/chat/completions
      Authorization: Bearer <api_key>
    """

    def __init__(self, cfg: GrokConfig):
        if not cfg.api_key or not cfg.api_key.strip():
            raise ValueError("Grok api_key пустой")
        if not cfg.model or not cfg.model.strip():
            raise ValueError("Grok model пустой")
        self.cfg = cfg

    def _chat(self, system: str, user: str) -> str:
        payload: Dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
        }

        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

        r = requests.post(url, headers=headers, json=payload, timeout=self.cfg.timeout_seconds)
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            # Подмешиваем тело ответа (часто там объяснение: модель/ключ/лимиты/валидаторы)
            body = ""
            try:
                body = (r.text or "")[:2000]
            except Exception:
                body = ""
            raise requests.HTTPError(f"{e} | response_body={body}") from e

        data = r.json()

        return (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )

    def choose(self, req: AIChoiceRequest) -> AIChoiceResponse:
        system = (
            "Ты помощник, который выбирает варианты ответа для теста.\n"
            "Верни СТРОГО JSON без markdown и без пояснений.\n"
            "Формат: {\"choices\": [1]} для одного ответа или {\"choices\": [1,3]} для нескольких.\n"
            "Индексы 1-based и должны соответствовать списку вариантов."
        )
        user_lines = [
            f"Вопрос: {req.question.strip()}",
            f"Режим: {'несколько вариантов (checkbox)' if req.multi_select else 'один вариант (radio)'}",
            "Варианты:",
        ]
        for i, opt in enumerate(req.options, start=1):
            user_lines.append(f"{i}. {opt.strip()}")
        user = "\n".join(user_lines)

        text = self._chat(system=system, user=user)

        parsed = _extract_choices_json(text)
        if not parsed:
            return AIChoiceResponse(choices=[], raw_text=text)

        choices = parsed.get("choices")
        if not isinstance(choices, list):
            return AIChoiceResponse(choices=[], raw_text=text)
        cleaned: list[int] = []
        for c in choices:
            try:
                cleaned.append(int(c))
            except Exception:
                continue

        return AIChoiceResponse(choices=cleaned, raw_text=text)

    def text(self, req: AITextRequest) -> AITextResponse:
        system = (
            "Ты помощник, который даёт текстовые ответы для поля(ей) теста.\n"
            "Верни СТРОГО JSON без markdown и без пояснений.\n"
            "Формат: {\"texts\": [\"...\"]}. Если полей несколько — верни столько же элементов в массиве."
        )
        user_lines = [
            f"Вопрос: {req.question.strip()}",
            f"Количество полей: {int(req.fields)}",
        ]
        user = "\n".join(user_lines)
        text = self._chat(system=system, user=user)
        parsed = _extract_any_json(text)
        if not parsed:
            return AITextResponse(texts=[], raw_text=text)
        texts = parsed.get("texts")
        if not isinstance(texts, list):
            return AITextResponse(texts=[], raw_text=text)
        cleaned: list[str] = []
        for t in texts:
            if t is None:
                cleaned.append("")
            else:
                cleaned.append(str(t))
        return AITextResponse(texts=cleaned, raw_text=text)

    def order(self, req: AIOrderRequest) -> AIOrderResponse:
        system = (
            "Ты помощник, который расставляет элементы в правильном порядке.\n"
            "Верни СТРОГО JSON без markdown и без пояснений.\n"
            "Формат: {\"order\": [2,1,3]} — это порядок индексов 1-based из списка Items."
        )
        user_lines = [f"Задание: {req.question.strip()}", "Items:"]
        for i, it in enumerate(req.items, start=1):
            user_lines.append(f"{i}. {it.strip()}")
        user = "\n".join(user_lines)
        text = self._chat(system=system, user=user)
        parsed = _extract_any_json(text)
        if not parsed:
            return AIOrderResponse(order=[], raw_text=text)
        order = parsed.get("order")
        if not isinstance(order, list):
            return AIOrderResponse(order=[], raw_text=text)
        cleaned: list[int] = []
        for x in order:
            try:
                cleaned.append(int(x))
            except Exception:
                continue
        return AIOrderResponse(order=cleaned, raw_text=text)

    def match(self, req: AIMatchRequest) -> AIMatchResponse:
        system = (
            "Ты помощник, который сопоставляет элементы слева и справа.\n"
            "Верни СТРОГО JSON без markdown и без пояснений.\n"
            "Формат: {\"pairs\": [[1,3],[2,1]]} — пары индексов 1-based: [leftIndex,rightIndex]."
        )
        user_lines = [
            f"Задание: {req.question.strip()}",
            "Left:",
        ]
        for i, it in enumerate(req.left_items, start=1):
            user_lines.append(f"{i}. {it.strip()}")
        user_lines.append("Right:")
        for i, it in enumerate(req.right_items, start=1):
            user_lines.append(f"{i}. {it.strip()}")
        user = "\n".join(user_lines)
        text = self._chat(system=system, user=user)
        parsed = _extract_any_json(text)
        if not parsed:
            return AIMatchResponse(pairs=[], raw_text=text)
        pairs = parsed.get("pairs")
        if not isinstance(pairs, list):
            return AIMatchResponse(pairs=[], raw_text=text)
        cleaned: list[list[int]] = []
        for p in pairs:
            if not isinstance(p, (list, tuple)) or len(p) != 2:
                continue
            try:
                li = int(p[0])
                ri = int(p[1])
            except Exception:
                continue
            cleaned.append([li, ri])
        return AIMatchResponse(pairs=cleaned, raw_text=text)


_JSON_CANDIDATE_RE = re.compile(r"\{[\s\S]*\}")


def _extract_choices_json(text: str) -> Optional[Dict[str, Any]]:
    """Достаём JSON-объект из ответа модели.

    - Может быть мусор вокруг → ищем {...}
    - Пытаемся json.loads на найденном куске
    """
    if not text:
        return None

    m = _JSON_CANDIDATE_RE.search(text)
    if not m:
        return None

    candidate = m.group(0).strip()
    try:
        obj = json.loads(candidate)
    except Exception:
        return None

    if not isinstance(obj, dict):
        return None
    return obj


def _extract_any_json(text: str) -> Optional[Dict[str, Any]]:
    """То же, что и _extract_choices_json, но без привязки к ключу choices."""
    return _extract_choices_json(text)

