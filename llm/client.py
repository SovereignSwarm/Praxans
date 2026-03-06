"""Unified Ollama client wrapper for the Thronglets LLM subsystem.

Replaces the six top-level LLM helper functions that were in thronglets_game.py:
  get_ollama_client, get_fastest_available_model, get_ollama_options,
  sanitize_llm_response, generate_ollama_text, start_async_llm_job

Usage from the scheduler:
    client = OllamaClient(preferred_model="qwen3.5:9b")
    text, model = client.generate(prompt, options={...})
"""

from __future__ import annotations

import logging
import re
import time
import threading
from typing import Any

from runtime_config import USER_SETTINGS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Response sanitisation
# ---------------------------------------------------------------------------

def sanitize_llm_response(response_text: str | None) -> str:
    """Strip Qwen thinking tags and markdown wrappers before parsing."""
    if not response_text:
        return ""
    cleaned = re.sub(
        r"<think>.*?</think>", "", response_text, flags=re.IGNORECASE | re.DOTALL
    )
    if re.search(r"</think>", cleaned, flags=re.IGNORECASE):
        cleaned = re.split(r"</think>", cleaned, maxsplit=1, flags=re.IGNORECASE)[-1]
    cleaned = cleaned.strip()
    cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = cleaned.strip("`").strip()
    return cleaned


# ---------------------------------------------------------------------------
# Channel-specific Ollama option profiles
# ---------------------------------------------------------------------------

CHANNEL_OPTIONS: dict[str, dict[str, Any]] = {
    "council": {
        "temperature": 0.12,
        "top_p": 0.8,
        "repeat_penalty": 1.08,
        "num_ctx": 8192,
        "num_predict": 384,
    },
    "faction_leaders": {
        "temperature": 0.15,
        "top_p": 0.85,
        "repeat_penalty": 1.08,
        "num_ctx": 6144,
        "num_predict": 220,
    },
    "historian": {
        "temperature": 0.18,
        "top_p": 0.85,
        "repeat_penalty": 1.08,
        "num_ctx": 6144,
        "num_predict": 256,
    },
    "memory_summarizer": {
        "temperature": 0.10,
        "top_p": 0.8,
        "repeat_penalty": 1.08,
        "num_ctx": 4096,
        "num_predict": 192,
    },
}

DEFAULT_OPTIONS: dict[str, Any] = {
    "temperature": 0.2,
    "top_p": 0.85,
    "repeat_penalty": 1.08,
    "num_ctx": 4096,
    "num_predict": 192,
}


def get_channel_options(channel: str, seed: int | None = None) -> dict[str, Any]:
    """Return Ollama generation options for a given channel."""
    opts = dict(CHANNEL_OPTIONS.get(channel, DEFAULT_OPTIONS))
    
    # Apply global temperature modifier
    opts["temperature"] = max(0.0, opts.get("temperature", 0.2) + USER_SETTINGS.global_temperature_modifier)
    
    if seed is not None:
        opts["seed"] = seed
    return opts


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

# Detection timeout (fast, just to list models)
_DETECT_TIMEOUT = 2.5
# Request timeout per generate call
_REQUEST_TIMEOUT = 25.0
# Keep model loaded in Ollama for fast follow-ups
_KEEP_ALIVE = "15m"


class OllamaClient:
    """Thin wrapper around the ``ollama`` Python package.

    Instantiated once at game startup.  Thread-safe for concurrent
    ``generate()`` calls (Ollama handles its own queue internally).
    """

    def __init__(
        self,
        preferred_model: str = "qwen3.5:9b",
        detect_timeout: float = _DETECT_TIMEOUT,
        request_timeout: float = _REQUEST_TIMEOUT,
        keep_alive: str = _KEEP_ALIVE,
        seed: int | None = None,
    ):
        self.preferred_model = preferred_model
        self.request_timeout = request_timeout
        self.keep_alive = keep_alive
        self.seed = seed

        self._ollama = _try_import_ollama()
        self._client = self._make_client(request_timeout) if self._ollama else None
        self._detected_model: str | None = None
        self._detect_lock = threading.Lock()
        self._detect_timeout = detect_timeout

    @property
    def available(self) -> bool:
        return self._ollama is not None

    # ---- model detection ---------------------------------------------------

    def detect_model(self, force_refresh: bool = False) -> str | None:
        """Detect and cache the preferred Ollama model.  Thread-safe."""
        if self._detected_model == USER_SETTINGS.llm_model and not force_refresh:
            return self._detected_model

        if not self.available:
            return None

        with self._detect_lock:
            if self._detected_model:
                return self._detected_model

            try:
                client = self._make_client(self._detect_timeout)
                models_response = client.list() if client else self._ollama.list()

                if hasattr(models_response, "get"):
                    available = models_response.get("models", [])
                else:
                    available = getattr(models_response, "models", [])

                if not available:
                    logger.warning(
                        "[LLM] No models available. Install with: ollama pull %s",
                        self.preferred_model,
                    )
                    return None

                names: list[str] = []
                for m in available:
                    if isinstance(m, dict):
                        n = m.get("name", "")
                    elif hasattr(m, "model"):
                        n = m.model
                    elif isinstance(m, str):
                        n = m
                    else:
                        continue
                    if n and n.strip():
                        names.append(n.strip())

                if USER_SETTINGS.llm_model in names:
                    self._detected_model = USER_SETTINGS.llm_model
                    logger.info(
                        "[LLM] Selected preferred model: %s", USER_SETTINGS.llm_model
                    )
                    return self._detected_model

                logger.warning(
                    "[LLM] Preferred model %s not found in available models: %s",
                    USER_SETTINGS.llm_model, names
                )
                return None

            except Exception as exc:
                logger.error("[LLM] Model detection error: %s", exc)
                return None

    # ---- generation --------------------------------------------------------

    def generate(
        self,
        prompt: str,
        channel: str = "council",
        options: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Run a blocking generate call.  Returns (response_text, model_used).

        Raises RuntimeError on failure so the scheduler can record the error.
        """
        if not self.available:
            raise RuntimeError("Ollama package not installed")

        model = self.detect_model()
        if not model:
            raise RuntimeError("No LLM model available")

        opts = options or get_channel_options(channel, self.seed)

        try:
            gen = self._client.generate if self._client else self._ollama.generate
            response = gen(
                model=model,
                prompt=prompt,
                options=opts,
                stream=False,
                think=False,
                raw=False,
                keep_alive=self.keep_alive,
            )

            if isinstance(response, dict):
                text = response.get("response", "")
            else:
                text = getattr(response, "response", "")

            text = sanitize_llm_response(text)
            if not text:
                raise RuntimeError("Empty response from model")
            return text, model

        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Ollama generate failed: {exc}") from exc

    # ---- internals ---------------------------------------------------------

    def _make_client(self, timeout: float):
        if self._ollama is None:
            return None
        try:
            kwargs = {"timeout": timeout}
            if USER_SETTINGS.llm_host:
                kwargs["host"] = USER_SETTINGS.llm_host
                
            return self._ollama.Client(**kwargs)
        except Exception:
            return None

    def refresh_client(self):
        """Rebuild the client, typically called when settings change."""
        with self._detect_lock:
            self._client = self._make_client(self.request_timeout)
        self.detect_model(force_refresh=True)


def _try_import_ollama():
    try:
        import ollama
        return ollama
    except ImportError:
        return None
