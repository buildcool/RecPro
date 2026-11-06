from __future__ import annotations

import json
import threading
from typing import Any

from .db import Database

DEFAULTS: dict[str, Any] = {
    "onboarded": False,
    "theme": "system",  # system | light | dark
    # sensitivity per area: never_miss | balanced | fewer
    "sensitivity.faces": "never_miss",
    "sensitivity.sensitive": "never_miss",
    "sensitivity.categories": "balanced",
    "performance.use_gpu": True,
    "performance.quiet_on_battery": True,
    "performance.paused": False,
    "privacy.strict_offline": False,
    "privacy.blur_default": True,
    "privacy.auto_lock_minutes": 5,
    "privacy.ids_private": False,
    "privacy.check_before_show": True,
    "ops.removal_default": "bin",  # bin | recycle | keep
    "ops.structure_default": "keep",  # keep | flat | date | person
    "ops.conflict_default": "rename",  # rename | skip
    "ocr.languages": ["en", "hi"],
    "models.profile": "best",  # best | fast
}


class Settings:
    def __init__(self, db: Database):
        self.db = db
        self._lock = threading.Lock()
        self._cache: dict[str, Any] | None = None

    def all(self) -> dict[str, Any]:
        with self._lock:
            if self._cache is None:
                stored = {r["key"]: json.loads(r["value"]) for r in self.db.q("SELECT key, value FROM settings")}
                self._cache = {**DEFAULTS, **stored}
            return dict(self._cache)

    def get(self, key: str, default: Any = None) -> Any:
        return self.all().get(key, DEFAULTS.get(key, default))

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        unknown = [k for k in values if k not in DEFAULTS]
        if unknown:
            raise KeyError(f"Unknown settings: {', '.join(unknown)}")
        with self.db.tx() as c:
            for k, v in values.items():
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, json.dumps(v)),
                )
        with self._lock:
            self._cache = None
        return self.all()
