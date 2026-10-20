#!/usr/bin/env python3
"""Record one chaos run into an offline bundle. REQUIRES A LIVE STACK.

Needs: kind cluster with the demo target + Prometheus reachable, and a fault
already injected (Chaos Mesh, or POST /chaos/<mode> on the demo service).
Run from the repo root. Live capture of evidence snapshots lands with the
kind stack (DESIGN.md step 2); what works today is bundle construction +
validation, which is unit-tested.
"""
import argparse
import json
import sys

from app.evaluation.bundles import validate_bundle


def build_bundle(incident: dict, evidence: list, fault_family: str,
                 service: str, fix, run_id: str) -> dict:
    """Pure constructor: parts in, validated bundle out. Raises if invalid."""
    bundle = {"incident": dict(incident or {}),
              "evidence": list(evidence or []),
              "label": {"fault_family": fault_family, "service": service,
                        "fix": fix},
              "outcome": {"recovered": False, "mttr_s": None},
              "run_id": run_id}
    ok, errors = validate_bundle(bundle)
    if not ok:
        raise ValueError(f"invalid bundle: {errors}")
    return bundle


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--service", required=True)
    ap.add_argument("--fault", required=True,
                    help="fault family from the catalog (app/policy/faults.py)")
    ap.add_argument("--fix", default=None,
                    help="gold fix action; omit for must-escalate faults")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out", required=True, help="bundle .json path")
    ap.add_argument("--api", default="http://localhost:4000")
    args = ap.parse_args(argv)

    import urllib.request
    try:
        with urllib.request.urlopen(f"{args.api}/health", timeout=10) as r:
            health = json.loads(r.read().decode())
    except Exception as e:
        print(f"API unreachable at {args.api}: {e}", file=sys.stderr)
        sys.exit(1)
    if not health.get("ok"):
        print("API not healthy; aborting", file=sys.stderr)
        sys.exit(1)

    print(f"stack OK; capture the incident + evidence for run {args.run_id} "
          f"({args.fault} on {args.service}), then save the bundle.")
    print("Full live capture lands with the kind stack (DESIGN.md step 2).")
    return args


if __name__ == "__main__":
    main()
