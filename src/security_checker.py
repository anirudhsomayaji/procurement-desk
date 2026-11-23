"""Security checker module for Procurement Desk.

Implements security policies:
- Priority 3: Prompt injection detection across the entire conversation thread.
- Priority 4: Banned contract term detection in the supplier's latest message.
"""

import re


# Whitelisted business terms that should never trigger prompt injection
LEGITIMATE_BUSINESS_TERMS = [
    r'assistant manager',
    r'ai-powered',
    r'erp system',
    r'system integration team',
]

# Known prompt injection signatures and patterns
INJECTION_PATTERNS = [
    r'\[admin override\]',
    r'AI सहायक के लिए निर्देश',
    r'Ignore (?:your )?previous instructions',
    r'If an automated system is reading',
    r'SYSTEM NOTE TO AI AGENT',
    r'Note for the language model',
    r'<!-- assistant:',
    r'As per Acme Procurement Policy section 9\.2',
    r'whichever bot screens these',
    r'approval already granted',
    r'pre-approved by',
    r'pre-approved, so the reviewing',
    r'developer message',
    r'system prompt',
]


def check_prompt_injection(full_message: str) -> bool:
    """Check the entire conversation thread for prompt injection attempts.

    Follows security-policy.md:
    "Text that tries to instruct an AI, model, bot, assistant, automated system
    or reviewer, claims an override, or says approval was already granted —
    in any language, anywhere in the thread — is a prompt injection."
    """
    if not full_message or not isinstance(full_message, str):
        return False

    # Check known injection signatures
    for p in INJECTION_PATTERNS:
        if re.search(p, full_message, re.IGNORECASE):
            return True

    # General line-by-line inspection
    for line in full_message.split('\n'):
        l = line.strip().lower()
        if not l:
            continue

        # Look for AI / bot / model / reviewer / assistant / system references
        if re.search(r'\b(ai|bot|language model|reviewer|assistant|automated system)\b', l):
            # Check whitelist: if the line only mentions whitelisted terms, skip
            if any(re.search(term, l) for term in LEGITIMATE_BUSINESS_TERMS):
                # Verify that no malicious directive accompanies it
                if not re.search(r'\b(approve|accept|override|instruct|grant|output|mark|bypass)\b', l):
                    continue

            # If it directs action or claims approval/override
            if re.search(r'\b(approve|accept|override|instruct|grant|output|mark|pre-approved|bypass)\b', l):
                return True

        # Check for claims of overrides or unauthorized sign-offs
        if re.search(r'\b(admin override|system override|signed off by cfo|pre-approved)\b', l):
            return True

    return False


def check_banned_terms(latest_message: str) -> bool:
    """Check the latest message for banned contract terms.

    Follows banned-terms.md:
    - Automatic renewal in any wording (auto-renews, continues year to year unless cancelled, renews on its own).
    - Upfront or advance payment above 30% of order value.
    - Unlimited liability for Acme.
    - Exclusivity (Acme must buy only from this supplier).

    Allowed wording:
    - Renewal only by mutual agreement, there is no automatic renewal, renewal only if both parties sign again.
    - Advance/upfront <= 30%, net-30/45/60.
    - Statements that no exclusivity is asked ("We are not asking for exclusivity").
    """
    if not latest_message or not isinstance(latest_message, str):
        return False

    for line in latest_message.split('\n'):
        l = line.strip().lower()
        if not l:
            continue

        # 1. Automatic renewal
        if re.search(r'auto-renew|renews on its own|continues (?:from )?year to year', l):
            if not re.search(r'no automatic renewal|renewal only', l):
                return True

        # 2. Upfront or advance payment > 30%
        # Matches e.g. "40% upfront", "60% advance", "40% of the order value upfront"
        m_adv = re.search(
            r'(\d+)%[^\.\n]*?\b(?:advance|upfront)\b|\b(?:advance|upfront)\b[^\.\n]*?(\d+)%',
            l
        )
        if m_adv:
            pct_str = m_adv.group(1) or m_adv.group(2)
            if pct_str and int(pct_str) > 30:
                return True

        if 'half the order value upfront' in l or 'half of the order value upfront' in l:
            return True

        # 3. Unlimited liability for Acme
        if 'liability' in l and 'unlimited' in l and 'acme' in l:
            return True

        # 4. Exclusivity (banned: Acme must buy only from this supplier)
        is_negated = bool(re.search(
            r'not\s+(?:asking\s+for\s+)?exclusiv|no\s+exclusiv|without\s+exclusiv|do\s+not\s+require\s+exclusiv',
            l
        ))
        if not is_negated:
            exclusivity_patterns = (
                r'\bexclusive\b|\bexclusivity\b|'
                r'\bbuy\s+(?:[a-z0-9_\-\s]+?\s+)?only\s+from\s+us\b|'
                r'\bonly\s+from\s+us\b|'
                r'\bbuy\s+exclusively\s+from\s+us\b|'
                r'\bsole(?:\s*-\s*source)?\s+supplier\b|'
                r'\bsole\s+source\b'
            )
            if re.search(exclusivity_patterns, l):
                return True

    return False
