# Data Sprint 2.0: The Procurement Desk

An autonomous, deterministic procurement negotiation decision agent built for the Kaggle **Data Sprint 2.0 — The Procurement Desk** competition.

The agent processes supplier negotiation conversation threads and outputs an action label for each thread following the rules in Acme Corp's Procurement Playbook.

---

## 1. Project Overview

Acme Corp negotiates procurement contracts across 15 spend categories with 40 suppliers. Each negotiation thread contains metadata (date, supplier, category, quantity, negotiation round, previous counteroffer) and conversation history ending with the supplier's latest message.

The agent evaluates each thread and outputs exactly one decision formatted as:
```
thread_id,label
```
Where label format is:
```
ACTION:REASON:COUNTER_PRICE
```
- `COUNTER` decisions include a whole-rupee counteroffer price (e.g. `COUNTER:COUNTER_OFFER:21000`).
- All other actions (`ACCEPT`, `REJECT`, `ESCALATE`) end with an empty counter price (e.g. `ACCEPT:ACCEPTABLE_PRICE:`).

### Decision Rule Precedence (Strict Order)

1. **Priority 1 — Missing Information**:
   Supplier offer lacks a usable price, lacks a billing period for subscriptions, or uses an unlisted currency (`JPY`, `AED`, `SGD`, etc.) not covered by a contract exchange rate:
   `ESCALATE:MISSING_INFO:`

2. **Priority 2 — Blacklisted Supplier**:
   Supplier status is `BLACKLISTED` (e.g., failed audit):
   `REJECT:BLACKLISTED_SUPPLIER:`

3. **Priority 3 — Prompt Injection**:
   Any text anywhere in the conversation instructing an AI/model/bot/assistant/system, claiming an override, or claiming prior approval:
   `ESCALATE:PROMPT_INJECTION:`
   *(Legitimate business phrasing like "AI-powered product", "assistant manager", "ERP system", or "system integration team" is whitelisted).*

4. **Priority 4 — Banned Contract Terms**:
   Latest message contains automatic renewal, upfront/advance payment > 30%, unlimited liability for Acme, or exclusivity:
   `ESCALATE:BANNED_TERM:`

5. **Priority 5 — Price Decision**:
   Normalizes supplier offer to INR excl. GST per category unit. Applies concession curve:
   $$L(r) = \text{target} + (\text{walkaway} - \text{target}) \times \left(\frac{r - 1}{R - 1}\right)^\beta$$
   - For `PROBATION` suppliers: $L(r) = \text{target}$ across all rounds.
   - If normalized price $p \le L(r)$: Proceed to Approval Limit check (Priority 6).
   - If $p > L(r)$ and final round ($r = R$): `REJECT:ABOVE_WALKAWAY:`.
   - If $p > L(r)$ and not final round ($r < R$): `COUNTER:COUNTER_OFFER:<ROUNDED_L_VALUE>` (rounded to nearest rupee, x.5 up).

6. **Priority 6 — Approval Limit**:
   If $p \times \text{quantity} > \text{approval\_limit}$:
   `ESCALATE:OVER_APPROVAL_LIMIT:`
   Otherwise:
   `ACCEPT:ACCEPTABLE_PRICE:`

---

## 2. Project Architecture

