"""Evaluation script for sample dataset against ground truth answers.

Loads sample threads, makes decisions, joins with sample_answers.csv,
calculates accuracy, reports correct and incorrect predictions,
and saves sample_predictions.csv and sample_evaluation.csv.
"""

from pathlib import Path
import pandas as pd
from src.agent import ProcurementAgent


def run_sample_evaluation():
    print("=" * 60)
    print("PROCUREMENT DESK — SAMPLE EVALUATION (40 THREADS)")
    print("=" * 60)

    agent = ProcurementAgent()
    accuracy, preds_df, eval_df = agent.evaluate_sample()

    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)

    preds_path = output_dir / "sample_predictions.csv"
    eval_path = output_dir / "sample_evaluation.csv"

    preds_df.to_csv(preds_path, index=False)
    eval_df.to_csv(eval_path, index=False)

    print(f"\nSaved sample predictions to: {preds_path}")
    print(f"Saved sample evaluation to:  {eval_path}")

    # Summary
    correct_df = eval_df[eval_df['is_correct']]
    incorrect_df = eval_df[~eval_df['is_correct']]

    print(f"\nTotal sample threads processed: {len(eval_df)}")
    print(f"Correct predictions:            {len(correct_df)}")
    print(f"Incorrect predictions:          {len(incorrect_df)}")
    print(f"Exact-match Accuracy:           {accuracy:.2f}%\n")

    print("-" * 60)
    print("PREDICTION BREAKDOWN BY THREAD:")
    print("-" * 60)
    for idx, row in eval_df.iterrows():
        status = "MATCH" if row['is_correct'] else "MISMATCH"
        print(f"[{row['thread_id']}] {status:8s} | Expected: {row['label_actual']:<30s} | Predicted: {row['label_pred']}")

    if len(incorrect_df) > 0:
        print("\n" + "!" * 60)
        print("MISMATCH DETAILS:")
        print("!" * 60)
        for idx, row in incorrect_df.iterrows():
            print(f"Thread:   {row['thread_id']}")
            print(f"Expected: {row['label_actual']}")
            print(f"Got:      {row['label_pred']}\n")

    # Action-level breakdown
    print("\n" + "-" * 60)
    print("ACTION DISTRIBUTION (PREDICTED vs ACTUAL):")
    print("-" * 60)
    eval_df['action_pred'] = eval_df['label_pred'].apply(lambda x: x.split(':')[0])
    eval_df['action_actual'] = eval_df['label_actual'].apply(lambda x: x.split(':')[0])
    print("\nActual actions:")
    print(eval_df['action_actual'].value_counts())
    print("\nPredicted actions:")
    print(eval_df['action_pred'].value_counts())

    action_acc = (eval_df['action_pred'] == eval_df['action_actual']).mean() * 100.0
    print(f"\nAction-level Accuracy: {action_acc:.2f}%")

    return accuracy


if __name__ == "__main__":
    run_sample_evaluation()
