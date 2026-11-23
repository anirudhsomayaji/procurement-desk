"""Unit tests for offer parsing and price normalization."""

import pytest
from src.offer_parser import (
    words_to_number,
    parse_numeric_value,
    extract_and_normalize_offer,
)
from src.playbook_loader import CategoryRule, SupplierRule


@pytest.fixture
def dummy_category():
    return CategoryRule(
        slug='monitors',
        name='Monitors',
        normalized_unit='INR excl. GST per monitor',
        gst_rate=0.18,
        target_price=14000.0,
        walkaway_price=16500.0,
        total_rounds=3,
        concession_exponent=1.0,
        approval_limit=1200000.0
    )


@pytest.fixture
def dummy_supplier():
    return SupplierRule(
        name='Test Supplier',
        slug='test-supplier',
        status='APPROVED',
        contract_rates={'USD': 82.0},
        price_caps={}
    )


def test_words_to_number():
    assert words_to_number("thirteen thousand rupees") == 13000.0
    assert words_to_number("twenty-six thousand four hundred rupees") == 26400.0
    assert words_to_number("one lakh seven thousand three hundred rupees") == 107300.0
    assert words_to_number("two thousand rupees") == 2000.0


def test_parse_numeric_value():
    assert parse_numeric_value("₹1.2 lakh") == 120000.0
    assert parse_numeric_value("₹58.3k") == 58300.0
    assert parse_numeric_value("Rs. 1,05,042") == 105042.0
    assert parse_numeric_value("INR 14,500.50") == 14500.50


def test_currency_conversion_default(dummy_category):
    sup = SupplierRule(name='Standard Sup', slug='std', status='APPROVED')
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'We can offer USD 100 per monitor.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, sup)
    assert not offer.is_missing_info
    # 100 * 84.5 = 8450
    assert offer.normalized_price == pytest.approx(8450.0)


def test_currency_conversion_contract_override(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'We can offer USD 100 per monitor.'
    }
    # dummy_supplier contract rate is 82.0
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    assert offer.normalized_price == pytest.approx(8200.0)


def test_unlisted_currency_triggers_missing_info(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'We can offer JPY 15000 per monitor.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert offer.is_missing_info


def test_gst_normalization(dummy_category, dummy_supplier):
    # GST rate is 18% (0.18)
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'We can do INR 11,800 per monitor inclusive of GST.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    # 11800 / 1.18 = 10000
    assert offer.normalized_price == pytest.approx(10000.0)


def test_range_quote_takes_higher_end(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'The price is between Rs. 12,000 and ₹14,500 per monitor depending on specs.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    assert offer.normalized_price == 14500.0


def test_free_items_quote(dummy_category, dummy_supplier):
    # Precedent P-02: 1 free for every 10 paid -> price * 10 / 11
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'Our price is ₹11,000 per monitor, plus 1 free monitor for every 10 you pay for.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    assert offer.normalized_price == pytest.approx(11000.0 * 10 / 11.0)


def test_total_quote_divided_by_quantity(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 50,
        'round': 1,
        'supplier_message': 'Our final price is ₹7,50,000 in total for all 50 monitors.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    assert offer.normalized_price == pytest.approx(15000.0)


def test_list_discount(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'We offer a 10% discount on our list price of ₹15,000 per monitor.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    assert offer.normalized_price == pytest.approx(13500.0)


def test_correction_quote(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'CORRECTION — the price in my previous email should read INR 13,800 per monitor, not ₹15,000.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    assert offer.normalized_price == 13800.0


def test_dozen_conversion(dummy_category, dummy_supplier):
    row = {
        'thread_id': 'T999',
        'category': 'monitors',
        'quantity': 24,
        'round': 1,
        'supplier_message': 'We can quote ₹1,44,000 per dozen monitors.'
    }
    offer = extract_and_normalize_offer(row, dummy_category, dummy_supplier)
    assert not offer.is_missing_info
    # 144,000 / 12 = 12,000
    assert offer.normalized_price == 12000.0


def test_ream_to_box_conversion():
    cat = CategoryRule(
        slug='printer-paper',
        name='Printer paper',
        normalized_unit='INR excl. GST per box',
        gst_rate=0.12,
        target_price=2200.0,
        walkaway_price=2600.0,
        total_rounds=3,
        concession_exponent=1.0,
        approval_limit=250000.0,
        pack_conversion='one box = 10 reams.'
    )
    sup = SupplierRule(name='Standard Sup', slug='std', status='APPROVED')
    row = {
        'thread_id': 'T999',
        'category': 'printer-paper',
        'quantity': 10,
        'round': 1,
        'supplier_message': 'We can do ₹250 per ream.'
    }
    offer = extract_and_normalize_offer(row, cat, sup)
    assert not offer.is_missing_info
    # 250 * 10 = 2500
    assert offer.normalized_price == 2500.0
