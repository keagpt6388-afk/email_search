"""외부 조회 결과 캐시(SQLite, JSON 값). 같은 사람·같은 문서를 다시 묻지 않게 한다."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable


class Cache:
    def __init__(self, root: Path | None) -> None:
        self.root = root
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(root / "cache.sqlite3", check_same_thread=False)
            self._conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, json TEXT, at REAL)")
            self._conn.commit()

    def get(self, key: str, ttl: float | None = None) -> Any:
        if self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute("SELECT json, at FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if ttl is not None and time.time() - float(row[1]) > ttl:
            return None
        return json.loads(row[0])

    def put(self, key: str, value: Any) -> None:
        if self._conn is None:
            return
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv VALUES (?,?,?)", (key, json.dumps(value, ensure_ascii=False), time.time()))
            self._conn.commit()

    def cached(self, key: str, loader: Callable[[], Any], ttl: float | None = None, cache_none: bool = True) -> Any:
        """loader 예외는 None 으로 삼는다. 실패(None)를 캐시할지 선택할 수 있다(한도 오류는 다음 번에 다시 시도해야 하므로 cache_none=False)."""
        hit = self.get(key, ttl)
        if hit is not None:
            return hit.get("v") if isinstance(hit, dict) and "v" in hit else hit
        try:
            value = loader()
        except Exception:  # noqa: BLE001
            value = None
        if value is not None or cache_none:
            self.put(key, {"v": value})
        return value
