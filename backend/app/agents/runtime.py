"""Shared agent runtime.

Calls any provider through LiteLLM, asks for JSON, validates it against a Pydantic model,
retries with the validation error, falls back to a second model, and records tokens and cost.
Set COUNCIL_MOCK_LLM=1 to use registered mock responders instead (tests and offline demos).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional, Type, TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from app.config import config, mock_mode

T = TypeVar("T")


class AgentError(RuntimeError):
    pass


@dataclass
class CallRecord:
    agent: str
    model: str
    ok: bool
    attempts: int
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: Optional[str] = None
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


@dataclass
class Usage:
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    def summary(self) -> dict:
        return {"calls": len(self.calls), "failed": sum(not c.ok for c in self.calls),
                "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
                "completion_tokens": sum(c.completion_tokens for c in self.calls),
                "cost_usd": self.cost_usd}


# ---------- mock responders (tests / offline) ----------
_MOCKS: dict[str, Callable[[str, str], str]] = {}


def register_mock(agent: str, fn: Callable[[str, str], str]) -> None:
    """fn(system, user) -> raw text the 'model' returns."""
    _MOCKS[agent] = fn


def clear_mocks() -> None:
    _MOCKS.clear()


# ---------- JSON extraction ----------
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """Parse JSON from a model reply, tolerating code fences and leading prose."""
    m = _FENCE.search(text)
    if m:
        text = m.group(1)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        a, b = text.find(open_c), text.rfind(close_c)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model reply")


# Provider errors worth retrying on the same model (overloaded, rate limited, network) before the fallback.
TRANSIENT_ERRORS = {"ServiceUnavailableError", "RateLimitError", "Timeout", "APIConnectionError", "InternalServerError"}
_RETRY_AFTER = re.compile(r"try again in ([\d.]+)\s*s", re.I)
MAX_RETRY_WAIT = 90.0          # longer than this: move to the fallback model instead of waiting
# Rate-limit errors that waiting cannot fix: a used-up daily quota, a request over the per-minute cap.
NO_RETRY_MARKERS = ("exceeded your current quota", "Request too large")


PROVIDER_KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
                 "groq": "GROQ_API_KEY", "ollama_chat": "OLLAMA_API_BASE", "ollama": "OLLAMA_API_BASE"}


def has_key(model: str) -> bool:
    """True when the provider of a LiteLLM model name has its key set (unknown providers: assume yes)."""
    env = PROVIDER_KEYS.get(model.split("/", 1)[0])
    return env is None or bool(os.environ.get(env))


_OBSERVED = False


def _observe(litellm) -> None:
    """Send every prompt, token count and cost to Langfuse when its keys are set in .env (task 1.2).
    Needs `pip install -e ".[observability]"`; without keys or the package, calls run unlogged."""
    global _OBSERVED
    if _OBSERVED:
        return
    _OBSERVED = True
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        return
    try:
        import langfuse  # noqa: F401
    except ImportError:
        return
    for hook in ("success_callback", "failure_callback"):
        cbs = getattr(litellm, hook)
        if "langfuse" not in cbs:
            cbs.append("langfuse")


class AgentRuntime:
    def __init__(self, usage: Optional[Usage] = None, max_attempts: int = 3, temperature: float = 0.2,
                 retry_wait: float = 3.0, on_change: Optional[Callable[["AgentRuntime"], None]] = None):
        self.usage = usage or Usage()
        self.max_attempts = max_attempts
        self.temperature = temperature
        self.retry_wait = retry_wait
        self.personas = config("personas")["agents"]
        self.active: dict[int, CallRecord] = {}          # calls in flight, so watchers see who is working on which model
        self.on_change = on_change                       # called when a call starts or ends (e.g. to write usage.json)
        self._lock = threading.Lock()

    def _started(self, rec: CallRecord) -> int:
        with self._lock:
            key = id(rec)
            self.active[key] = rec
        self._notify()
        return key

    def _ended(self, key: int, rec: CallRecord) -> None:
        with self._lock:
            self.active.pop(key, None)
            self.usage.calls.append(rec)
        self._notify()

    def _notify(self) -> None:
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:
                pass                                     # watching must never break a run

    def persona(self, agent: str) -> dict:
        if agent not in self.personas:
            raise AgentError(f"unknown agent '{agent}' (see config/personas.yaml)")
        return self.personas[agent]

    def ask(self, agent: str, system: str, user: str, schema: Type[T] | Any) -> T:
        """Ask an agent and return a validated object of `schema` (a model or e.g. list[Model])."""
        p = self.persona(agent)
        fallback = p.get("fallback_model") or []
        models = [p["model"]] + (fallback if isinstance(fallback, list) else [fallback])   # one model or a list, in order
        adapter = TypeAdapter(schema)
        last_err = "no attempt made"
        if not mock_mode():
            usable = [m for m in models if has_key(m)]
            if not usable:
                raise AgentError(f"{agent}: no API key for any of {', '.join(models)} (see .env)")
            models = usable                                  # a model without a key is skipped, not called
        for model in (["mock"] if mock_mode() else models):
            msgs = [{"role": "system", "content": system + "\n\nReply with JSON only."},
                    {"role": "user", "content": user}]
            for attempt in range(1, self.max_attempts + 1):
                t0 = time.time()
                rec = CallRecord(agent=agent, model=model, ok=False, attempts=attempt)
                key = self._started(rec)
                try:
                    raw = self._complete(agent, model, msgs, rec)
                    obj = adapter.validate_python(extract_json(raw))
                    rec.ok, rec.seconds = True, round(time.time() - t0, 3)
                    self._ended(key, rec)
                    return obj
                except (ValueError, ValidationError) as e:
                    last_err = f"{type(e).__name__}: {e}"
                    rec.error, rec.seconds = last_err[:500], round(time.time() - t0, 3)
                    self._ended(key, rec)
                    msgs.append({"role": "user", "content":
                                 f"Your reply was not valid. Error: {last_err[:800]}\nReturn corrected JSON only."})
                except Exception as e:  # provider errors: wait and retry if transient, else move to the fallback
                    last_err = f"{type(e).__name__}: {e}"
                    rec.error, rec.seconds = last_err[:500], round(time.time() - t0, 3)
                    self._ended(key, rec)
                    hopeless = any(m in str(e) for m in NO_RETRY_MARKERS)
                    if type(e).__name__ in TRANSIENT_ERRORS and not hopeless and attempt < self.max_attempts:
                        asked = _RETRY_AFTER.search(str(e))           # e.g. Groq: "try again in 52.07s"
                        wait = max(self.retry_wait * attempt, float(asked.group(1)) if asked else 0.0)
                        if wait <= MAX_RETRY_WAIT:
                            time.sleep(wait)
                            continue
                    break
        raise AgentError(f"{agent}: no valid reply after retries and fallback. Last error: {last_err}")

    def _complete(self, agent: str, model: str, msgs: list[dict], rec: CallRecord) -> str:
        if model == "mock":
            if agent not in _MOCKS:
                raise AgentError(f"mock mode: no mock registered for '{agent}'")
            sys_txt = msgs[0]["content"]
            user_txt = "\n".join(m["content"] for m in msgs[1:])
            return _MOCKS[agent](sys_txt, user_txt)
        import litellm  # imported lazily so tests run without network
        _observe(litellm)
        # drop_params: models that only accept their default temperature (e.g. Claude 5.5) get the call without it
        resp = litellm.completion(model=model, messages=msgs, temperature=self.temperature, drop_params=True,
                                  metadata={"trace_name": f"council:{agent}", "generation_name": agent,
                                            "tags": [agent, model]})
        u = getattr(resp, "usage", None)
        if u:
            rec.prompt_tokens = getattr(u, "prompt_tokens", 0) or 0
            rec.completion_tokens = getattr(u, "completion_tokens", 0) or 0
        try:
            rec.cost_usd = float(litellm.completion_cost(completion_response=resp) or 0.0)
        except Exception:
            rec.cost_usd = 0.0
        return resp.choices[0].message.content or ""
