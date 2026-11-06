from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Everything RecPro writes lives under one data folder chosen by the user."""

    data: Path

    @property
    def db(self) -> Path:
        return self.data / "recpro.db"

    @property
    def thumbs(self) -> Path:
        return self.data / "thumbs"

    @property
    def previews(self) -> Path:
        return self.data / "previews"

    @property
    def faces(self) -> Path:
        return self.data / "faces"

    @property
    def models(self) -> Path:
        return self.data / "models"

    @property
    def private(self) -> Path:
        return self.data / "private"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def tmp(self) -> Path:
        return self.data / "tmp"

    def ensure(self) -> None:
        for p in (self.data, self.thumbs, self.previews, self.faces, self.models, self.private, self.logs, self.tmp):
            p.mkdir(parents=True, exist_ok=True)
