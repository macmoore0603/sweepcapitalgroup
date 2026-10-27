"""Append-only JSONL journal: every signal, risk decision, order and execution report."""

from __future__ import annotations

import dataclasses
import json
import os
from enum import Enum
from pathlib import Path
from typing import Any


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


class Journal:
    """One JSON object per line: ``{"ts": ..., "kind": ..., **payload}``. Flushed per write.

    The envelope always wins: a payload that has its own ``ts`` or ``kind``
    (e.g. a ``Signal``) is nested under ``"payload"`` instead of overwriting
    them; a non-dict payload goes under ``"value"``.
    """

    def __init__(self, path: str | os.PathLike[str] | None) -> None:
        self._fh = None
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fh = p.open("a", encoding="utf-8")

    def record(self, kind: str, ts: float, payload: Any) -> None:
        if self._fh is None:
            return
        body = to_jsonable(payload)
        line: dict[str, Any] = {"ts": ts, "kind": kind}
        if not isinstance(body, dict):
            line["value"] = body
        elif line.keys() & body.keys():
            line["payload"] = body
        else:
            line.update(body)
        self._fh.write(json.dumps(line, separators=(",", ":")) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


class NullJournal(Journal):
    def __init__(self) -> None:
        super().__init__(None)
