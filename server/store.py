"""Реестр моделей.

Каждая модель - папка data/output/<id>/ со всем, что к ней относится:
исходник, GLB, рендеры, метаданные, лог. Один каталог - одна единица работы,
ничего не разбросано.

Адресация короткими id (m_a3f7), а не путями: их дёшево держать в голове
и передавать между вызовами.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import config
from .errors import ModelNotFound


class ModelStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or config.OUTPUT_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self) -> tuple[str, Path]:
        model_id = "m_" + uuid.uuid4().hex[:6]
        d = self.root / model_id
        (d / "views").mkdir(parents=True, exist_ok=True)
        return model_id, d

    def ids(self) -> list[str]:
        """Свежие сверху - обычно нужна последняя модель."""
        dirs = [p for p in self.root.iterdir() if p.is_dir() and p.name.startswith("m_")]
        dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in dirs]

    def dir(self, model_id: str) -> Path:
        d = self.root / model_id
        if not d.is_dir():
            raise ModelNotFound(model_id, self.ids())
        return d

    def resolve(self, model_id: str | None) -> str:
        """None или 'last' означают последнюю модель - самый частый случай."""
        if model_id in (None, "", "last", "latest"):
            ids = self.ids()
            if not ids:
                raise ModelNotFound("last", [])
            return ids[0]
        return self.dir(model_id).name

    def meta(self, model_id: str) -> dict[str, Any]:
        f = self.dir(model_id) / "meta.json"
        if not f.exists():
            return {}
        return json.loads(f.read_text(encoding="utf-8"))

    def write_meta(self, model_id: str, data: dict[str, Any]) -> None:
        d = self.dir(model_id)
        data = {**data, "id": model_id, "updated_at": time.time()}
        (d / "meta.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def log(self, model_id: str, text: str) -> None:
        with (self.dir(model_id) / "log.txt").open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")

    def glb(self, model_id: str) -> Path:
        return self.dir(model_id) / "model.glb"

    def views(self, model_id: str) -> list[Path]:
        return sorted((self.dir(model_id) / "views").glob("*.png"))
