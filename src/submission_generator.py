"""Submission generator and validator for Procurement Desk.

Creates and validates compliant Kaggle submission CSV files.
"""

from pathlib import Path
import re
from typing import List, Optional, Tuple, Dict, Any
import pandas as pd

from .decision_engine import DecisionResult


VALID_ACTIONS = {'ACCEPT', 'COUNTER', 'REJECT', 'ESCALATE'}
LABEL_REGEX = re.compile(
    r'^(ACCEPT:[A-Z_]+:|COUNTER:[A-Z_]+:\d+|REJECT:[A-Z_]+:|ESCALATE:[A-Z_]+:)$'
)


def validate_submission_df(df: pd.DataFrame, expected_count: Optional[int] = 2000) -> Tuple[bool, List[str]]:
    """Strictly validate that submission adheres to Kaggle competition specifications."""
    errors = []

    # 1. Exactly two columns
    expected_cols = ['thread_id', 'label']
    if list(df.columns) != expected_cols:
        errors.append(f"Expected columns {expected_cols}, got {list(df.columns)}")

    # 2. Row count
    if expected_count is not None and len(df) != expected_count:
        errors.append(f"Expected {expected_count} rows, got {len(df)}")

    # 3. Duplicate or missing IDs
    if df['thread_id'].isnull().any():
        errors.append("Null thread IDs found in submission")
    if df['thread_id'].duplicated().any():
        dups = df['thread_id'][df['thread_id'].duplicated()].tolist()
        errors.append(f"Duplicate thread IDs found: {dups[:5]}")

    # 4. Label formatting check
    invalid_labels = []
    for idx, row in df.iterrows():
        lbl = str(row['label'])
        if not LABEL_REGEX.match(lbl):
            invalid_labels.append((row['thread_id'], lbl))

    if invalid_labels:
        errors.append(f"Found {len(invalid_labels)} invalid label format(s): {invalid_labels[:5]}")

    return len(errors) == 0, errors


def generate_submission_file(
    results: List[DecisionResult],
    output_path: Path,
    expected_count: Optional[int] = 2000,
    diagnostics_path: Optional[Path] = None
) -> Path:
    """Validate and write final submission CSV atomically.

    Writes to a temporary file first, validates all schema rules, and replaces target.
    Optionally saves detailed decision diagnostics separately.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [{'thread_id': r.thread_id, 'label': r.label} for r in results]
    df = pd.DataFrame(rows, columns=['thread_id', 'label'])

    # Validate dataframe before writing
    is_valid, errors = validate_submission_df(df, expected_count=expected_count)
    if not is_valid:
        raise ValueError(f"Submission validation failed with errors:\n" + "\n".join(errors))

    # Write atomically via temp file
    temp_path = output_path.with_suffix('.tmp.csv')
    df.to_csv(temp_path, index=False)

    # Verify written file can be read and re-validated
    verify_df = pd.read_csv(temp_path)
    is_valid_re, errors_re = validate_submission_df(verify_df, expected_count=expected_count)
    if not is_valid_re:
        if temp_path.exists():
            temp_path.unlink()
        raise ValueError(f"Written submission file failed validation:\n" + "\n".join(errors_re))

    temp_path.replace(output_path)

    # Save diagnostics if requested
    if diagnostics_path:
        diag_path = Path(diagnostics_path)
        diag_path.parent.mkdir(parents=True, exist_ok=True)
        diag_rows = []
        for r in results:
            diag_rows.append({
                'thread_id': r.thread_id,
                'action': r.action,
                'reason': r.reason,
                'counter_price': r.counter_price,
                'label': r.label,
                'category': r.diagnostics.get('category'),
                'supplier': r.diagnostics.get('supplier'),
                'supplier_status': r.diagnostics.get('supplier_status'),
                'quantity': r.diagnostics.get('quantity'),
                'round': r.diagnostics.get('round'),
                'normalized_price': r.diagnostics.get('normalized_price'),
                'concession_level_L': r.diagnostics.get('concession_level_L'),
                'total_order_value': r.diagnostics.get('total_order_value'),
                'approval_limit': r.diagnostics.get('approval_limit'),
            })
        pd.DataFrame(diag_rows).to_csv(diag_path, index=False)

    return output_path
