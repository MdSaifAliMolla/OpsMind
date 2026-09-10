import json
import os

from dotenv import load_dotenv
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

from app.ml.features import FEATURE_COLUMNS, load_dataset

load_dotenv()

try:
    import mlflow
    import mlflow.sklearn
    HAS_MLFLOW = True
except ImportError:
    HAS_MLFLOW = False

try:
    import xgboost as xgb
    HAS_XGB = True
except ImportError:
    HAS_XGB = False


def build_model(params):
    if HAS_XGB:
        n_classes = params.pop("_n_classes")
        return xgb.XGBClassifier(
            n_estimators=200,
            objective="multi:softprob",
            num_class=n_classes,
            random_state=42,
            **params,
        )
    return RandomForestClassifier(n_estimators=200, random_state=42)


def main():
    df = load_dataset()
    print(f"loaded {len(df)} incidents")

    le = LabelEncoder()
    y = le.fit_transform(df["severity"])
    X = df[FEATURE_COLUMNS]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.25, random_state=42)

    grid = [
        {"max_depth": 4, "learning_rate": 0.1},
        {"max_depth": 6, "learning_rate": 0.05},
        {"max_depth": 8, "learning_rate": 0.05},
    ]

    tracking = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
    if HAS_MLFLOW:
        try:
            mlflow.set_tracking_uri(tracking)
            mlflow.set_experiment("incident-severity")
        except Exception:
            print("mlflow unavailable, training locally")
            mlflow_active = False
        else:
            mlflow_active = True
    else:
        mlflow_active = False
        print("mlflow not installed, training locally without tracking")

    best_f1 = -1
    best_model = None
    best_params = None
    best_run_id = None

    for params in grid:
        p = dict(params)
        p["_n_classes"] = len(le.classes_)
        model = build_model(p)
        # random forest ignores xgb-only params
        try:
            model.fit(X_train, y_train)
        except TypeError:
            model = RandomForestClassifier(n_estimators=200, random_state=42)
            model.fit(X_train, y_train)

        preds = model.predict(X_test)
        # xgboost 3.x returns the probability matrix from predict
        import numpy as np
        preds = np.asarray(preds)
        if preds.ndim > 1:
            preds = preds.argmax(axis=1)
        f1 = f1_score(y_test, preds, average="macro")
        print(params, "F1:", round(f1, 4))
        print(classification_report(y_test, preds, target_names=list(le.classes_)))

        if mlflow_active:
            try:
                with mlflow.start_run() as run:
                    mlflow.log_params(params)
                    mlflow.log_metric("f1_macro", f1)
                    if HAS_XGB and type(model).__name__ == "XGBClassifier":
                        mlflow.xgboost.log_model(model, "model")
                    else:
                        mlflow.sklearn.log_model(model, "model")
                    run_id = run.info.run_id
            except Exception as e:
                print(f"mlflow log failed: {e}")
                run_id = None
        else:
            run_id = None

        if f1 > best_f1:
            best_f1 = f1
            best_model = model
            best_params = params
            best_run_id = run_id

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifacts")
    os.makedirs(out_dir, exist_ok=True)

    import joblib
    joblib.dump(best_model, os.path.join(out_dir, "model.joblib"))
    with open(os.path.join(out_dir, "labels.json"), "w") as f:
        json.dump(list(le.classes_), f)
    with open(os.path.join(out_dir, "metrics.json"), "w") as f:
        json.dump({"f1_macro": best_f1, "best_params": best_params}, f, indent=2)

    print(f"best F1: {best_f1:.4f} with {best_params}")
    print(f"saved to {out_dir}")

    if mlflow_active and best_run_id:
        try:
            mlflow.register_model(f"runs:/{best_run_id}/model", "incident-severity-model")
            print("registered incident-severity-model from run", best_run_id)
        except Exception as e:
            print(f"registry skipped: {e}")
    elif mlflow_active:
        print("register manually with: mlflow models create / register best run as incident-severity-model")


if __name__ == "__main__":
    main()
