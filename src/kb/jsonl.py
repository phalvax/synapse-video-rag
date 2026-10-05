"""Lecture / écriture de fichiers JSONL typés (une ligne = un objet Pydantic)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def write_jsonl(path: Path, items: Iterable[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(item.model_dump_json() + "\n")


def read_jsonl(path: Path, model: type[M]) -> list[M]:
    with path.open(encoding="utf-8") as f:
        return [model.model_validate_json(line) for line in f if line.strip()]
