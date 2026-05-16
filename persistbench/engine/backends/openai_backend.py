"""OpenAI function-calling backend for PersistBench V4.

Supports:
  - GPT-4o, GPT-4-turbo, GPT-3.5-turbo
  - Continuous session mode (conversation history maintained)
  - Fresh session mode (new context per session)
  - Token usage tracking

Requires: openai >= 1.0.0
Set OPENAI_API_KEY in the environment before running.

Usage:
    python -m persistbench.run_benchmark \\
        --scenario scenarios/sbmp/sbmp-001.yaml \\
        --llm-backend openai \\
        --llm-model gpt-4o \\
        --run-id run-openai-001
"""
from __future__ import annotations

import os
from typing import Optional

from persistbench.engine.backends.base import AgentBackend


class OpenAIBackend(AgentBackend):
    """Live OpenAI API backend with function-calling support.

    Args:
        model:          OpenAI model ID (default "gpt-4o")
        api_key:        API key (default: OPENAI_API_KEY env var)
        system_prompt:  System instruction prepended to each session
        max_tokens:     Max output tokens per turn (default 512)
        session_mode:   "continuous" (shared history) or "fresh" (new context each session)
        request_delay:  Seconds to wait between turns (default 0.2)
        temperature:    Sampling temperature (default 0.0 for reproducibility)
    """

    DEFAULT_SYSTEM = (
        "You are a helpful assistant with persistent memory across sessions. "
        "Answer questions accurately based on context provided in the conversation."
    )

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_tokens: int = 512,
        session_mode: str = "continuous",
        request_delay: float = 0.2,
        temperature: float = 0.0,
    ) -> None:
        try:
            import openai
        except ImportError:
            raise ImportError(
                "openai package is required for OpenAIBackend. "
                "Install with: pip install openai>=1.0.0"
            )

        self.model        = model
        self.session_mode = session_mode
        self._system      = system_prompt or self.DEFAULT_SYSTEM
        self._max_tokens  = max_tokens
        self._request_delay = request_delay
        self._temperature = temperature
        self._messages: list[dict] = []
        self._usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

        self._client = openai.OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY"),
            timeout=60.0,
        )

    def send(self, content: str, turn=None) -> str:
        import time

        if self.session_mode == "fresh":
            messages = [{"role": "system", "content": self._system},
                        {"role": "user",   "content": content}]
        else:
            if not self._messages:
                self._messages.append({"role": "system", "content": self._system})
            self._messages.append({"role": "user", "content": content})
            messages = self._messages

        if self._request_delay > 0:
            time.sleep(self._request_delay)

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
        )

        response_text = resp.choices[0].message.content or ""
        self._usage["input_tokens"]  += resp.usage.prompt_tokens
        self._usage["output_tokens"] += resp.usage.completion_tokens
        self._usage["calls"]         += 1

        if self.session_mode == "continuous":
            self._messages.append({"role": "assistant", "content": response_text})

        return response_text

    def reset(self) -> None:
        self._messages = []

    @property
    def usage(self) -> dict:
        return dict(self._usage)


def estimate_cost(scenario: dict, model: str) -> dict:
    """Estimate API cost for an OpenAI run."""
    # Approximate token costs per 1M tokens (as of 2025)
    COSTS = {
        "gpt-4o":           {"input": 2.50,  "output": 10.00},
        "gpt-4-turbo":      {"input": 10.00, "output": 30.00},
        "gpt-3.5-turbo":    {"input": 0.50,  "output": 1.50},
        "gpt-4o-mini":      {"input": 0.15,  "output": 0.60},
    }
    cost = COSTS.get(model, {"input": 5.0, "output": 15.0})
    sessions = scenario.get("session_count", 10)
    turns_per_session = scenario.get("benign_turns_per_session", 4) + 2
    total_turns = sessions * turns_per_session
    # Rough estimate: 200 input tokens + 150 output tokens per turn
    input_tokens  = total_turns * 200
    output_tokens = total_turns * 150
    total_cost = (input_tokens / 1_000_000 * cost["input"] +
                  output_tokens / 1_000_000 * cost["output"])
    return {
        "turns": total_turns,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_cost_usd": round(total_cost, 4),
    }