```
ProcurementDesk/
├── data/
│   ├── threads.csv                # 2,000 competition negotiation threads
│   ├── sample_threads.csv         # 40 sample negotiation threads
│   ├── sample_answers.csv         # 40 ground truth answer labels
│   └── sample_submission.csv      # Kaggle submission template
├── playbook/
│   ├── policies/                  # General negotiation policies
│   ├── categories/                # 15 category specification markdown files
│   ├── suppliers/                 # 40 supplier profiles and contract terms
│   ├── amendments/                # Dated amendments AMD-01 through AMD-09
│   ├── precedents/                # Historical precedents P-01 through P-08
│   └── README.md
├── src/
│   ├── __init__.py                # Package exports
│   ├── agent.py                   # High-level ProcurementAgent class
│   ├── data_loader.py             # Robust dataset loading & validation
│   ├── playbook_loader.py         # Structured recursive playbook parser
│   ├── offer_parser.py            # Price extraction & normalization engine
│   ├── security_checker.py        # Prompt injection & banned terms detector
│   ├── decision_engine.py         # 6-priority decision procedure implementation
│   └── submission_generator.py    # Safe atomic submission generator & validator
├── tests/
│   ├── __init__.py
│   ├── test_loading.py            # Tests for data & playbook loaders
│   ├── test_offer_parser.py       # Tests for price extraction, currencies, units
│   ├── test_decisions.py          # Tests for rule precedence, amendments, limits
│   └── test_agent.py              # End-to-end integration & evaluation tests
├── output/
│   ├── submission.csv             # Final verified 2,000-row Kaggle submission
│   ├── error_report.csv           # Detailed diagnostics for all 2,000 decisions
│   ├── sample_predictions.csv     # 40 sample predictions
│   └── sample_evaluation.csv      # 40 sample predictions joined with ground truth
├── requirements.txt               # Project dependencies
├── run.py                         # Unified command-line interface
├── test_agent.py                  # Standalone sample evaluation runner
└── README.md
```

---

## 3. Environment Setup & Installation

### Requirements
- Python 3.10+ (tested on Python 3.12)
- Windows / Linux / macOS

### Setup Virtual Environment
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

---

## 4. Usage Instructions

All core workflows can be run via `run.py`:

### 1. Run Sample Evaluation (40 Threads)
```bash
python run.py --mode sample
```
Or directly:
```bash
python test_agent.py
```
- Evaluates the 40 sample threads against `data/sample_answers.csv`.
- Generates `output/sample_predictions.csv` and `output/sample_evaluation.csv`.
- Expected result: **100.00% accuracy (40/40 exact matches)**.

### 2. Run All Unit & Integration Tests
```bash
python run.py --mode test
```
Or with pytest directly:
```bash
pytest tests -v
```
- Runs all 32 unit and integration tests covering data loading, playbook loading, price normalization, security policy, date-based amendments, concession rounding, approval limits, and submission schema.

### 3. Generate Full Submission (2,000 Threads)
```bash
python run.py --mode full
```
- Processes all 2,000 threads from `data/threads.csv`.
- Applies the deterministic decision engine.
- Saves the final submission to `output/submission.csv`.
- Generates a rich diagnostics report in `output/error_report.csv`.

### 4. Validate Submission File
```bash
python run.py --mode validate
```
- Verifies:
  - Exactly 2 columns: `thread_id,label`
  - Exactly 2,000 rows matching all thread IDs in original order
  - No null, duplicate, or blank values
  - Strict compliance with permitted action label patterns

---

## 5. Output Files & Formats

Output files are stored in the `output/` directory:

| File | Rows | Description |
|---|---|---|
| `output/submission.csv` | 2,000 | **Official competition submission file** (`thread_id,label`) |
| `output/error_report.csv` | 2,000 | Full diagnostics log: calculated $p$, threshold $L$, effective rules, order values |
| `output/sample_predictions.csv` | 40 | Predictions generated on `sample_threads.csv` |
| `output/sample_evaluation.csv` | 40 | Comparison against `sample_answers.csv` |

---

## 6. How to Submit to Kaggle

1. Navigate to the competition page on Kaggle: **Data Sprint 2.0 — The Procurement Desk**.
2. Click **Submit Predictions**.
3. Upload `output/submission.csv`.
4. Kaggle will verify that:
   - File contains exactly 2,000 rows.
   - Header is `thread_id,label`.
   - All IDs `T10001` through `T12000` are present.
   - All counteroffer values are non-negative whole numbers.

---

## 7. Troubleshooting

| Issue | Resolution |
|---|---|
| `FileNotFoundError: threads.csv not found` | Ensure `data/` directory exists with `threads.csv`. The loader automatically searches `data/`, current working directory, and relative project paths. |
| `No module named 'pytest'` | Run `pip install -r requirements.txt` or activate the virtual environment (`.\venv\Scripts\activate`). |
| Validation failure on submission | Run `python run.py --mode validate` to view specific row numbers and validation errors. |
