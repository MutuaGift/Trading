import pandas as pd
import joblib
import os
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

from config import SYMBOLS


def train_symbol(symbol):
    csv_file = f"{symbol}_data.csv"
    model_file = f"{symbol}_model.pkl"

    print(f"\n{'='*50}")
    print(f"Training model for {symbol}...")
    print(f"{'='*50}")

    if not os.path.exists(csv_file):
        print(f"ERROR: {csv_file} not found. Run get_data.py first.")
        return

    try:
        data = pd.read_csv(csv_file)
    except Exception as e:
        print(f"ERROR loading {csv_file}: {e}")
        return

    required_cols = ["RSI", "MA_FAST", "MA_SLOW", "RESULT"]
    for col in required_cols:
        if col not in data.columns:
            print(f"ERROR: Missing column '{col}' in {csv_file}.")
            return

    # Class balance check
    value_counts = data["RESULT"].value_counts(normalize=True)
    print(f"\nClass distribution for {symbol}:")
    for label, pct in value_counts.items():
        label_name = {0: "SELL", 1: "BUY", 2: "FLAT"}.get(label, str(label))
        print(f"  {label_name} ({label}): {pct * 100:.1f}%")
        if pct > 0.70:
            print(f"  WARNING: Class {label_name} makes up {pct*100:.1f}% of data — model may be biased!")

    X = data[["RSI", "MA_FAST", "MA_SLOW"]]
    y = data["RESULT"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"\nData split: {len(X_train)} training, {len(X_test)} testing samples.")

    candidates = {
        "LogisticRegression": Pipeline([
            ('scaler', StandardScaler()),
            ('classifier', LogisticRegression(max_iter=1000))
        ]),
        "RandomForest": Pipeline([
            ('scaler', StandardScaler()),
            ('classifier', RandomForestClassifier(n_estimators=100, random_state=42))
        ]),
        "GradientBoosting": Pipeline([
            ('scaler', StandardScaler()),
            ('classifier', GradientBoostingClassifier(n_estimators=100, random_state=42))
        ]),
    }

    print("\nRunning 5-fold cross-validation...")
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    best_name = None
    best_score = -1
    best_pipeline = None

    for name, pipeline in candidates.items():
        scores = cross_val_score(pipeline, X_train, y_train, cv=cv, scoring="accuracy")
        mean_score = scores.mean()
        print(f"  {name}: CV Accuracy = {mean_score * 100:.2f}% (+/- {scores.std() * 100:.2f}%)")
        if mean_score > best_score:
            best_score = mean_score
            best_name = name
            best_pipeline = pipeline

    print(f"\nBest model for {symbol}: {best_name} (CV accuracy={best_score * 100:.2f}%)")

    best_pipeline.fit(X_train, y_train)

    predictions = best_pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)

    print(f"\nFINAL TEST ACCURACY ({best_name}): {accuracy * 100:.2f}%")
    print("Confusion Matrix:")
    print(confusion_matrix(y_test, predictions))
    print("\nClassification Report:")
    print(classification_report(y_test, predictions, zero_division=0))

    joblib.dump(best_pipeline, model_file)
    print(f"SUCCESS: '{best_name}' saved as '{model_file}'")


if __name__ == "__main__":
    for symbol in SYMBOLS:
        train_symbol(symbol)
    print("\nAll symbols trained.")
