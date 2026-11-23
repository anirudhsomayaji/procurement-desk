"""Offer parser module for Procurement Desk.

Extracts, converts, and normalizes supplier price quotations following
units-and-currency.md and relevant precedent and category policies.
"""

from dataclasses import dataclass
import re
from typing import Optional, Tuple, Dict, Any


DEFAULT_EXCHANGE_RATES = {
    'INR': 1.0,
    'USD': 84.5,
    'EUR': 91.0,
    'GBP': 106.0,
}

UNLISTED_CURRENCIES = [
    'JPY', 'AED', 'SGD', 'CAD', 'AUD', 'CNY', 'CHF', 'YEN', 'PESO', 'WON', 'RUB'
]

SUBSCRIPTION_CATEGORIES_ANNUAL = {'cloud-servers', 'crm-licenses', 'design-software'}
SUBSCRIPTION_CATEGORIES_MONTHLY = {'cleaning', 'security-guards'}
ALL_SUBSCRIPTION_CATEGORIES = SUBSCRIPTION_CATEGORIES_ANNUAL | SUBSCRIPTION_CATEGORIES_MONTHLY

ONES = {
    'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
    'eleven': 11, 'twelve': 12, 'thirteen': 13, 'fourteen': 14,
    'fifteen': 15, 'sixteen': 16, 'seventeen': 17, 'eighteen': 18,
    'nineteen': 19
}

TENS = {
    'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
    'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90
}


@dataclass
class ParsedOffer:
    normalized_price: Optional[float]
    is_missing_info: bool
    raw_quoted_price: Optional[float] = None
    currency: str = "INR"
    exchange_rate: float = 1.0
    is_gst_inclusive: bool = False
    details: Dict[str, Any] = None


def extract_latest_message(thread_message: str) -> str:
    """Return only the latest message in the thread conversation."""
    if not thread_message:
        return ""
    if '[Latest message' in thread_message:
        return thread_message.split('[Latest message')[-1]
    return thread_message


def words_to_number(text: str) -> Optional[float]:
    """Convert English word numerals (including Indian lakh/crore) to float."""
    tokens = re.findall(r'[a-z]+', text.lower())
    total = 0
    current = 0
    matched = False

    for token in tokens:
        if token in ONES:
            current += ONES[token]
            matched = True
        elif token in TENS:
            current += TENS[token]
            matched = True
        elif token == 'hundred':
            current = (current if current != 0 else 1) * 100
            matched = True
        elif token == 'thousand':
            total += (current if current != 0 else 1) * 1000
            current = 0
            matched = True
        elif token in ['lakh', 'lacs', 'lac']:
            total += (current if current != 0 else 1) * 100000
            current = 0
            matched = True
        elif token in ['crore', 'crores']:
            total += (current if current != 0 else 1) * 10000000
            current = 0
            matched = True
        elif token in ['and', 'rupees', 'rupee', 'inr']:
            continue
        else:
            if matched:
                break
            continue

    total += current
    return float(total) if matched else None


def parse_numeric_value(s: str) -> Optional[float]:
    """Parse number from string, supporting words, lakh/k notation, commas, and currency prefixes."""
    s = s.strip()

    # Check numeric lakh / k notation FIRST (e.g. 1.2 lakh, 18.5k)
    m_lakh = re.search(r'([\d\.]+)\s*(?:lakh|lacs|lac)\b', s, re.IGNORECASE)
    if m_lakh:
        return float(m_lakh.group(1)) * 100000.0

    m_k = re.search(r'([\d\.]+)\s*k\b', s, re.IGNORECASE)
    if m_k:
        return float(m_k.group(1)) * 1000.0

    # Check words if words like thousand/hundred/lakh are present without a leading number
    word_keywords = [
        'thousand', 'hundred', 'lakh', 'twenty', 'thirty', 'forty',
        'fifty', 'sixty', 'seventy', 'eighty', 'ninety'
    ]
    if any(w in s.lower() for w in word_keywords):
        wn = words_to_number(s)
        if wn is not None:
            return wn

    # Prefer number following currency symbol
    m_curr = re.search(r'(?:₹|Rs\.|INR|USD|EUR|GBP|\$|€|£)\s*([\d,]+(?:\.\d+)?)', s, re.IGNORECASE)
    if m_curr:
        clean = m_curr.group(1).replace(',', '')
        try:
            return float(clean)
        except ValueError:
            pass

    # Prefer number following pricing keywords
    m_after_kw = re.search(
        r'(?:quote|offer|price is|can do|read)\s+(?:INR|Rs\.|₹|\$|€|£)?\s*([\d,]+(?:\.\d+)?)',
        s,
        re.IGNORECASE
    )
    if m_after_kw:
        clean = m_after_kw.group(1).replace(',', '')
        try:
            return float(clean)
        except ValueError:
            pass

    # Fallback to the last numeric string in the chunk (avoids matching quantity at start)
    all_nums = re.findall(r'[\d,]+(?:\.\d+)?', s)
    if all_nums:
        clean = all_nums[-1].replace(',', '')
        try:
            return float(clean)
        except ValueError:
            return None

    return None


