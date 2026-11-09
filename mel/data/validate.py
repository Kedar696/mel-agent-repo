"""JSON Schema validation for insight / survey / schedule_handoff / response / no_survey / bottom_sheet. Owner: P1."""

import json
from functools import lru_cache

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from mel.config import SCHEMAS

KINDS = ("insight", "survey", "schedule_handoff", "response", "no_survey", "bottom_sheet")


@lru_cache
def _registry() -> Registry:
    reg = Registry()
    for p in SCHEMAS.glob("*.schema.json"):
        s = json.loads(p.read_text(encoding="utf-8"))
        res = Resource.from_contents(s)
        reg = reg.with_resource(s.get("$id", p.name), res).with_resource(p.name, res)
    return reg


@lru_cache
def _validator(kind: str) -> Draft202012Validator:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {KINDS}")
    schema = json.loads((SCHEMAS / f"{kind}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, registry=_registry())


def errors(kind: str, obj: dict) -> list[str]:
    return [f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in _validator(kind).iter_errors(obj)]


def failed_fields(kind: str, obj: dict) -> list[str]:
    """Every field that fails the schema, sorted, as dotted paths (``query_summary``,
    ``verification.needed``). A missing required field is named, not reported as the parent."""
    fields: set[str] = set()
    for e in _validator(kind).iter_errors(obj):
        path = [str(p) for p in e.path]
        if e.validator == "required" and isinstance(e.instance, dict):
            fields.update(".".join(path + [k]) for k in e.validator_value if k not in e.instance)
        else:
            fields.add(".".join(path) or "<root>")
    return sorted(fields)


def is_valid(kind: str, obj: dict) -> bool:
    return not errors(kind, obj)


def why_junk(insight: dict) -> list[str]:
    """Plain reasons an insight should get no survey. Empty list means it looks clean.

    Two sources of 'junk': the practice label ``quality_flag == "junk"``, and any way the
    row fails the insight schema (junk rows are broken on purpose and may miss required
    fields or carry out-of-range values). P1 reports these so a batch run can say *why* a
    row was dropped instead of silently skipping it.
    """
    reasons: list[str] = []
    if insight.get("quality_flag") == "junk":
        reasons.append("labelled junk (quality_flag)")
    reasons.extend(f"schema: {e}" for e in errors("insight", insight))
    return reasons


def validate(kind: str, obj: dict) -> dict:
    errs = errors(kind, obj)
    if errs:
        raise ValueError(f"{kind} invalid:\n  " + "\n  ".join(errs[:10]))
    return obj
