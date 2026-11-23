"""Unit tests for data and playbook loading."""

import pytest
import pandas as pd
from src.data_loader import (
    load_threads,
    load_sample_threads,
    load_sample_answers,
    load_sample_submission,
    validate_threads_df,
)
from src.playbook_loader import load_playbook


def test_load_sample_threads():
    df = load_sample_threads()
    assert len(df) == 40
    assert 'thread_id' in df.columns
    assert 'supplier_message' in df.columns
    assert not df['thread_id'].duplicated().any()


def test_load_sample_answers():
    df = load_sample_answers()
    assert len(df) == 40
    assert list(df.columns) == ['thread_id', 'label']
    assert not df['thread_id'].duplicated().any()


def test_load_sample_submission():
    df = load_sample_submission()
    assert len(df) == 2000
    assert list(df.columns) == ['thread_id', 'label']


def test_load_full_threads():
    df = load_threads()
    assert len(df) == 2000
    assert not df['thread_id'].duplicated().any()


def test_validate_threads_missing_columns():
    bad_df = pd.DataFrame({'thread_id': ['T001']})
    with pytest.raises(ValueError, match="missing required columns"):
        validate_threads_df(bad_df)


def test_validate_threads_duplicate_ids():
    df = load_sample_threads()
    bad_df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate thread IDs detected"):
        validate_threads_df(bad_df)


def test_playbook_loading():
    playbook = load_playbook()
    # 15 categories
    assert len(playbook.categories) == 15
    assert 'laptops' in playbook.categories
    assert 'catering' in playbook.categories
    assert 'monitors' in playbook.categories

    # 9 amendments
    assert len(playbook.amendments) == 9
    assert playbook.amendments[0].effective_date <= playbook.amendments[-1].effective_date

    # 40 suppliers
    assert len(playbook.suppliers) == 40
    # Check statuses
    statuses = {s.status for s in playbook.suppliers.values()}
    assert statuses == {'APPROVED', 'PROBATION', 'BLACKLISTED'}

    # Check contracts
    jupiter = playbook.suppliers['Jupiter Devices']
    assert jupiter.price_caps.get('monitors') == 17600.0

    kestrel = playbook.suppliers['Kestrel Learning']
    assert kestrel.contract_rates.get('EUR') == 90.5