def extract_and_normalize_offer(
    thread_row: Any,
    category_rule: Any,
    supplier_rule: Any
) -> ParsedOffer:
    """Extract and normalize the current supplier offer to INR excl. GST per normalized unit.

    Returns ParsedOffer containing normalized price and is_missing_info flag.
    """
    full_msg = thread_row['supplier_message']
    latest = extract_latest_message(full_msg)
    cat_slug = thread_row['category']
    quantity = int(thread_row['quantity'])

    # 1. Check for missing information: no usable price
    no_price_phrases = [
        "pricing will depend on the final specs",
        "pricing will depend on final specs",
        "let's get on a call to discuss",
        "get on a call to discuss",
        "please share them and we will revert",
    ]
    if any(p in latest.lower() for p in no_price_phrases):
        return ParsedOffer(normalized_price=None, is_missing_info=True, details={"reason": "no_usable_price"})

    # 2. Check for unlisted currency
    for unlisted in UNLISTED_CURRENCIES:
        if re.search(r'\b' + unlisted + r'\b', latest, re.IGNORECASE):
            return ParsedOffer(normalized_price=None, is_missing_info=True, details={"reason": f"unlisted_currency_{unlisted}"})

    # 3. Detect currency
    currency = 'INR'
    if re.search(r'\bUSD\b|\$', latest, re.IGNORECASE):
        currency = 'USD'
    elif re.search(r'\bEUR\b|€', latest, re.IGNORECASE):
        currency = 'EUR'
    elif re.search(r'\bGBP\b|£', latest, re.IGNORECASE):
        currency = 'GBP'

    # Exchange rate lookup: supplier contract overrides default table
    if currency == 'USD':
        rate = supplier_rule.contract_rates.get('USD', DEFAULT_EXCHANGE_RATES['USD'])
    elif currency == 'EUR':
        rate = supplier_rule.contract_rates.get('EUR', DEFAULT_EXCHANGE_RATES['EUR'])
    elif currency == 'GBP':
        rate = supplier_rule.contract_rates.get('GBP', DEFAULT_EXCHANGE_RATES['GBP'])
    else:
        rate = 1.0

    # 4. GST inclusion check
    is_gst_inclusive = bool(re.search(
        r'inclusive of gst|including gst|\(gst included\)|incl\. gst',
        latest,
        re.IGNORECASE
    ))

    price_val: Optional[float] = None
    pattern_matched = "unknown"

    # Pattern A: CORRECTION
    m_corr = re.search(r'CORRECTION — the price in my previous email should read (.*?), not', latest, re.IGNORECASE)
    if m_corr:
        pattern_matched = "correction"
        price_val = parse_numeric_value(m_corr.group(1))

    # Pattern B: Range quote (Precedent P-01, P-04)
    elif re.search(r'between\s+(.*?)\s+and\s+(.*?)\s+per', latest, re.IGNORECASE):
        pattern_matched = "range"
        m_range = re.search(r'between\s+(.*?)\s+and\s+(.*?)\s+per', latest, re.IGNORECASE)
        # Evaluated at higher end
        price_val = parse_numeric_value(m_range.group(2))

    # Pattern C: Free items (Precedent P-02, P-05)
    elif re.search(r'plus 1 free (?:.*?) for every (\d+) you pay for', latest, re.IGNORECASE):
        pattern_matched = "free_items"
        m_free = re.search(r'(.*?)\s+per\s+(.*?), plus 1 free (?:.*?) for every (\d+) you pay for', latest, re.IGNORECASE)
        if m_free:
            base_p = parse_numeric_value(m_free.group(1))
            k = float(m_free.group(3))
            if base_p is not None:
                price_val = base_p * k / (k + 1.0)

    # Pattern D: Total for all units (units-and-currency.md)
    elif re.search(r'in total for all (\d+)', latest, re.IGNORECASE):
        pattern_matched = "total_all_units"
        m_tot = re.search(r'(.*?)\s+in total for all (\d+)', latest, re.IGNORECASE)
        if m_tot:
            tot_p = parse_numeric_value(m_tot.group(1))
            n_units = float(m_tot.group(2))
            if tot_p is not None and n_units > 0:
                price_val = tot_p / n_units

    # Pattern E: List price discount (units-and-currency.md)
    elif re.search(r'(\d+(?:\.\d+)?%)\s+discount on our list price of\s+(.*?)\s+per', latest, re.IGNORECASE):
        pattern_matched = "list_discount"
        m_disc = re.search(r'(\d+(?:\.\d+)?%)\s+discount on our list price of\s+(.*?)\s+per', latest, re.IGNORECASE)
        disc_pct = float(m_disc.group(1).replace('%', '')) / 100.0
        base_p = parse_numeric_value(m_disc.group(2))
        if base_p is not None:
            price_val = base_p * (1.0 - disc_pct)

    # Pattern F: Previous quote discount (units-and-currency.md)
    elif re.search(r'(\d+(?:\.\d+)?%)\s+off our previous quote', latest, re.IGNORECASE):
        pattern_matched = "previous_quote_discount"
        m_prev = re.search(r'(\d+(?:\.\d+)?%)\s+off our previous quote', latest, re.IGNORECASE)
        disc_pct = float(m_prev.group(1).replace('%', '')) / 100.0
        # Search for supplier's own earlier quote in the thread
        m_earlier = re.findall(
            r'(?:quote is|earlier quote was|we can do)\s+([^\n]+?)\s+per',
            full_msg,
            re.IGNORECASE
        )
        if m_earlier:
            base_p = parse_numeric_value(m_earlier[-1])
            if base_p is not None:
                price_val = base_p * (1.0 - disc_pct)

    # Pattern G: Tiered pricing (units-and-currency.md)
    elif re.search(r'for orders of up to (\d+)\s+.*?, and (.*?)\s+per\s+.*?for larger orders', latest, re.IGNORECASE):
        pattern_matched = "tiered_split"
        m_tier = re.search(
            r'(.*?)\s+per\s+.*?for orders of up to (\d+)\s+.*?, and (.*?)\s+per\s+.*?for larger orders',
            latest,
            re.IGNORECASE
        )
        p1 = parse_numeric_value(m_tier.group(1))
        t_qty = int(m_tier.group(2))
        p2 = parse_numeric_value(m_tier.group(3))
        price_val = p1 if quantity <= t_qty else p2

    elif re.search(r'(.*?)\s+per\s+.*?, with a further (\d+(?:\.\d+)?%)\s+off for orders of (\d+)\s+.*?or more', latest, re.IGNORECASE):
        pattern_matched = "tiered_volume_discount"
        m_tier2 = re.search(
            r'(.*?)\s+per\s+.*?, with a further (\d+(?:\.\d+)?%)\s+off for orders of (\d+)\s+.*?or more',
            latest,
            re.IGNORECASE
        )
        base_p = parse_numeric_value(m_tier2.group(1))
        t_disc = float(m_tier2.group(2).replace('%', '')) / 100.0
        t_qty = int(m_tier2.group(3))
        if base_p is not None:
            price_val = base_p * (1.0 - t_disc) if quantity >= t_qty else base_p

    # Pattern H: Standard per-unit quotation
    else:
        pattern_matched = "standard_quote"
        m_std = re.search(
            r'(?:quote|offer|price is|can do|can offer)\s+(?:a\s+)?([^\n]+?)\s+per\s+([^\n\.,]+)',
            latest,
            re.IGNORECASE
        )
        if m_std:
            price_val = parse_numeric_value(m_std.group(1))

    if price_val is None:
        return ParsedOffer(
            normalized_price=None,
            is_missing_info=True,
            details={"reason": "unparseable_price", "pattern": pattern_matched}
        )

    raw_price = price_val

    # 5. Pack and sub-unit conversions
    if re.search(r'per pack of 4 fixtures', latest, re.IGNORECASE):
        price_val /= 4.0
    elif re.search(r'per dozen', latest, re.IGNORECASE):
        price_val /= 12.0
    elif re.search(r'per ream\b', latest, re.IGNORECASE) and cat_slug == 'printer-paper':
        price_val *= 10.0

    # 6. Subscription billing period conversions
    if cat_slug in SUBSCRIPTION_CATEGORIES_ANNUAL:
        # Category requires annual. If quoted monthly, multiply by 12
        if re.search(r'per\s+(?:seat|server)\s+per\s+month\b|per\s+month\b', latest, re.IGNORECASE):
            price_val *= 12.0
    elif cat_slug in SUBSCRIPTION_CATEGORIES_MONTHLY:
        # Category requires monthly. If quoted yearly/annual, divide by 12
        if re.search(r'per\s+(?:site|guard)\s+per\s+year\b|per\s+year\b|annually\b', latest, re.IGNORECASE):
            price_val /= 12.0

    # 7. Currency conversion to INR
    price_inr = price_val * rate

    # 8. GST normalization: divide by (1 + GST) if GST inclusive
    if is_gst_inclusive:
        price_inr /= (1.0 + category_rule.gst_rate)

    return ParsedOffer(
        normalized_price=price_inr,
        is_missing_info=False,
        raw_quoted_price=raw_price,
        currency=currency,
        exchange_rate=rate,
        is_gst_inclusive=is_gst_inclusive,
        details={"pattern": pattern_matched}
    )
