from __future__ import annotations

from config import Config

from ai_providers.base import AIProvider
from ai_providers.grok import GrokConfig, GrokProvider


def get_ai_provider() -> AIProvider:
    provider = (getattr(Config, "AI_PROVIDER", "") or "").strip().lower()
    if not provider:
        provider = "grok"

    if provider == "grok":
        cfg = GrokConfig(
            api_key=Config.GROK_API_KEY,
            model=Config.GROK_MODEL,
            base_url=Config.GROK_BASE_URL,
            timeout_seconds=Config.AI_TIMEOUT_SECONDS,
        )
        return GrokProvider(cfg)

    raise ValueError(f"Неизвестный AI provider: {provider}")

