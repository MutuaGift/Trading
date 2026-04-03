import pandas as pd
import joblib
import os
from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.pipeline import Pipeline
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix

def train_ai():
    print("Initializing AI Training Sequence...")

    # 1. Load Data Safely
    if not os.path.exists("market_data.csv"):
        print("ERROR: market_data.csv not found!")
        print("Please ensure your historical data file is in the same folder.")
        return

    try:
        data = pd.read_csv("market_data.csv")
    except Exception as e:
        print(f"ERROR loading CSV: {e}")
        return

    # Ensure required columns exist
    required_cols = ["RSI", "MA_FAST", "MA_SLOW", "RESULT"]
    for col in required_cols:
        if col not in data.columns:
            print(f"ERROR: Missing column '{col}' in CSV.")
            return

    # 2. Class Balance Check
    value_counts = data["RESULT"].value_counts(normalize=True)
    print("\nClass distribution:")
    for label, pct in value_counts.items():
        label_name = {0: "SELL", 1: "BUY", 2: "FLAT"}.get(label, str(label))
        print(f"  {label_name} ({label}): {pct * 100:.1f}%")
        if pct > 0.70:
            print(f"  WARNING: Class {label_name} makes up {pct*100:.1f}% of data — model may be biased!")

    # 3. Prepare Features and Target
    # Support FLAT=2 if present, otherwise binary BUY/SELL
    X = data[["RSI", "MA_FAST", "MA_SLOW"]]
    y = data["RESULT"]

    # 4. Stratified Split (80% train, 20% test)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"\nData split: {len(X_train)} training samples, {len(X_test)} testing samples.")

    # 5. Define Candidate Models
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

    # 6. 5-Fold Cross-Validation to Pick Best Model
    print("\nRunning 5-fold cross-validation on all models...")
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

    print(f"\nBest model: {best_name} (CV accuracy={best_score * 100:.2f}%)")

    # 7. Train Best Model on Full Training Set
    print(f"Training {best_name} on full training data...")
    best_pipeline.fit(X_train, y_train)

    # 8. Evaluate on Test Set
    print("\nTesting against unseen data...")
    predictions = best_pipeline.predict(X_test)
    accuracy = accuracy_score(y_test, predictions)

    print("\n" + "="*40)
    print(f"FINAL TEST ACCURACY ({best_name}): {accuracy * 100:.2f}%")
    print("="*40)
    print("Confusion Matrix:")
    print(confusion_matrix(y_test, predictions))
    print("\nClassification Report:")
    print(classification_report(y_test, predictions, zero_division=0))
    print("="*40 + "\n")

    # 9. Save the Best Model
    joblib.dump(best_pipeline, "model.pkl")
    print(f"SUCCESS: '{best_name}' saved as 'model.pkl' and ready for live trading!")

if __name__ == "__main__":
    train_ai()
