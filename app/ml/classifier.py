import json
import logging
import os

log = logging.getLogger(__name__)

_model = None
_labels = ["P1", "P2", "P3", "P4"]
_loaded = False

ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")


def rule_based(f: dict) -> str:
    if f.get("pods_ready", 1) == 0 or f.get("error_rate", 0) >= 0.25:
        return "P1"
    if f.get("redis_up", 1) == 0:
        return "P1"
    if f.get("db_connections", 0) >= 85:
        return "P1"
    if f.get("error_rate", 0) >= 0.1 or f.get("cpu_pct", 0) >= 80 or f.get("memory_pct", 0) >= 85:
        return "P2"
    if f.get("error_rate", 0) >= 0.03:
        return "P3"
    return "P4"


def _load():
    global _model, _labels, _loaded
    if _loaded:
        return
    _loaded = True
    labels_path = os.path.join(ART_DIR, "labels.json")
    model_path = os.path.join(ART_DIR, "model.joblib")
    try:
        if os.path.exists(labels_path):
            with open(labels_path, encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, list) and loaded:
                    _labels = [str(x) for x in loaded]
        if os.path.exists(model_path):
            import joblib
            _model = joblib.load(model_path)
    except Exception as e:
        log.debug(f"severity model unavailable, rules fallback: {e}")
        _model = None


def predict_severity(features: dict) -> str:
    _load()
    if _model is not None:
        try:
            import numpy as np
            import pandas as pd

            from app.ml.features import FEATURE_COLUMNS
            row = {c: features.get(c, 0) for c in FEATURE_COLUMNS}
            preds = np.asarray(_model.predict(pd.DataFrame([row])))
            idx = int(preds.argmax() if preds.ndim > 1 else preds.flatten()[0])
            if 0 <= idx < len(_labels):
                return _labels[idx]
        except Exception as e:
            log.debug(f"model predict failed, fallback: {e}")
    return rule_based(features)
