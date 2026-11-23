"""CLI runner for Procurement Desk.

Usage:
    python run.py --mode sample     # Run sample evaluation on 40 threads
    python run.py --mode test       # Run all pytest unit tests
    python run.py --mode full       # Generate full submission for 2,000 threads
    python run.py --mode validate   # Validate the generated submission file
"""

import argparse
from pathlib import Path
import sys
import subprocess
import pandas as pd

from src.agent import ProcurementAgent
from src.submission_generator import validate_submission_df
from src.data_loader import load_threads


def mode_sample():
    print("\n[RUNNER] Running Sample Evaluation (40 Threads)...")
    agent = ProcurementAgent()
    accuracy, preds_df, eval_df = agent.evaluate_sample()

    out_dir = Path("output")
    out_dir.mkdir(parents=True, exist_ok=True)
    preds_path = out_dir / "sample_predictions.csv"
    eval_path = out_dir / "sample_evaluation.csv"

    preds_df.to_csv(preds_path, index=False)
    eval_df.to_csv(eval_path, index=False)

    print(f"[SUCCESS] Sample evaluation completed.")
    print(f"  Accuracy: {accuracy:.2f}% ({int(eval_df['is_correct'].sum())}/{len(eval_df)})")
    print(f"  Saved predictions: {preds_path}")
    print(f"  Saved evaluation:  {eval_path}")

    if accuracy < 100.0:
        print("[WARNING] Not all sample predictions matched.")
        mismatches = eval_df[~eval_df['is_correct']]
        for idx, r in mismatches.iterrows():
            print(f"  Mismatch {r['thread_id']}: Expected={r['label_actual']} Got={r['label_pred']}")
        sys.exit(1)


def mode_test():
    print("\n[RUNNER] Running Unit Test Suite with pytest...")
    result = subprocess.run([sys.executable, "-m", "pytest", "tests", "-v"], check=False)
    sys.exit(result.returncode)


def mode_full():
    print("\n[RUNNER] Processing Full Dataset (2,000 Threads)...")
    agent = ProcurementAgent()
    out_file = Path("output/submission.csv")
    diag_file = Path("output/error_report.csv")

    sub_path = agent.run_full_submission(
        output_csv=out_file,
        diagnostics_csv=diag_file
    )

    df = pd.read_csv(sub_path)
    print(f"[SUCCESS] Full submission generated successfully!")
    print(f"  Submission path: {sub_path} ({len(df)} rows)")
    print(f"  Diagnostics log: {diag_file}")
    print("\nLabel Distribution:")
    counts = df['label'].apply(lambda x: x.split(':')[0] + ':' + x.split(':')[1]).value_counts()
    for lbl, count in counts.items():
        print(f"  {lbl:<30s}: {count}")


def mode_validate():
    print("\n[RUNNER] Validating Submission File...")
    sub_path = Path("output/submission.csv")
    if not sub_path.exists():
        print(f"[ERROR] Submission file not found at {sub_path}. Run with '--mode full' first.")
        sys.exit(1)

    df = pd.read_csv(sub_path)
    is_valid, errors = validate_submission_df(df, expected_count=2000)

    # Check match with threads.csv thread_ids
    threads_df = load_threads()
    expected_ids = threads_df['thread_id'].tolist()
    actual_ids = df['thread_id'].tolist()

    if expected_ids != actual_ids:
        errors.append("Thread IDs or order do not exactly match threads.csv")

    if is_valid and not errors:
        print(f"[SUCCESS] Submission file is 100% VALID and compliant!")
        print(f"  Path: {sub_path}")
        print(f"  Rows: {len(df)}")
        print(f"  Columns: {list(df.columns)}")
        print("  All 2,000 thread IDs are unique, valid, and ordered properly.")
    else:
        print(f"[FAILED] Submission file validation failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Procurement Desk Competition Runner")
    parser.add_argument(
        "--mode",
        choices=["sample", "test", "full", "validate"],
        required=True,
        help="Execution mode"
    )
    args = parser.parse_args()

    if args.mode == "sample":
        mode_sample()
    elif args.mode == "test":
        mode_test()
    elif args.mode == "full":
        mode_full()
    elif args.mode == "validate":
        mode_validate()


if __name__ == "__main__":
    main()
