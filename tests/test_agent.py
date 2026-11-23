"""Integration tests for ProcurementAgent."""

from pathlib import Path
import pandas as pd
from src.agent import ProcurementAgent
from src.submission_generator import validate_submission_df


def test_agent_sample_evaluation():
    agent = ProcurementAgent()
    accuracy, preds_df, eval_df = agent.evaluate_sample()

    # Exact match on all 40 sample threads
    assert len(eval_df) == 40
    assert accuracy == 100.0, f"Expected 100.0% accuracy on sample set, got {accuracy}%\nMismatches:\n{eval_df[~eval_df['is_correct']]}"

    # Verify predictions dataframe schema
    assert list(preds_df.columns) == ['thread_id', 'label']
    is_valid, errors = validate_submission_df(preds_df, expected_count=40)
    assert is_valid, f"Sample predictions failed validation: {errors}"


def test_agent_submission_generation(tmp_path):
    agent = ProcurementAgent()
    out_file = tmp_path / "test_submission.csv"
    diag_file = tmp_path / "test_diag.csv"

    res_path = agent.run_full_submission(
        output_csv=out_file,
        diagnostics_csv=diag_file
    )

    assert res_path.exists()
    sub_df = pd.read_csv(res_path)
    assert len(sub_df) == 2000
    assert list(sub_df.columns) == ['thread_id', 'label']

    is_valid, errors = validate_submission_df(sub_df, expected_count=2000)
    assert is_valid, f"Generated submission failed validation: {errors}"

    assert diag_file.exists()
    diag_df = pd.read_csv(diag_file)
    assert len(diag_df) == 2000
