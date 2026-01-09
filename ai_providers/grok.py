from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from ai_providers.base import AIChoiceRequest, AIChoiceResponse


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
        r.raise_for_status()
        data = r.json()

        text = (
            (data.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )

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

