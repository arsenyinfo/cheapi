import abc
import sqlite3
import threading
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple, Union


class Sentinel:
    def __repr__(self):
        return "SENTINEL"


SENTINEL = Sentinel()


class CachingWrapper:
    def __init__(
        self,
        func: Callable[..., Any],
        cache_backend: Optional[str] = None,
        max_size: Optional[int] = None,
        max_age: Optional[Union[float, timedelta]] = None,
    ) -> None:
        self.func = func
        self.cache_backend = cache_backend or "memory"
        self.max_size = max_size

        if isinstance(max_age, float):
            max_age = timedelta(seconds=max_age)
        self.max_age = max_age
        self.cache = self._get_cache()

    def __repr__(self):
        return f"CachingWrapper({self.func.__name__})"

    def __str__(self):
        return repr(self)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        cache_key = self._get_cache_key(args, kwargs)
        cached_value = self.cache.get(cache_key)
        if cached_value is not SENTINEL:
            return cached_value
        result = self.func(*args, **kwargs)
        if result is not None:
            self.cache.set(cache_key, result)
        return result

    def clear(self) -> None:
        self.cache.clear()

    @classmethod
    def cache_fn(cls, *args, **kwargs) -> Callable[..., Any]:
        def _is_run_without_params():
            return len(args) == 1 and callable(args[0]) and not kwargs

        def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
            wrapper = cls(fn) if _is_run_without_params() else cls(fn, *args, **kwargs)

            @wraps(fn)
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                return wrapper(*args, **kwargs)

            return wrapped

        if _is_run_without_params():
            return decorator(args[0])
        return decorator

    def _get_cache(self) -> "BaseCache":
        if self.cache_backend == "memory":
            return InMemoryCache(max_size=self.max_size, max_age=self.max_age)
        elif self.cache_backend == "sqlite":
            try:
                fn_name = self.func.__name__
            except AttributeError:
                fn_name = self.func.__class__.__name__  # for functors
            return SqliteCache(
                func_name=fn_name,
                max_size=self.max_size,
                max_age=self.max_age,
            )
        else:
            raise ValueError(f"Invalid cache backend: {self.cache_backend}")

    @staticmethod
    def _get_cache_key(args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
        key_parts = [str(arg) for arg in args]
        key_parts += [f"{k}={v}" for k, v in sorted(kwargs.items())]
        return ":".join(key_parts)


class BaseCache(abc.ABC):
    def __init__(
        self, max_size: Optional[int] = None, max_age: Optional[timedelta] = None
    ):
        self.max_size = max_size
        self.max_age = max_age
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        raise NotImplementedError

    def set(self, key: str, value: Any) -> None:
        with self.lock:
            if self.max_size is not None and len(self) >= self.max_size:
                self._evict_oldest()
            self._set(key, value)

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        raise NotImplementedError

    def _get_age(self, key: str) -> Optional[timedelta]:
        raise NotImplementedError

    def _is_outdated(self, key: str) -> bool:
        if self.max_age is None:
            return False
        age = self._get_age(key)
        if age is None:
            return False
        return age > self.max_age

    def __len__(self):
        raise NotImplementedError

    def _evict_oldest(self) -> None:
        raise NotImplementedError


class InMemoryCache(BaseCache):
    def __init__(
        self,
        max_size: Optional[int] = None,
        max_age: Optional[timedelta] = None,
    ) -> None:
        super().__init__(max_size=max_size, max_age=max_age)
        self.cache = {}
        self.lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            value, age = self.cache.get(key, (SENTINEL, None))
            if value is not SENTINEL and self._is_outdated(key):
                self.delete(key)
                return SENTINEL
            return value

    def _set(self, key: str, value: Any) -> None:
        self.cache[key] = (value, datetime.now())

    def delete(self, key: str) -> None:
        with self.lock:
            del self.cache[key]

    def clear(self) -> None:
        with self.lock:
            self.cache.clear()

    def _get_age(self, key: str) -> Optional[timedelta]:
        with self.lock:
            value, created_at = self.cache.get(key, (SENTINEL, None))
            if value is not SENTINEL and created_at is not None:
                return datetime.now() - created_at
            return None

    def _is_expired(self, value: Tuple[Any, datetime]) -> bool:
        if self.max_age is None:
            return False
        return datetime.now() - value[1] > self.max_age

    def _evict_oldest(self) -> None:
        oldest_key = None
        oldest_time = datetime.now()
        for key, (value, dt) in self.cache.items():
            if dt < oldest_time:
                oldest_key = key
                oldest_time = dt
        if oldest_key is not None:
            self.cache.pop(oldest_key)  # not self.delete(oldest_key) to avoid lock

    def __len__(self):
        return len(self.cache)


class SqliteCache(BaseCache):
    def __init__(
        self,
        func_name: str,
        max_size: Optional[int] = None,
        max_age: Optional[timedelta] = None,
        cache_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(max_size=max_size, max_age=max_age)

        self.func_name = func_name
        cache_dir = cache_dir or Path.home() / ".cache" / "cheapi"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = cache_dir / f"{func_name}.db"
        self.conn = sqlite3.connect(str(self.cache_file))
        self._create_table()

    def get(self, key: str) -> Optional[Any]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT value, created_at FROM cache WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if row is not None:
                value, created_at = row
                if (
                    self.max_age is not None
                    and datetime.now() - created_at > self.max_age
                ):
                    cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
                    self.conn.commit()
                    return SENTINEL
                return value
            return SENTINEL

    def _set(self, key: str, value: Any) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, value, datetime.now()),
        )
        self.conn.commit()

    def delete(self, key: str) -> None:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM cache WHERE key = ?", (key,))
            self.conn.commit()

    def clear(self) -> None:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM cache")
            self.conn.commit()
        self.cache_file.unlink()

    def _create_table(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            f"CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value BLOB, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, max_age INTERVAL)"
        )
        self.conn.commit()

    def __len__(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        return cursor.fetchone()[0]

    def _get_age(self, key: str) -> Optional[timedelta]:
        with self.lock:
            cursor = self.conn.cursor()
            cursor.execute("SELECT created_at FROM cache WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row is not None:
                return datetime.now() - row[0]
            return None

    def _evict_oldest(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "DELETE FROM cache WHERE created_at = (SELECT MIN(created_at) FROM cache);"
        )
        self.conn.commit()
