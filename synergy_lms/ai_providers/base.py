from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, Protocol


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


@dataclass(frozen=True)
class AITextRequest:
    """Запрос к AI: сгенерировать текстовый ответ(ы) для вопроса/поля ввода."""

    question: str
    fields: int = 1


@dataclass(frozen=True)
class AITextResponse:
    """Ответ AI: текст или список текстов (если несколько полей)."""

    texts: List[str]
    raw_text: str | None = None


@dataclass(frozen=True)
class AIOrderRequest:
    """Запрос к AI: расставить элементы в правильном порядке (сортировка)."""

    question: str
    items: List[str]


@dataclass(frozen=True)
class AIOrderResponse:
    """Ответ AI: порядок элементов (1-based индексы)."""

    order: List[int]
    raw_text: str | None = None


@dataclass(frozen=True)
class AIMatchRequest:
    """Запрос к AI: сопоставить элементы слева/справа (drag&drop matching)."""

    question: str
    left_items: List[str]
    right_items: List[str]


@dataclass(frozen=True)
class AIMatchResponse:
    """Ответ AI: пары [leftIndex, rightIndex] (1-based индексы)."""

    pairs: List[List[int]]
    raw_text: str | None = None


class AIProvider(Protocol):
    """Интерфейс провайдера AI (расширяемый)."""

    def choose(self, req: AIChoiceRequest) -> AIChoiceResponse: ...
    def text(self, req: AITextRequest) -> AITextResponse: ...
    def order(self, req: AIOrderRequest) -> AIOrderResponse: ...
    def match(self, req: AIMatchRequest) -> AIMatchResponse: ...

