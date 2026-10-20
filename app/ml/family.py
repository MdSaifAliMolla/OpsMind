"""Fault-family classifier trained on the generated incident corpus.

Returns None for unknown labels or when no trained model is available.
"""
import json
import logging
import os

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from app.ml.features import FEATURE_COLUMNS, incident_to_features

log = logging.getLogger(__name__)

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

ART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
MODEL_FILE = os.path.join(ART_DIR, "family.joblib")
LABELS_FILE = os.path.join(ART_DIR, "family_labels.json")

_labels = None
_model = None
_loaded = False


def _load():
    global _labels, _model, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(LABELS_FILE) as f:
            labels = json.load(f)
        if isinstance(labels, list) and labels:
            _labels = labels
        _model = joblib.load(MODEL_FILE)
    except Exception as e:
        log.debug(f"family model unavailable: {e}")
        _labels, _model = None, None


def train_family(incidents_dir=None, out_dir=None):
    rows = []
    if incidents_dir is None:
        incidents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "../../data/incidents")
    incidents_dir = os.path.abspath(incidents_dir)
    for name in sorted(os.listdir(incidents_dir)):
        path = os.path.join(incidents_dir, name, "incident.json")
        if not os.path.isfile(path):
            continue
        with open(path) as f:
            rec = json.load(f)
        feats = incident_to_features(rec)
        feats["family"] = str(rec.get("alert_type", "unknown"))
        rows.append(feats)
    df = pd.DataFrame(rows)
    le = LabelEncoder()
    y = le.fit_transform(df["family"])
    X = df[FEATURE_COLUMNS]
    counts = pd.Series(y).value_counts()
    strat = y if (counts >= 2).all() else None
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=strat)
    if HAS_XGB:
        model = xgb.XGBClassifier(n_estimators=200, objective="multi:softprob",
                                  num_class=len(le.classes_), random_state=42,
                                  max_depth=4, learning_rate=0.1)
    else:
        model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(X_train, y_train)
    pred = model.predict(X_test)
    try:
        import numpy as np
        pred = np.asarray(pred)
        if pred.ndim > 1:
            pred = pred.argmax(axis=1)
        pred = pred.flatten()
    except Exception:
        pass
    f1 = float(f1_score(y_test, list(pred), average="macro", zero_division=0))
    out = os.path.abspath(out_dir) if out_dir else ART_DIR
    os.makedirs(out, exist_ok=True)
    joblib.dump(model, os.path.join(out, "family.joblib"))
    with open(os.path.join(out, "family_labels.json"), "w") as f:
        json.dump(list(le.classes_), f)
    _mlflow_log({"model": "xgboost" if HAS_XGB else "random_forest",
                 "n_labels": len(le.classes_)}, f1, model)
    return {"f1_macro": round(f1, 4), "labels": list(le.classes_)}


def _mlflow_log(params: dict, f1: float, model) -> None:
    """Best-effort tracking + registry. Never fails training."""
    uri = os.getenv("MLFLOW_TRACKING_URI", "")
    if not uri:
        return
    try:
        import socket
        from urllib.parse import urlparse

        import mlflow

        parts = urlparse(uri if "://" in uri else f"http://{uri}")
        socket.create_connection((parts.hostname, parts.port or 5000),
                                 timeout=2).close()
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment("fault-family")
        with mlflow.start_run():
            mlflow.log_params(params)
            mlflow.log_metric("f1_macro", f1)
            try:
                if HAS_XGB:
                    import mlflow.xgboost
                    mlflow.xgboost.log_model(model, "model",
                                             registered_model_name="fault-family-model")
                else:
                    import mlflow.sklearn
                    mlflow.sklearn.log_model(model, "model",
                                             registered_model_name="fault-family-model")
            except Exception as e:
                log.debug(f"model registry skipped: {e}")
    except Exception as e:
        log.debug(f"mlflow tracking skipped: {e}")


def predict_family(features: dict) -> str | None:
    """Family string, or None when the model is absent/broken. Never raises."""
    _load()
    if _model is None or not _labels:
        return None
    try:
        row = {c: features.get(c, 0) for c in FEATURE_COLUMNS}
        pred = _model.predict(pd.DataFrame([row]))
        try:
            import numpy as np
            pred = np.asarray(pred).flatten()
        except Exception:
            pass
        idx = int(pred[0])
        if 0 <= idx < len(_labels):
            return str(_labels[idx])
    except Exception as e:
        log.debug(f"family predict failed: {e}")
    return None


if __name__ == "__main__":
    print(train_family())
