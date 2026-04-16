"""Simple TTL + LRU cache for expensive computations."""

import asyncio
import time
from collections import OrderedDict
from functools import wraps
from hashlib import sha256
from threading import Lock
from typing import Any

# Max entries in the cache. Each punctuality day is ~33MB as list-of-dicts,
# so 8 entries ≈ 260MB. Cloud Run default is 512MB.
_MAX_ENTRIES = 8

_lock = Lock()
_store: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def _make_key(*args, **kwargs) -> str:
    raw = repr((args, sorted(kwargs.items())))
    return sha256(raw.encode()).hexdigest()


def _evict_expired_locked():
    """Remove expired entries. Must hold _lock."""
    now = time.time()
    expired = [k for k, (exp, _) in _store.items() if now >= exp]
    for k in expired:
        del _store[k]


def _evict_lru_locked():
    """Remove oldest entries until under max size. Must hold _lock."""
    while len(_store) > _MAX_ENTRIES:
        _store.popitem(last=False)  # Remove oldest


def cached(ttl: int = 3600):
    """Decorator that caches return values with a TTL in seconds."""
    def decorator(fn):
        prefix = f"{fn.__module__}.{fn.__qualname__}"
        is_async = asyncio.iscoroutinefunction(fn)

        def _get_or_set(key, compute):
            with _lock:
                now = time.time()
                entry = _store.get(key)
                if entry and now < entry[0]:
                    _store.move_to_end(key)  # Mark as recently used
                    return entry[1]

            # Compute outside lock to avoid blocking other threads
            value = compute()

            with _lock:
                _store[key] = (time.time() + ttl, value)
                _evict_expired_locked()
                _evict_lru_locked()
            return value

        @wraps(fn)
        def wrapper(*args, **kwargs):
            key = f"{prefix}:{_make_key(*args, **kwargs)}"
            return _get_or_set(key, lambda: fn(*args, **kwargs))

        @wraps(fn)
        async def async_wrapper(*args, **kwargs):
            key = f"{prefix}:{_make_key(*args, **kwargs)}"
            with _lock:
                now = time.time()
                entry = _store.get(key)
                if entry and now < entry[0]:
                    _store.move_to_end(key)
                    return entry[1]
            value = await fn(*args, **kwargs)
            with _lock:
                _store[key] = (time.time() + ttl, value)
                _evict_expired_locked()
                _evict_lru_locked()
            return value

        return async_wrapper if is_async else wrapper
    return decorator


def clear_expired():
    """Remove expired entries."""
    with _lock:
        _evict_expired_locked()


def cache_clear():
    """Remove all entries."""
    with _lock:
        _store.clear()


def cache_size() -> int:
    """Return number of entries in cache."""
    return len(_store)
