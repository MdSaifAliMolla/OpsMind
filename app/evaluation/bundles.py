"""Recorded-run bundles: the unit of v2 evaluation.

A bundle freezes one chaos run: the incident as the agent saw it, the evidence
bundle collectors produced, and the ground-truth label from the injector.
Bundles make RCA/remediation eval offline and repeatable (no cluster, no quota
burn per re-run of the harness — only per LLM call).

Schema:
  incident: dict (incident_id, service, namespace?, alert_type, description)
  evidence: list (evidence items as stored in state)
  label: {fault_family, service, fix} (fix may be null = escalate expected)
  outcome: {recovered: bool, mttr_s: float|None} (live runs only; null offline)
"""
import json
import os

REQUIRED_TOP = ("incident", "evidence", "label")
REQUIRED_LABEL = ("fault_family", "service", "fix")


def validate_bundle(bundle: dict) -> tuple:
    """Returns (ok: bool, errors: list[str]). Pure, never raises."""
    try:
        if not isinstance(bundle, dict):
            return False, ["bundle must be an object"]
        errors = []
        for key in REQUIRED_TOP:
            if key not in bundle:
                errors.append(f"missing top-level key: {key}")
        label = bundle.get("label") or {}
        if not isinstance(label, dict):
            errors.append("label must be an object")
        else:
            for key in REQUIRED_LABEL:
                if key not in label:
                    errors.append(f"missing label key: {key}")
        incident = bundle.get("incident") or {}
        if not isinstance(incident, dict) or not incident.get("incident_id"):
            errors.append("incident.incident_id missing")
        if not isinstance(bundle.get("evidence"), list):
            errors.append("evidence must be a list")
        return (len(errors) == 0), errors
    except Exception as e:
        return False, [f"validation crashed: {e}"]


def save_bundle(path: str, bundle: dict) -> str:
    ok, errors = validate_bundle(bundle)
    if not ok:
        raise ValueError(f"invalid bundle: {errors}")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(bundle, f, indent=2)
    return os.path.abspath(path)


def load_bundle(path: str) -> dict:
    try:
        with open(path) as f:
            bundle = json.load(f)
    except Exception as e:
        raise ValueError(f"unreadable bundle at {path}: {e}")
    ok, errors = validate_bundle(bundle)
    if not ok:
        raise ValueError(f"invalid bundle at {path}: {errors}")
    return bundle


def list_bundles(directory: str) -> list:
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            out.append(load_bundle(os.path.join(directory, name)))
        except Exception:
            continue
    return out
