from __future__ import annotations

import importlib
import logging

from .config import Paths
from .context import Context

log = logging.getLogger("recpro")

# Services are registered in dependency order. Each module exposes ``create(ctx)``.
SERVICE_MODULES = [
    ("ml", "recpro.ml.service"),
    ("library", "recpro.library.service"),
    ("indexer", "recpro.jobs.indexer"),
    ("ops", "recpro.ops.service"),
    ("people", "recpro.review.people"),
    ("labels", "recpro.labels"),
    ("semantic_index", "recpro.semindex"),
    ("taxonomy", "recpro.taxonomy"),
    ("private", "recpro.private"),
]


def build_context(paths: Paths, token: str, port: int = 0) -> Context:
    ctx = Context(paths, token, port)
    for name, modname in SERVICE_MODULES:
        try:
            mod = importlib.import_module(modname)
        except ModuleNotFoundError as e:
            if e.name == modname:
                continue
            raise
        ctx.register(name, mod.create(ctx))
    return ctx
