"""Thin layer over Jinja2: the one place that knows where the templates live."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def make_env(templates_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        undefined=StrictUndefined,  # a missing template variable is a hard error, not silent emptiness
    )
    env.filters["tojson"] = lambda v: json.dumps(v, ensure_ascii=False)
    return env
