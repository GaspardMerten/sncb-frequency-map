"""Simple TTL cache for expensive computations."""

import asyncio
import time
from functools import wraps
from hashlib import sha256
from typing import Any

_store: dict[str, tuple[float, Any]] = {}


def _make_key(*args, **kwargs) -> str:
    raw = repr((args, sorted(kwargs.items())))
    return sha256(raw.encode()).hexdigest()


def cached(ttl: int = 3600):
    """Decorator that caches return values with a TTL in seconds."""
    def decorator(fn):
        prefix = f"{fn.__module__}.{fn.__qualname__}"
        is_async = asyncio.iscoroutinefunction(fn)

        def _get_or_set(key, compute):
            now = time.time()
            entry = _store.get(key)
            if entry and now < entry[0]:
                return entry[1]
            value = compute()
            _store[key] = (now + ttl, value)
            return value

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{prefix}:{_make_key(*args, **kwargs)}"
            return _get_or_set(key, lambda: fn(*args, **kwargs))

        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            key = f"{prefix}:{_make_key(*args, **kwargs)}"
            now = time.time()
            entry = _store.get(key)
            if entry and now < entry[0]:
                return entry[1]
            value = await fn(*args, **kwargs)
            _store[key] = (now + ttl, value)
            return value

        return async_wrapper if is_async else wrapper
    return decorator


def clear_expired():
    """Remove expired entries."""
    now = time.time()
    expired = [k for k, (exp, _) in _store.items() if now >= exp]
    for k in expired:
        del _store[k]
