"""Central Agent module for Procurement Desk.

Provides the end-to-end ProcurementAgent coordinating data loading,
playbook rule matching, negotiation decision making, and submission export.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd

from .data_loader import (
    load_threads,
    load_sample_threads,
    load_sample_answers,
    load_sample_submission
)
from .playbook_loader import load_playbook, Playbook
from .decision_engine import make_decision, DecisionResult
from .submission_generator import generate_submission_file, validate_submission_df


class ProcurementAgent:
    """Automated procurement negotiation agent implementing Acme Corp policies."""

    def __init__(self, playbook_dir: Optional[Path] = None):
        self.playbook: Playbook = load_playbook(playbook_dir)

    def decide_thread(self, thread_row: Any) -> DecisionResult:
        """Evaluate a single negotiation thread and generate a decision."""
        return make_decision(thread_row, self.playbook)

    def process_threads(self, threads_df: pd.DataFrame) -> List[DecisionResult]:
        """Process a dataframe of negotiation threads and return all decisions."""
        results = []
        for idx, row in threads_df.iterrows():
            result = self.decide_thread(row)
            results.append(result)
        return results

    def evaluate_sample(
        self,
        sample_threads: Optional[pd.DataFrame] = None,
        sample_answers: Optional[pd.DataFrame] = None
    ) -> Tuple[float, pd.DataFrame, pd.DataFrame]:
        """Run evaluation on sample dataset and return accuracy and evaluation dataframes."""
        threads_df = sample_threads if sample_threads is not None else load_sample_threads()
        answers_df = sample_answers if sample_answers is not None else load_sample_answers()

        results = self.process_threads(threads_df)
        preds_df = pd.DataFrame([
            {'thread_id': r.thread_id, 'label': r.label} for r in results
        ])

        # Merge predictions with ground-truth answers
        eval_df = pd.merge(preds_df, answers_df, on='thread_id', suffixes=('_pred', '_actual'))
        eval_df['is_correct'] = eval_df['label_pred'] == eval_df['label_actual']

        correct_count = eval_df['is_correct'].sum()
        total_count = len(eval_df)
        accuracy = (correct_count / total_count * 100.0) if total_count > 0 else 0.0

        return accuracy, preds_df, eval_df

    def run_full_submission(
        self,
        threads_path: Optional[Path] = None,
        output_csv: Path = Path('output/submission.csv'),
        diagnostics_csv: Optional[Path] = Path('output/error_report.csv')
    ) -> Path:
        """Process all 2,000 threads and generate the verified Kaggle submission file."""
        threads_df = load_threads(threads_path)
        results = self.process_threads(threads_df)
        return generate_submission_file(
            results,
            output_path=output_csv,
            expected_count=2000,
            diagnostics_path=diagnostics_csv
        )
