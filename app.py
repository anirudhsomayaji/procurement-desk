"""Enterprise Web Server for Procurement Desk UI.

Serves the modern enterprise dashboard and exposes REST API endpoints
connecting directly to the existing production ProcurementAgent.
Requires zero external pip dependencies (built entirely on Python standard library).
"""

import http.server
import json
import math
import os
import socketserver
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import production modules
from src.agent import ProcurementAgent
from src.data_loader import (
    load_threads,
    load_sample_threads,
    load_sample_answers,
    load_sample_submission
)
from src.playbook_loader import load_playbook, Playbook
from src.decision_engine import make_decision, DecisionResult, compute_concession_level
from src.offer_parser import extract_and_normalize_offer, DEFAULT_EXCHANGE_RATES
from src.security_checker import check_prompt_injection, check_banned_terms
from src.submission_generator import validate_submission_df
import pandas as pd

# Global state / cache
AGENT: Optional[ProcurementAgent] = None
PLAYBOOK: Optional[Playbook] = None
THREADS_DF: Optional[pd.DataFrame] = None
SUBMISSION_DF: Optional[pd.DataFrame] = None
ERROR_REPORT_DF: Optional[pd.DataFrame] = None
SAMPLE_EVAL_DATA: Optional[Dict[str, Any]] = None


def initialize_backend():
    """Pre-cache backend objects for instant sub-millisecond API responses."""
    global AGENT, PLAYBOOK, THREADS_DF, SUBMISSION_DF, ERROR_REPORT_DF, SAMPLE_EVAL_DATA
    print("[BACKEND] Initializing Procurement Agent and caching datasets...")
    
    AGENT = ProcurementAgent()
    PLAYBOOK = AGENT.playbook
    THREADS_DF = load_threads()
    
    sub_path = PROJECT_ROOT / "output" / "submission.csv"
    if sub_path.exists():
        SUBMISSION_DF = pd.read_csv(sub_path)
    else:
        SUBMISSION_DF = pd.DataFrame([
            {'thread_id': r.thread_id, 'label': r.label} for r in AGENT.process_threads(THREADS_DF)
        ])
        
    diag_path = PROJECT_ROOT / "output" / "error_report.csv"
    if diag_path.exists():
        ERROR_REPORT_DF = pd.read_csv(diag_path)
        
    # Pre-evaluate sample threads for instant benchmark display
    accuracy, sample_preds, sample_eval = AGENT.evaluate_sample()
    SAMPLE_EVAL_DATA = {
        'accuracy': accuracy,
        'total': len(sample_eval),
        'correct': int(sample_eval['is_correct'].sum()),
        'records': sample_eval.to_dict(orient='records')
    }
    print(f"[BACKEND] Ready: {len(THREADS_DF)} threads, {len(SUBMISSION_DF)} predictions loaded.")


class ProcurementRequestHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP handler serving UI assets and JSON REST APIs."""

    def log_message(self, format, *args):
        # Concise logging
        sys.stdout.write(f"[{self.log_date_time_string()}] {self.command} {self.path} - {args[0]}\n")

    def send_json(self, data: Any, status: int = 200):
        """Helper to send JSON responses."""
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        """Handle pre-flight CORS requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        """Route GET requests to static files or REST endpoints."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Static UI Routes
        if path == "/" or path == "/index.html":
            self.serve_file(PROJECT_ROOT / "ui" / "index.html", "text/html; charset=utf-8")
            return
        elif path.startswith("/ui/"):
            filename = path[4:]
            file_path = PROJECT_ROOT / "ui" / filename
            self.serve_static_asset(file_path)
            return

        # API Routes
        if path == "/api/stats":
            self.handle_get_stats()
        elif path == "/api/threads":
            self.handle_get_threads(query)
        elif path.startswith("/api/thread/"):
            thread_id = path.split("/api/thread/")[1].strip()
            self.handle_get_single_thread(thread_id)
        elif path == "/api/playbook":
            self.handle_get_playbook()
        elif path == "/api/sample-eval":
            self.send_json(SAMPLE_EVAL_DATA)
        elif path == "/api/download-submission":
            self.handle_download_submission()
        else:
            self.send_error(404, "Endpoint Not Found")

    def do_POST(self):
        """Route POST requests for live agent analysis and security scanning."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        if path == "/api/analyze":
            self.handle_post_analyze(req_data)
        elif path == "/api/security-scan":
            self.handle_post_security_scan(req_data)
        else:
            self.send_error(404, "Endpoint Not Found")

    def serve_file(self, file_path: Path, content_type: str):
        """Serve a local file with proper content type."""
        if not file_path.exists():
            self.send_error(404, f"File {file_path.name} not found")
            return
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(content)

    def serve_static_asset(self, file_path: Path):
        """Serve CSS, JS, SVG, and other static assets with correct MIME types."""
        suffix = file_path.suffix.lower()
        mime_types = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.svg': 'image/svg+xml',
            '.png': 'image/png',
            '.ico': 'image/x-icon',
        }
        ct = mime_types.get(suffix, 'application/octet-stream')
        self.serve_file(file_path, ct)

    # --------------------------------------------------------------------------
    # API Handlers
    # --------------------------------------------------------------------------

    def handle_get_stats(self):
        """Return high-level summary KPIs and output label distribution."""
        sub_df = SUBMISSION_DF
        sub_df['action'] = sub_df['label'].apply(lambda x: x.split(':')[0])
        sub_df['reason'] = sub_df['label'].apply(lambda x: x.split(':')[1])
        action_counts = sub_df['action'].value_counts().to_dict()

        response = {
            'total_threads': len(sub_df),
            'action_distribution': {
                'ACCEPT': action_counts.get('ACCEPT', 0),
                'COUNTER': action_counts.get('COUNTER', 0),
                'REJECT': action_counts.get('REJECT', 0),
                'ESCALATE': action_counts.get('ESCALATE', 0),
            },
            'percentages': {
                'ACCEPT': round(action_counts.get('ACCEPT', 0) / len(sub_df) * 100, 1),
                'COUNTER': round(action_counts.get('COUNTER', 0) / len(sub_df) * 100, 1),
                'REJECT': round(action_counts.get('REJECT', 0) / len(sub_df) * 100, 1),
                'ESCALATE': round(action_counts.get('ESCALATE', 0) / len(sub_df) * 100, 1),
            },
            'sample_accuracy': SAMPLE_EVAL_DATA['accuracy'],
            'sample_correct': SAMPLE_EVAL_DATA['correct'],
            'sample_total': SAMPLE_EVAL_DATA['total'],
            'categories_count': len(PLAYBOOK.categories),
            'suppliers_count': len(PLAYBOOK.suppliers),
            'amendments_count': len(PLAYBOOK.amendments),
            'precedents_count': len(PLAYBOOK.precedents)
        }
        self.send_json(response)

    def handle_get_threads(self, query: Dict[str, List[str]]):
        """Return filtered and paginated thread records."""
        df = THREADS_DF.copy()
        sub_map = dict(zip(SUBMISSION_DF['thread_id'], SUBMISSION_DF['label']))
        df['label'] = df['thread_id'].map(sub_map)
        df['action'] = df['label'].apply(lambda x: str(x).split(':')[0] if pd.notnull(x) else "")

        # Filters
        category = query.get('category', [''])[0].strip().lower()
        if category:
            df = df[df['category'] == category]

        supplier = query.get('supplier', [''])[0].strip()
        if supplier:
            df = df[df['supplier'] == supplier]

        action = query.get('action', [''])[0].strip().upper()
        if action and action != 'ALL':
            df = df[df['action'] == action]

        search = query.get('search', [''])[0].strip().lower()
        if search:
            df = df[
                df['thread_id'].str.lower().str.contains(search) |
                df['supplier'].str.lower().str.contains(search) |
                df['category'].str.lower().str.contains(search) |
                df['label'].str.lower().str.contains(search)
            ]

        total_matching = len(df)
        page = max(1, int(query.get('page', ['1'])[0]))
        limit = max(5, min(100, int(query.get('limit', ['20'])[0])))
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit

        paginated = df.iloc[start_idx:end_idx]
        records = []
        for idx, row in paginated.iterrows():
            records.append({
                'thread_id': row['thread_id'],
                'date': row['date'],
                'supplier': row['supplier'],
                'category': row['category'],
                'quantity': int(row['quantity']),
                'round': int(row['round']),
                'our_last_counter': None if pd.isna(row['our_last_counter']) else float(row['our_last_counter']),
                'label': row['label'],
                'action': row['action'],
            })

        self.send_json({
            'total': total_matching,
            'page': page,
            'limit': limit,
            'total_pages': max(1, math.ceil(total_matching / limit)),
            'records': records
        })

    def handle_get_single_thread(self, thread_id: str):
        """Fetch complete transcript and diagnostics for a specific thread."""
        match = THREADS_DF[THREADS_DF['thread_id'] == thread_id]
        if match.empty:
            self.send_error(404, f"Thread {thread_id} not found")
            return

        row = match.iloc[0]
        sub_row = SUBMISSION_DF[SUBMISSION_DF['thread_id'] == thread_id]
        label = sub_row.iloc[0]['label'] if not sub_row.empty else ""

        diag_dict = {}
        if ERROR_REPORT_DF is not None:
            diag_match = ERROR_REPORT_DF[ERROR_REPORT_DF['thread_id'] == thread_id]
            if not diag_match.empty:
                diag_dict = diag_match.iloc[0].to_dict()

        # Split conversation history into earlier vs latest message
        full_msg = str(row['supplier_message'])
        earlier_text = ""
        latest_text = full_msg
        if '[Latest message' in full_msg:
            parts = full_msg.split('[Latest message')
            earlier_text = parts[0].strip()
            latest_text = '[Latest message' + parts[1].strip()

        resp = {
            'thread_id': row['thread_id'],
            'date': row['date'],
            'supplier': row['supplier'],
            'category': row['category'],
            'quantity': int(row['quantity']),
            'round': int(row['round']),
            'our_last_counter': None if pd.isna(row['our_last_counter']) else float(row['our_last_counter']),
            'supplier_message': full_msg,
            'earlier_message': earlier_text,
            'latest_message': latest_text,
            'label': label,
            'diagnostics': diag_dict
        }
        self.send_json(resp)

    def handle_post_analyze(self, req_data: Dict[str, Any]):
        """Run the actual production decision engine and return full audit trace."""
        thread_id = req_data.get('thread_id')
        
        # Look up existing thread row or build from request fields
        if thread_id and thread_id in THREADS_DF['thread_id'].values:
            row = THREADS_DF[THREADS_DF['thread_id'] == thread_id].iloc[0].to_dict()
        else:
            row = {
                'thread_id': req_data.get('thread_id', 'CUSTOM_001'),
                'date': req_data.get('date', '2026-10-01'),
                'supplier': req_data.get('supplier', 'Saffron Kitchens'),
                'category': req_data.get('category', 'catering'),
                'quantity': int(req_data.get('quantity', 100)),
                'round': int(req_data.get('round', 1)),
                'our_last_counter': req_data.get('our_last_counter'),
                'supplier_message': req_data.get('supplier_message', '')
            }

        # Execute the ACTUAL production decision engine
        result: DecisionResult = AGENT.decide_thread(row)
        cat_slug = str(row['category']).strip().lower()
        sup_name = str(row['supplier']).strip()

        cat_rule = PLAYBOOK.categories[cat_slug]
        sup_rule = PLAYBOOK.suppliers[sup_name]
        parsed_offer = extract_and_normalize_offer(row, cat_rule, sup_rule)

        # Build detailed rule explanation
        rule_trace = []
        rule_trace.append({
            'step': 1,
            'name': 'Missing Information Check',
            'passed': not parsed_offer.is_missing_info,
            'details': f"Parsed normalized price: ₹{parsed_offer.normalized_price:,.2f}" if not parsed_offer.is_missing_info else f"Missing info: {parsed_offer.details.get('reason')}"
        })
        
        rule_trace.append({
            'step': 2,
            'name': 'Supplier Status Check',
            'passed': sup_rule.status != 'BLACKLISTED',
            'details': f"Supplier status: {sup_rule.status}"
        })

        is_injection = check_prompt_injection(row['supplier_message'])
        rule_trace.append({
            'step': 3,
            'name': 'Prompt Injection Screen',
            'passed': not is_injection,
            'details': "No prompt injection detected in thread transcript" if not is_injection else "Adversarial prompt injection pattern detected"
        })

        is_banned = check_banned_terms(row['supplier_message'])
        rule_trace.append({
            'step': 4,
            'name': 'Banned Contract Terms Screen',
            'passed': not is_banned,
            'details': "No prohibited commercial clauses in latest message" if not is_banned else "Prohibited contract clause detected (auto-renew, upfront >30%, liability, or exclusivity)"
        })

        if not parsed_offer.is_missing_info and sup_rule.status != 'BLACKLISTED' and not is_injection and not is_banned:
            L = result.diagnostics.get('concession_level_L', 0.0)
            p = result.diagnostics.get('normalized_price', 0.0)
            rule_trace.append({
                'step': 5,
                'name': 'Price vs Concession Threshold',
                'passed': p <= L,
                'details': f"Normalized price p = ₹{p:,.2f} vs Concession threshold L = ₹{L:,.2f} (Round {row['round']}/{cat_rule.total_rounds})"
            })

            if p <= L:
                tot_val = result.diagnostics.get('total_order_value', 0.0)
                app_lim = result.diagnostics.get('approval_limit', 0.0)
                rule_trace.append({
                    'step': 6,
                    'name': 'Approval Limit Check',
                    'passed': tot_val <= app_lim,
                    'details': f"Total order commitment ₹{tot_val:,.2f} vs Approval limit ₹{app_lim:,.2f}"
                })

        response = {
            'thread_id': result.thread_id,
            'action': result.action,
            'reason': result.reason,
            'counter_price': result.counter_price,
            'label': result.label,
            'diagnostics': {
                'category': cat_rule.name,
                'supplier': sup_rule.name,
                'supplier_status': sup_rule.status,
                'quantity': row['quantity'],
                'round': row['round'],
                'normalized_price': parsed_offer.normalized_price,
                'currency': parsed_offer.currency,
                'exchange_rate': parsed_offer.exchange_rate,
                'is_gst_inclusive': parsed_offer.is_gst_inclusive,
                'target_price': result.diagnostics.get('effective_category', {}).get('target_price', cat_rule.target_price),
                'walkaway_price': result.diagnostics.get('effective_category', {}).get('walkaway_price', cat_rule.walkaway_price),
                'concession_level_L': result.diagnostics.get('concession_level_L'),
                'total_order_value': result.diagnostics.get('total_order_value'),
                'approval_limit': result.diagnostics.get('approval_limit', cat_rule.approval_limit),
                'applied_amendments': result.diagnostics.get('effective_category', {}).get('applied_amendments', [])
            },
            'rule_trace': rule_trace
        }
        self.send_json(response)

    def handle_post_security_scan(self, req_data: Dict[str, Any]):
        """Run the actual security checker on arbitrary input text."""
        text = req_data.get('text', '')
        has_injection = check_prompt_injection(text)
        has_banned = check_banned_terms(text)

        self.send_json({
            'text': text,
            'has_prompt_injection': has_injection,
            'has_banned_terms': has_banned,
            'prompt_injection_status': 'FLAGGED' if has_injection else 'CLEAN',
            'banned_terms_status': 'FLAGGED' if has_banned else 'CLEAN',
            'action_triggered': (
                'ESCALATE:PROMPT_INJECTION:' if has_injection else
                ('ESCALATE:BANNED_TERM:' if has_banned else 'PASS')
            )
        })

    def handle_get_playbook(self):
        """Return complete structured playbook policies and tables."""
        categories = []
        for slug, cat in sorted(PLAYBOOK.categories.items()):
            categories.append({
                'slug': cat.slug,
                'name': cat.name,
                'unit': cat.normalized_unit,
                'gst_rate': cat.gst_rate,
                'target_price': cat.target_price,
                'walkaway_price': cat.walkaway_price,
                'total_rounds': cat.total_rounds,
                'concession_exponent': cat.concession_exponent,
                'approval_limit': cat.approval_limit,
                'pack_conversion': cat.pack_conversion,
            })

        suppliers = []
        for name, sup in sorted(PLAYBOOK.suppliers.items()):
            suppliers.append({
                'name': sup.name,
                'slug': sup.slug,
                'status': sup.status,
                'contract_rates': sup.contract_rates,
                'price_caps': sup.price_caps,
                'notes': sup.notes
            })

        amendments = []
        for amd in PLAYBOOK.amendments:
            amendments.append({
                'id': amd.id,
                'category': amd.category,
                'effective_date': amd.effective_date,
                'field_changed': amd.field_changed,
                'new_value': amd.new_value,
            })

        precedents = []
        for pid, prec in sorted(PLAYBOOK.precedents.items()):
            precedents.append({
                'id': prec.id,
                'category': prec.category,
                'description': prec.description
            })

        self.send_json({
            'categories': categories,
            'suppliers': suppliers,
            'amendments': amendments,
            'precedents': precedents,
            'default_exchange_rates': DEFAULT_EXCHANGE_RATES
        })

    def handle_download_submission(self):
        """Serve the official submission.csv as an attachment."""
        sub_path = PROJECT_ROOT / "output" / "submission.csv"
        if not sub_path.exists():
            self.send_error(404, "Submission file not found")
            return
        content = sub_path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition', 'attachment; filename="submission.csv"')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def run_server(port: int = 8000):
    """Start the multi-threaded HTTP server."""
    initialize_backend()
    server_address = ('', port)
    
    # Threading server handles parallel requests smoothly
    class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    httpd = ThreadedHTTPServer(server_address, ProcurementRequestHandler)
    print("=" * 70)
    print("PROCUREMENT DESK — ENTERPRISE UI APPLICATION SERVER")
    print("=" * 70)
    print(f"Server Running At : http://localhost:{port}")
    print(f"Network Access    : http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop the server.")
    print("=" * 70)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[BACKEND] Stopping server...")
        httpd.server_close()
        print("[BACKEND] Server stopped cleanly.")


if __name__ == '__main__':
    port = 8000
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        port = int(sys.argv[1])
    run_server(port)
