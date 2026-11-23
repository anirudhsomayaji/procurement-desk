"""Playbook loader module for Procurement Desk.

Loads, parses, and structures all playbook policies, category definitions,
dated amendments, supplier contracts, and historical precedents.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Dict, List, Optional


@dataclass
class CategoryRule:
    slug: str
    name: str
    normalized_unit: str
    gst_rate: float
    target_price: float
    walkaway_price: float
    total_rounds: int
    concession_exponent: float
    approval_limit: float
    pack_conversion: Optional[str] = None
    raw_text: str = ""


@dataclass
class Amendment:
    id: str
    category: str
    effective_date: str
    field_changed: str
    new_value: float
    raw_text: str = ""


@dataclass
class SupplierRule:
    name: str
    slug: str
    status: str  # APPROVED, PROBATION, BLACKLISTED
    contract_rates: Dict[str, float] = field(default_factory=dict)
    price_caps: Dict[str, float] = field(default_factory=dict)
    notes: str = ""
    raw_text: str = ""


@dataclass
class Precedent:
    id: str
    category: str
    description: str
    raw_text: str = ""


@dataclass
class Playbook:
    categories: Dict[str, CategoryRule]
    amendments: List[Amendment]
    suppliers: Dict[str, SupplierRule]
    policies: Dict[str, str]
    precedents: Dict[str, Precedent]


def find_playbook_dir(custom_path: Optional[Path] = None) -> Path:
    """Find the playbook directory robustly."""
    candidates = [
        custom_path,
        Path('playbook'),
        Path(__file__).resolve().parent.parent / 'playbook',
        Path.cwd() / 'playbook',
    ]
    for c in candidates:
        if c and Path(c).exists() and Path(c).is_dir():
            # Check if nested inside another playbook dir
            if (Path(c) / 'playbook').exists() and (Path(c) / 'playbook').is_dir():
                return Path(c) / 'playbook'
            return Path(c)
    raise FileNotFoundError("Could not find playbook directory.")


def normalize_slug(s: str) -> str:
    """Normalize names like 'Courier services' or 'courier' to 'courier'."""
    s = s.strip().lower()
    s = re.sub(r'[^a-z0-9]+', '-', s).strip('-')
    aliases = {
        'courier-services': 'courier',
        'cleaning-services': 'cleaning',
        'training-workshops': 'training',
    }
    return aliases.get(s, s)


def load_playbook(playbook_dir: Optional[Path] = None) -> Playbook:
    """Load and parse all playbook documents."""
    root = find_playbook_dir(playbook_dir)

    # 1. Policies
    policies = {}
    policies_dir = root / 'policies'
    if policies_dir.exists():
        for p in policies_dir.glob('*.md'):
            policies[p.stem] = p.read_text(encoding='utf-8')

    # 2. Categories
    categories = {}
    cat_dir = root / 'categories'
    if cat_dir.exists():
        for p in cat_dir.glob('*.md'):
            text = p.read_text(encoding='utf-8')
            m_title = re.search(r'# Category:\s*(.*)', text)
            cat_name = m_title.group(1).strip() if m_title else p.stem
            slug = normalize_slug(cat_name)

            unit = re.search(r'Normalized unit:\*\*\s*(.*)', text).group(1).strip()
            gst = float(re.search(r'GST rate:\*\*\s*(\d+)%', text).group(1)) / 100.0
            target = float(re.search(r'Target price:\*\*\s*[₹Rs\.]*([\d,]+)', text).group(1).replace(',', ''))
            walkaway = float(re.search(r'Walk-away price:\*\*\s*[₹Rs\.]*([\d,]+)', text).group(1).replace(',', ''))
            rounds = int(re.search(r'Negotiation rounds \(R\):\*\*\s*(\d+)', text).group(1))
            beta = float(re.search(r'Concession exponent \(β\):\*\*\s*([\d\.]+)', text).group(1))
            limit = float(re.search(r'Approval limit:\*\*\s*[₹Rs\.]*([\d,]+)', text).group(1).replace(',', ''))

            pack_conv = None
            m_pack = re.search(r'Pack conversion:\*\*\s*(.*)', text)
            if m_pack:
                pack_conv = m_pack.group(1).strip()

            categories[slug] = CategoryRule(
                slug=slug,
                name=cat_name,
                normalized_unit=unit,
                gst_rate=gst,
                target_price=target,
                walkaway_price=walkaway,
                total_rounds=rounds,
                concession_exponent=beta,
                approval_limit=limit,
                pack_conversion=pack_conv,
                raw_text=text
            )

    # 3. Amendments
    amendments = []
    amd_dir = root / 'amendments'
    if amd_dir.exists():
        for p in sorted(amd_dir.glob('*.md')):
            text = p.read_text(encoding='utf-8')
            amd_id = p.stem
            title = text.split('\n')[0]
            m_cat = re.search(r'AMD-\d+:\s*(.*)', title)
            cat_raw = m_cat.group(1).strip() if m_cat else ""
            cat_slug = normalize_slug(cat_raw)

            eff_date = re.search(r'Effective from:\*\*\s*(\d{4}-\d{2}-\d{2})', text).group(1)
            change_text = re.search(r'Change:\*\*\s*(.*)', text).group(1)

            field_changed = ""
            new_val = 0.0
            if 'walk-away price' in change_text.lower():
                field_changed = 'walkaway_price'
                new_val = float(re.search(r'[₹Rs\.]*([\d,]+)', change_text).group(1).replace(',', ''))
            elif 'target price' in change_text.lower():
                field_changed = 'target_price'
                new_val = float(re.search(r'[₹Rs\.]*([\d,]+)', change_text).group(1).replace(',', ''))
            elif 'approval limit' in change_text.lower():
                field_changed = 'approval_limit'
                new_val = float(re.search(r'[₹Rs\.]*([\d,]+)', change_text).group(1).replace(',', ''))

            amendments.append(Amendment(
                id=amd_id,
                category=cat_slug,
                effective_date=eff_date,
                field_changed=field_changed,
                new_value=new_val,
                raw_text=text
            ))

    # Sort amendments chronologically
    amendments.sort(key=lambda a: (a.effective_date, a.id))

    # 4. Suppliers
    suppliers = {}
    sup_dir = root / 'suppliers'
    if sup_dir.exists():
        for p in sup_dir.glob('*.md'):
            text = p.read_text(encoding='utf-8')
            m_name = re.search(r'# Supplier:\s*(.*)', text)
            sup_name = m_name.group(1).strip() if m_name else p.stem
            status_line = re.search(r'Status:\*\*\s*(.*)', text).group(1).strip()
            if 'BLACKLISTED' in status_line.upper():
                status = 'BLACKLISTED'
            elif 'PROBATION' in status_line.upper():
                status = 'PROBATION'
            else:
                status = 'APPROVED'

            contract_rates = {}
            m_rate = re.findall(r'invoices in ([A-Z]{3}) are converted at [₹Rs\.]*([\d\.]+) per \1', text)
            for curr, rate in m_rate:
                contract_rates[curr.upper()] = float(rate)

            price_caps = {}
            m_cap = re.findall(r'price cap for ([\w\s-]+) of [₹Rs\.]*([\d,]+)', text)
            for cat_c, cap in m_cap:
                c_slug = normalize_slug(cat_c)
                price_caps[c_slug] = float(cap.replace(',', ''))

            m_notes = re.search(r'Notes:\*\*\s*(.*)', text)
            notes = m_notes.group(1).strip() if m_notes else ""

            suppliers[sup_name] = SupplierRule(
                name=sup_name,
                slug=p.stem,
                status=status,
                contract_rates=contract_rates,
                price_caps=price_caps,
                notes=notes,
                raw_text=text
            )

    # 5. Precedents
    precedents = {}
    prec_dir = root / 'precedents'
    if prec_dir.exists():
        for p in sorted(prec_dir.glob('*.md')):
            text = p.read_text(encoding='utf-8')
            prec_id = p.stem
            m_title = re.search(r'# Precedent (P-\d+)\s*—\s*(.*)', text)
            cat_name = m_title.group(2).strip() if m_title else ""
            precedents[prec_id] = Precedent(
                id=prec_id,
                category=cat_name,
                description=text,
                raw_text=text
            )

    return Playbook(
        categories=categories,
        amendments=amendments,
        suppliers=suppliers,
        policies=policies,
        precedents=precedents
    )
