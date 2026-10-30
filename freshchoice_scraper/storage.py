"""Storage and atomic file persistence utilities for FreshChoice."""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable


def _json_default(obj: Any) -> Any:
    """JSON serializer for objects not serializable by default json code."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: Path | str, data: Any, indent: int = 2) -> Path:
    """Atomically write JSON data."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=indent, ensure_ascii=False, default=_json_default)
    tmp.replace(p)
    return p


def read_json(path: Path | str) -> Any:
    """Read JSON file."""
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def write_jsonl(path: Path | str, records: Iterable[Any]) -> Path:
    """Atomically write JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in records:
            if hasattr(r, "model_dump"):
                d = r.model_dump(exclude_none=True)
            elif hasattr(r, "to_dict"):
                d = r.to_dict()
            elif isinstance(r, dict):
                d = {k: v for k, v in r.items() if v is not None}
            else:
                d = r.__dict__
            f.write(json.dumps(d, ensure_ascii=False, separators=(",", ":"), default=_json_default) + "\n")
    tmp.replace(p)
    return p


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    """Read lines of JSONL file."""
    out = []
    p = Path(path)
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out
