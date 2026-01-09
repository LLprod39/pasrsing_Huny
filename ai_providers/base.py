from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol


@dataclass(frozen=True)
class AIChoiceRequest:
    """Запрос к AI: выбрать варианты ответа по вопросу."""

    question: str
    options: List[str]
    multi_select: bool


@dataclass(frozen=True)
class AIChoiceResponse:
    """Ответ AI: список выбранных индексов (1-based)."""

    choices: List[int]
    raw_text: str | None = None


class AIProvider(Protocol):
    """Интерфейс провайдера AI (расширяемый)."""

    def choose(self, req: AIChoiceRequest) -> AIChoiceResponse: ...

