"""Model keyspace wiring: every table follows the connected keyspace.

Models leave __keyspace__ unset, so cqlengine resolves it from the default
keyspace that core.database.connect() registers. A literal keyspace on a model
would split writes between the model layer and the raw-CQL repositories, which
use settings.scylla_keyspace.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from cassandra.cqlengine import models as cql_models

from tests.conftest import TEST_KEYSPACE

ROOT = Path(__file__).resolve().parents[2]


def _model_modules() -> list[str]:
    """Dotted names of every feature model module (tests excluded)."""
    names = []
    for path in ROOT.glob("*/*model*.py"):
        if path.parent.name == "tests":
            continue
        names.append(".".join(path.relative_to(ROOT).with_suffix("").parts))
    return sorted(names)


def test_no_model_hard_codes_a_keyspace() -> None:
    offenders = []
    for name in _model_modules():
        source = (ROOT / f"{name.replace('.', '/')}.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            literal = isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            )
            if "__keyspace__" in targets and literal:
                offenders.append(f"{name}:{node.lineno}")
    assert offenders == []


def test_models_resolve_to_connection_keyspace(monkeypatch) -> None:
    monkeypatch.setattr(cql_models, "DEFAULT_KEYSPACE", "ks_probe")
    checked = 0
    for name in _model_modules():
        module = importlib.import_module(name)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, cql_models.Model)
                and value.__module__ == name
            ):
                # The session DB fixture pins the test keyspace on models
                # until the run ends; undo that so only a keyspace the
                # model itself declares can fail this check.
                if value.__dict__.get("__keyspace__") == TEST_KEYSPACE:
                    monkeypatch.setattr(value, "__keyspace__", None)
                assert value._get_keyspace() == "ks_probe", value.__name__
                checked += 1
    assert checked > 100
