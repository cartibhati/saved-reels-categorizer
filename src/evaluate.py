import json
import sqlite3
import pandas as pd
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "db" / "reels.db"
CATEGORIES_PATH = PROJECT_ROOT / "config" / "categories.json"

def load_mappings():
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Return a dict of {collection_name: expected_category} for confirmed collections
    mappings = {}
    for m in data.get("collection_mappings", []):
        if m.get("status") != "unconfirmed":
            mappings[m["collection_name"]] = m["mapped_category"]
    return mappings

def run_evaluation():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    mappings = load_mappings()
    if not mappings:
        print("No confirmed collection mappings found.")
        return

    # Fetch all items that belong to a confirmed collection
    query = """
    SELECT url, existing_collection, category, secondary_category, confidence, summary, caption
    FROM reels
    WHERE existing_collection IS NOT NULL AND existing_collection != ''
    """
    cursor.execute(query)
    posts = [dict(row) for row in cursor.fetchall()]
    conn.close()

    eval_data = []
    for p in posts:
        coll = p["existing_collection"]
        if coll in mappings:
            expected = mappings[coll]
            predicted = p["category"]
            eval_data.append({
                "url": p["url"],
                "collection": coll,
                "expected": expected,
                "predicted": predicted,
                "confidence": p["confidence"],
                "caption": p["caption"],
                "is_correct": (expected == predicted)
            })

    if not eval_data:
        print("No data to evaluate.")
        return

    df = pd.DataFrame(eval_data)
    total_eval = len(df)
    correct_count = df["is_correct"].sum()
    accuracy = correct_count / total_eval * 100

    print("=" * 60)
    print("PHASE 4: EVALUATION REPORT")
    print("=" * 60)
    print(f"Total Posts Evaluated : {total_eval}")
    print(f"Overall Accuracy      : {accuracy:.1f}% ({correct_count}/{total_eval})")
    print("=" * 60)
    
    # Confusion Matrix
    print("\nCONFUSION MATRIX (Expected vs Predicted):")
    # Pandas crosstab
    matrix = pd.crosstab(df['expected'], df['predicted'], margins=True, margins_name="Total")
    print(matrix.to_string())

    # Common misclassifications
    print("\n" + "=" * 60)
    print("TOP MISCLASSIFICATIONS")
    print("=" * 60)
    errors = df[~df["is_correct"]]
    if not errors.empty:
        error_counts = errors.groupby(["expected", "predicted"]).size().reset_index(name="count")
        error_counts = error_counts.sort_values(by="count", ascending=False)
        for _, row in error_counts.head(10).iterrows():
            print(f"Expected: {row['expected']:<35} | Predicted: {row['predicted']:<35} | Count: {row['count']}")
        
        # Print a few examples of the top error
        top_err = error_counts.iloc[0]
        print(f"\nExamples of Expected [{top_err['expected']}] classified as [{top_err['predicted']}]:")
        sample_errors = errors[(errors["expected"] == top_err["expected"]) & (errors["predicted"] == top_err["predicted"])]
        for _, err_row in sample_errors.head(3).iterrows():
            cap = err_row['caption'].replace('\n', ' ')
            if len(cap) > 100: cap = cap[:100] + "..."
            print(f" - URL: {err_row['url']}")
            print(f"   Caption: {cap}")
            print(f"   Confidence: {err_row['confidence']}")
    else:
        print("No misclassifications found!")

if __name__ == "__main__":
    run_evaluation()
