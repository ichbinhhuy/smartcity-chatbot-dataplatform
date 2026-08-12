"""Langfuse observability -- singleton client + trace helpers.

Hoat dong theo che do opt-in:
  - Neu LANGFUSE_SECRET_KEY duoc set -> gui trace len Langfuse cloud.
  - Neu khong -> tat ca ham la no-op, khong anh huong den runtime.
"""

from __future__ import annotations

import os
from typing import Any

import app.config  # Ensure .env is loaded into os.environ

_langfuse_client = None
_ENABLED = False


def _init() -> None:
    global _langfuse_client, _ENABLED
    secret = os.getenv("LANGFUSE_SECRET_KEY", "")
    public = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    host = os.getenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")

    if not secret or not public:
        print("[Langfuse] LANGFUSE_SECRET_KEY not set -- tracing disabled (no-op mode).")
        return

    try:
        from langfuse import Langfuse
        _langfuse_client = Langfuse(secret_key=secret, public_key=public, host=host)
        _ENABLED = True
        print(f"[Langfuse] Tracing enabled -- host={host}")
    except ImportError:
        print("[Langfuse] Package not installed. Run: pip install langfuse")
    except Exception as exc:
        print(f"[Langfuse] Init error: {exc}")


def is_enabled() -> bool:
    return _ENABLED


class _NoopObj:
    """Placeholder khi Langfuse bi tat -- moi method deu la no-op."""
    def end(self, **kw): pass
    def update(self, **kw): pass


class _LangfuseWrapper:
    """Wrapper tuong thich cho ca Langfuse SDK v4+ va legacy (v1/v2)."""
    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def update(self, **kwargs: Any) -> Any:
        if not self._inner or isinstance(self._inner, _NoopObj):
            return self
        try:
            if hasattr(self._inner, "update"):
                self._inner.update(**kwargs)
        except Exception as exc:
            print(f"[Langfuse] update error: {exc}")
        return self

    def end(self, output: Any = None, level: str | None = None, **kwargs: Any) -> None:
        if not self._inner or isinstance(self._inner, _NoopObj):
            return
        try:
            up_kwargs = {}
            if output is not None:
                up_kwargs["output"] = output
            if level is not None:
                up_kwargs["level"] = level
            if up_kwargs and hasattr(self._inner, "update"):
                self._inner.update(**up_kwargs)

            if hasattr(self._inner, "end"):
                try:
                    self._inner.end()
                except TypeError:
                    self._inner.end(output=output, level=level, **kwargs)
        except Exception as exc:
            print(f"[Langfuse] end error: {exc}")


def start_trace(name: str, user_id: str | None = None, metadata: dict | None = None) -> Any:
    if not _ENABLED or _langfuse_client is None:
        return _NoopObj()
    try:
        if hasattr(_langfuse_client, "start_observation"):
            kw = {"name": name, "as_type": "span", "metadata": metadata or {}}
            if user_id:
                kw["metadata"]["user_id"] = user_id
            obs = _langfuse_client.start_observation(**kw)
            return _LangfuseWrapper(obs)
        elif hasattr(_langfuse_client, "trace"):
            return _LangfuseWrapper(_langfuse_client.trace(name=name, user_id=user_id, metadata=metadata or {}))
        return _NoopObj()
    except Exception as exc:
        print(f"[Langfuse] start_trace error: {exc}")
        return _NoopObj()


def start_span(trace: Any, name: str, input: Any = None, metadata: dict | None = None) -> Any:
    if not _ENABLED or isinstance(trace, _NoopObj):
        return _NoopObj()
    try:
        real_trace = trace._inner if isinstance(trace, _LangfuseWrapper) else trace
        if hasattr(real_trace, "start_observation"):
            obs = real_trace.start_observation(name=name, as_type="span", input=input, metadata=metadata or {})
            return _LangfuseWrapper(obs)
        elif hasattr(real_trace, "span"):
            return _LangfuseWrapper(real_trace.span(name=name, input=input, metadata=metadata or {}))
        return _NoopObj()
    except Exception as exc:
        print(f"[Langfuse] start_span error: {exc}")
        return _NoopObj()


def start_generation(
    trace: Any,
    name: str,
    model: str = "",
    input: Any = None,
    metadata: dict | None = None,
) -> Any:
    if not _ENABLED or isinstance(trace, _NoopObj):
        return _NoopObj()
    try:
        real_trace = trace._inner if isinstance(trace, _LangfuseWrapper) else trace
        if hasattr(real_trace, "start_observation"):
            kw = {"name": name, "as_type": "generation", "input": input, "metadata": metadata or {}}
            if model:
                kw["model"] = model
            obs = real_trace.start_observation(**kw)
            return _LangfuseWrapper(obs)
        elif hasattr(real_trace, "generation"):
            return _LangfuseWrapper(real_trace.generation(name=name, model=model, input=input, metadata=metadata or {}))
        return _NoopObj()
    except Exception as exc:
        print(f"[Langfuse] start_generation error: {exc}")
        return _NoopObj()


def flush() -> None:
    """Flush pending events -- goi truoc khi container shutdown."""
    if _ENABLED and _langfuse_client:
        try:
            _langfuse_client.flush()
        except Exception:
            pass


_init()
