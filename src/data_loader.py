"""Data loading module for Procurement Desk.

Loads and validates Kaggle competition data files.
"""

from pathlib import Path
from typing import Optional
import pandas as pd


REQUIRED_THREAD_COLUMNS = [
    'thread_id',
    'date',
    'supplier',
    'category',
    'quantity',
    'round',
    'our_last_counter',
    'supplier_message',
]

REQUIRED_ANSWER_COLUMNS = ['thread_id', 'label']


def get_default_data_dir() -> Path:
    """Find the data directory robustly relative to project root or current dir."""
    candidates = [
        Path('data'),
        Path(__file__).resolve().parent.parent / 'data',
        Path.cwd() / 'data',
    ]
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return Path('data')


def validate_threads_df(df: pd.DataFrame, expected_count: Optional[int] = None) -> None:
    """Validate schema, nulls, duplicates, and counts for a threads dataframe."""
    missing_cols = [c for c in REQUIRED_THREAD_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Threads dataframe missing required columns: {missing_cols}")

    if df['thread_id'].duplicated().any():
        dups = df['thread_id'][df['thread_id'].duplicated()].tolist()
        raise ValueError(f"Duplicate thread IDs detected: {dups[:5]}")

    # Check for nulls in required fields (our_last_counter can be NaN in round 1)
    null_cols = ['thread_id', 'date', 'supplier', 'category', 'quantity', 'round', 'supplier_message']
    for col in null_cols:
        if df[col].isnull().any():
            raise ValueError(f"Found unexpected null values in column '{col}'")

    if expected_count is not None and len(df) != expected_count:
        raise ValueError(f"Expected {expected_count} rows, but found {len(df)}")


def load_threads(data_path: Optional[Path] = None) -> pd.DataFrame:
    """Load the full 2,000 negotiation threads."""
    path = data_path or (get_default_data_dir() / 'threads.csv')
    if not Path(path).exists():
        raise FileNotFoundError(f"threads.csv not found at {path}")
    df = pd.read_csv(path)
    validate_threads_df(df, expected_count=2000)
    return df


def load_sample_threads(data_path: Optional[Path] = None) -> pd.DataFrame:
    """Load the 40 sample negotiation threads."""
    path = data_path or (get_default_data_dir() / 'sample_threads.csv')
    if not Path(path).exists():
        raise FileNotFoundError(f"sample_threads.csv not found at {path}")
    df = pd.read_csv(path)
    validate_threads_df(df, expected_count=40)
    return df


def load_sample_answers(data_path: Optional[Path] = None) -> pd.DataFrame:
    """Load the 40 sample ground-truth answers."""
    path = data_path or (get_default_data_dir() / 'sample_answers.csv')
    if not Path(path).exists():
        raise FileNotFoundError(f"sample_answers.csv not found at {path}")
    df = pd.read_csv(path)
    missing_cols = [c for c in REQUIRED_ANSWER_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Answers dataframe missing columns: {missing_cols}")
    if df['thread_id'].duplicated().any():
        raise ValueError("Duplicate thread IDs detected in sample_answers.csv")
    if len(df) != 40:
        raise ValueError(f"Expected 40 sample answers, found {len(df)}")
    return df


def load_sample_submission(data_path: Optional[Path] = None) -> pd.DataFrame:
    """Load the sample submission template."""
    path = data_path or (get_default_data_dir() / 'sample_submission.csv')
    if not Path(path).exists():
        raise FileNotFoundError(f"sample_submission.csv not found at {path}")
    df = pd.read_csv(path)
    missing_cols = [c for c in REQUIRED_ANSWER_COLUMNS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"Submission template missing columns: {missing_cols}")
    if len(df) != 2000:
        raise ValueError(f"Expected 2000 submission rows, found {len(df)}")
    return df
