"""Decision engine module for Procurement Desk.

Implements the exact 6-priority decision procedure from decision-procedure.md.
"""

from dataclasses import dataclass, field
import math
from typing import Optional, Dict, Any

from .playbook_loader import Playbook, CategoryRule, SupplierRule
from .offer_parser import extract_and_normalize_offer, extract_latest_message, ParsedOffer
from .security_checker import check_prompt_injection, check_banned_terms


@dataclass
class DecisionResult:
    thread_id: str
    action: str  # ACCEPT, COUNTER, REJECT, ESCALATE
    reason: str  # ACCEPTABLE_PRICE, COUNTER_OFFER, ABOVE_WALKAWAY, etc.
    counter_price: Optional[int] = None
    label: str = ""
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.label:
            if self.action == "COUNTER":
                self.label = f"COUNTER:{self.reason}:{self.counter_price}"
            else:
                self.label = f"{self.action}:{self.reason}:"


def get_effective_category_rule(
    base_category: CategoryRule,
    amendments: list,
    thread_date: str,
    supplier_rule: SupplierRule
) -> Dict[str, Any]:
    """Calculate effective category parameters including dated amendments and contract caps."""
    effective = {
        'slug': base_category.slug,
        'name': base_category.name,
        'normalized_unit': base_category.normalized_unit,
        'gst_rate': base_category.gst_rate,
        'target_price': base_category.target_price,
        'walkaway_price': base_category.walkaway_price,
        'total_rounds': base_category.total_rounds,
        'concession_exponent': base_category.concession_exponent,
        'approval_limit': base_category.approval_limit,
        'applied_amendments': []
    }

    # Apply amendments on or before thread date in chronological order
    for amd in amendments:
        if amd.category == base_category.slug and amd.effective_date <= thread_date:
            effective[amd.field_changed] = amd.new_value
            effective['applied_amendments'].append(amd.id)

    # Supplier contract price cap replaces walk-away price for that category
    cap = supplier_rule.price_caps.get(base_category.slug)
    if cap is not None:
        effective['walkaway_price'] = cap
        effective['supplier_cap_override'] = cap

    return effective


def compute_concession_level(
    target: float,
    walkaway: float,
    current_round: int,
    total_rounds: int,
    beta: float,
    is_probation: bool
) -> float:
    """Compute acceptable concession level L(r) per concession-schedule.md and probation policy."""
    if is_probation:
        # Probation suppliers: no concessions, L equals target in every round
        return target

    if current_round == 1:
        return target
    if current_round >= total_rounds:
        return walkaway

    return target + (walkaway - target) * (((current_round - 1.0) / (total_rounds - 1.0)) ** beta)


def make_decision(thread_row: Any, playbook: Playbook) -> DecisionResult:
    """Process a single negotiation thread and generate a final procurement decision.

    Applies the 6 priority rules in strict order:
    1. Missing Information -> ESCALATE:MISSING_INFO:
    2. Blacklisted Supplier -> REJECT:BLACKLISTED_SUPPLIER:
    3. Prompt Injection -> ESCALATE:PROMPT_INJECTION:
    4. Banned Contract Terms -> ESCALATE:BANNED_TERM:
    5. Price Decision -> REJECT / COUNTER / Proceed to Step 6
    6. Approval Limit -> ESCALATE:OVER_APPROVAL_LIMIT: or ACCEPT:ACCEPTABLE_PRICE:
    """
    tid = str(thread_row['thread_id'])
    thread_date = str(thread_row['date'])
    cat_slug = str(thread_row['category']).strip().lower()
    sup_name = str(thread_row['supplier']).strip()
    quantity = int(thread_row['quantity'])
    current_round = int(thread_row['round'])
    full_message = str(thread_row['supplier_message'])
    latest_message = extract_latest_message(full_message)

    # Lookup category and supplier
    if cat_slug not in playbook.categories:
        raise KeyError(f"Unknown spend category: '{cat_slug}'")
    if sup_name not in playbook.suppliers:
        raise KeyError(f"Unknown supplier: '{sup_name}'")

    category_rule = playbook.categories[cat_slug]
    supplier_rule = playbook.suppliers[sup_name]

    # Calculate date-aware and contract-aware effective category parameters
    effective_cat = get_effective_category_rule(
        category_rule,
        playbook.amendments,
        thread_date,
        supplier_rule
    )

    diagnostics = {
        'thread_id': tid,
        'date': thread_date,
        'category': cat_slug,
        'supplier': sup_name,
        'quantity': quantity,
        'round': current_round,
        'effective_category': effective_cat,
        'supplier_status': supplier_rule.status,
    }

    # Step 1: Missing Information
    parsed_offer: ParsedOffer = extract_and_normalize_offer(thread_row, category_rule, supplier_rule)
    diagnostics['parsed_offer'] = parsed_offer

    if parsed_offer.is_missing_info:
        return DecisionResult(
            thread_id=tid,
            action="ESCALATE",
            reason="MISSING_INFO",
            diagnostics=diagnostics
        )

    # Step 2: Blacklisted Supplier
    if supplier_rule.status == "BLACKLISTED":
        return DecisionResult(
            thread_id=tid,
            action="REJECT",
            reason="BLACKLISTED_SUPPLIER",
            diagnostics=diagnostics
        )

    # Step 3: Prompt Injection
    if check_prompt_injection(full_message):
        return DecisionResult(
            thread_id=tid,
            action="ESCALATE",
            reason="PROMPT_INJECTION",
            diagnostics=diagnostics
        )

    # Step 4: Banned Contract Terms
    if check_banned_terms(latest_message):
        return DecisionResult(
            thread_id=tid,
            action="ESCALATE",
            reason="BANNED_TERM",
            diagnostics=diagnostics
        )

    # Step 5: Price Decision
    normalized_p = parsed_offer.normalized_price
    target_p = effective_cat['target_price']
    walkaway_p = effective_cat['walkaway_price']
    total_r = effective_cat['total_rounds']
    beta = effective_cat['concession_exponent']
    is_probation = (supplier_rule.status == "PROBATION")

    L = compute_concession_level(target_p, walkaway_p, current_round, total_r, beta, is_probation)
    diagnostics['normalized_price'] = normalized_p
    diagnostics['concession_level_L'] = L

    if normalized_p <= L:
        # Step 6: Approval Limit
        total_order_value = normalized_p * quantity
        approval_limit = effective_cat['approval_limit']
        diagnostics['total_order_value'] = total_order_value
        diagnostics['approval_limit'] = approval_limit

        if total_order_value > approval_limit:
            return DecisionResult(
                thread_id=tid,
                action="ESCALATE",
                reason="OVER_APPROVAL_LIMIT",
                diagnostics=diagnostics
            )
        else:
            return DecisionResult(
                thread_id=tid,
                action="ACCEPT",
                reason="ACCEPTABLE_PRICE",
                diagnostics=diagnostics
            )
    else:
        # Offer exceeds concession threshold
        if current_round >= total_r:
            # Final round rejection
            return DecisionResult(
                thread_id=tid,
                action="REJECT",
                reason="ABOVE_WALKAWAY",
                diagnostics=diagnostics
            )
        else:
            # Counteroffer rounded to nearest whole rupee (x.5 up)
            rounded_counter = int(math.floor(L + 0.5))
            return DecisionResult(
                thread_id=tid,
                action="COUNTER",
                reason="COUNTER_OFFER",
                counter_price=rounded_counter,
                diagnostics=diagnostics
            )
