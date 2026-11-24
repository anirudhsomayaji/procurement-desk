/**
 * Procurement Desk — Enterprise Frontend Controller
 * Acme Corporation &bull; Enterprise Procurement Intelligence
 */

const App = {
  state: {
    currentView: 'overview',
    stats: null,
    playbook: null,
    currentThreadId: 'T10010',
    currentThreadData: null,
    isPresentationMode: false,
    analyticsPage: 1,
    analyticsLimit: 20,
    analyticsAction: 'ALL',
    analyticsSearch: '',
    concessionSim: {
      target: 280,
      walkaway: 340,
      rounds: 3,
      r: 2,
      beta: 1.0
    }
  },

  modulesCatalog: {
    agent: {
      title: "ProcurementAgent Coordinator",
      file: "src/agent.py",
      badge: "ORCHESTRATOR",
      resp: "Central orchestration façade coordinating the complete lifecycle: dataset ingestion, structured playbook rule matching, thread evaluation, sample benchmarking, and batch submission generation.",
      inputs: "threads_df: pd.DataFrame or single thread row dict;\nplaybook_dir: Optional[Path]",
      proc: "Instantiates Playbook; iterates through negotiation threads; delegates each thread to make_decision(); aggregates results; benchmarks sample accuracy; writes validated submission.csv.",
      outputs: "Tuple[float, pd.DataFrame, pd.DataFrame] (accuracy, predictions, evaluation)\nor Path (to output/submission.csv)"
    },
    data_loader: {
      title: "Data Loader & Validator",
      file: "src/data_loader.py",
      badge: "INGESTION",
      resp: "Robust file loader enforcing schema integrity, checking required columns, detecting null values, and preventing duplicate thread IDs across 2,000 negotiation records.",
      inputs: "data_path: Optional[Path] pointing to threads.csv or sample_threads.csv",
      proc: "Validates presence of 8 mandatory columns; verifies thread_id uniqueness; enforces non-null constraints; checks expected row counts (2000 or 40).",
      outputs: "pd.DataFrame with validated dtypes and complete thread records"
    },
    playbook_loader: {
      title: "Structured Playbook Loader",
      file: "src/playbook_loader.py",
      badge: "KNOWLEDGE BASE",
      resp: "Parses corporate procurement policies, 15 spend category definitions, 40 supplier profiles, 9 dated amendments (AMD-01..09), and 8 historical case precedents (P-01..08).",
      inputs: "playbook_dir: Optional[Path] pointing to playbook/ root directory",
      proc: "Parses markdown files via structured regex; constructs strongly-typed dataclasses (CategoryRule, SupplierRule, Amendment); chains dated amendments chronologically by effective date.",
      outputs: "Playbook dataclass containing categories, amendments, suppliers, policies, precedents"
    },
    offer_parser: {
      title: "Offer Parser & Normalization Engine",
      file: "src/offer_parser.py",
      badge: "PARSING",
      resp: "Extracts supplier commercial quotations and normalizes them into INR excl. GST per normalized unit, applying FX conversion, GST de-compounding, batch divisors, and precedents.",
      inputs: "thread_row: Dict, category_rule: CategoryRule, supplier_rule: SupplierRule",
      proc: "Regex pattern matching (A..H) for range quotes (P-01), free items (P-02), list discounts, word numerals, lakhs/k; converts currencies (USD, EUR, GBP) using contract overrides; strips GST; normalizes packs, dozens, and reams.",
      outputs: "ParsedOffer dataclass (normalized_price: float, is_missing_info: bool, details: Dict)"
    },
    security_checker: {
      title: "Security & Risk Defense Checker",
      file: "src/security_checker.py",
      badge: "DEFENSE",
      resp: "Dual-tier security screening: scans entire thread history for adversarial prompt injections, and screens latest supplier messages for prohibited contractual clauses.",
      inputs: "full_message: str (entire transcript);\nlatest_message: str (supplier's latest email)",
      proc: "Checks injection signatures ([admin override], multilingual Hindi, directive overrides) with business whitelisting ('assistant manager', 'ERP system'); detects 4 banned clauses (auto-renewal, upfront >30%, unlimited liability, exclusivity).",
      outputs: "bool (True if risk detected, False if clean)"
    },
    decision_engine: {
      title: "Decision Engine Core",
      file: "src/decision_engine.py",
      badge: "DECISION CORE",
      resp: "Encapsulates the immutable 6-priority decision procedure: evaluates missing information, blacklist status, security flags, concession curves L(r), and financial approval limits.",
      inputs: "thread_row: Dict, playbook: Playbook",
      proc: "Applies 6 priorities in strict sequence: 1. Missing Info -> 2. Blacklisted -> 3. Injection -> 4. Banned Terms -> 5. Price vs L(r) -> 6. Approval Limit. Computes non-linear concession threshold L(r).",
      outputs: "DecisionResult dataclass (action, reason, counter_price, label, diagnostics)"
    },
    submission_generator: {
      title: "Submission Generator & Validator",
      file: "src/submission_generator.py",
      badge: "OUTPUT",
      resp: "Guarantees safe, atomic output generation and strictly validates Kaggle competition compliance before replacing output/submission.csv.",
      inputs: "results: List[DecisionResult], output_path: Path, expected_count: 2000",
      proc: "Validates 2 columns (thread_id, label), 2,000 row count, 0 nulls/duplicates, regex label syntax; writes to temp file; performs re-read verification before atomic file rename; saves diagnostic log.",
      outputs: "Path to verified, compliant output/submission.csv"
    }
  },

  async init() {
    console.log("[APP] Initializing Procurement Desk UI...");
    this.bindEvents();
    this.initConcessionCanvas();

    try {
      await Promise.all([
        this.fetchStats(),
        this.fetchPlaybook(),
        this.fetchThreadsForSelect(),
        this.fetchAnalyticsTable()
      ]);
      // Load default demo thread
      await this.loadThreadDetails(this.state.currentThreadId);
    } catch (err) {
      console.error("[APP] Initialization error:", err);
    }
  },

  bindEvents() {
    // Navigation items
    document.querySelectorAll('.sidebar-menu .nav-item').forEach(btn => {
      btn.addEventListener('click', () => {
        const view = btn.dataset.view;
        this.navigateTo(view);
      });
    });

    // Presentation mode button & shortcut
    const presBtn = document.getElementById('btn-presentation-mode');
    if (presBtn) {
      presBtn.addEventListener('click', () => this.togglePresentationMode());
    }

    document.addEventListener('keydown', (e) => {
      if ((e.key === 'p' || e.key === 'P') && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
        this.togglePresentationMode();
      }
      if (e.key === 'Escape' && this.state.isPresentationMode) {
        this.togglePresentationMode(false);
      }
      if (e.key === '/' && !['INPUT', 'TEXTAREA'].includes(e.target.tagName)) {
        e.preventDefault();
        const searchInput = document.getElementById('global-search');
        if (searchInput) searchInput.focus();
      }
    });

    // Global search
    const globalSearch = document.getElementById('global-search');
    if (globalSearch) {
      globalSearch.addEventListener('input', (e) => {
        const val = e.target.value.trim().toUpperCase();
        if (val.startsWith('T1') && val.length === 6) {
          this.navigateTo('workspace');
          this.loadDemoScenario(val);
        }
      });
    }

    // Analytics table filters
    const filterContainer = document.getElementById('action-filters');
    if (filterContainer) {
      filterContainer.addEventListener('click', (e) => {
        const btn = e.target.closest('.pill-filter');
        if (btn) {
          filterContainer.querySelectorAll('.pill-filter').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          this.state.analyticsAction = btn.dataset.action;
          this.state.analyticsPage = 1;
          this.fetchAnalyticsTable();
        }
      });
    }

    // Analytics search input
    const analyticsSearch = document.getElementById('analytics-search-input');
    if (analyticsSearch) {
      analyticsSearch.addEventListener('input', (e) => {
        this.state.analyticsSearch = e.target.value.trim();
        this.state.analyticsPage = 1;
        this.fetchAnalyticsTable();
      });
    }
  },

  navigateTo(viewId) {
    this.state.currentView = viewId;

    // Update sidebar buttons
    document.querySelectorAll('.sidebar-menu .nav-item').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === viewId);
    });

    // Update panels
    document.querySelectorAll('.view-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `view-${viewId}`);
    });

    // Scroll to top
    const main = document.querySelector('.main-content');
    if (main) main.scrollTop = 0;

    // Redraw charts if needed
    if (viewId === 'overview' && this.state.stats) {
      this.renderDonutChart(this.state.stats.action_distribution);
    } else if (viewId === 'engine') {
      this.updateConcessionSim();
    }
  },

  togglePresentationMode(force) {
    const nextState = typeof force === 'boolean' ? force : !this.state.isPresentationMode;
    this.state.isPresentationMode = nextState;
    document.body.classList.toggle('presentation-mode', nextState);

    const btn = document.getElementById('btn-presentation-mode');
    if (btn) {
      btn.querySelector('span:nth-child(2)').textContent = nextState ? 'Exit Presentation' : 'Presentation Mode';
    }
  },

  // ==========================================================================
  // API CALLS
  // ==========================================================================

  async fetchStats() {
    const res = await fetch('/api/stats');
    const data = await res.json();
    this.state.stats = data;

    // Populate Overview KPIs
    const elTotal = document.getElementById('kpi-total-threads');
    if (elTotal) elTotal.textContent = data.total_threads.toLocaleString();

    const dist = data.action_distribution;
    const pcts = data.percentages;

    const elAccept = document.getElementById('kpi-accept-count');
    if (elAccept) elAccept.textContent = dist.ACCEPT.toLocaleString();

    const elCounter = document.getElementById('kpi-counter-count');
    if (elCounter) elCounter.textContent = dist.COUNTER.toLocaleString();

    const elReject = document.getElementById('kpi-reject-count');
    if (elReject) elReject.textContent = dist.REJECT.toLocaleString();

    const elEscalate = document.getElementById('kpi-escalate-count');
    if (elEscalate) elEscalate.textContent = dist.ESCALATE.toLocaleString();

    this.renderDonutChart(dist);
    this.populateOverviewRecentTable();
  },

  renderDonutChart(dist) {
    const total = (dist.ACCEPT || 0) + (dist.COUNTER || 0) + (dist.REJECT || 0) + (dist.ESCALATE || 0) || 2000;
    const svg = document.getElementById('overview-donut');
    const legend = document.getElementById('donut-legend');
    if (!svg || !legend) return;

    svg.innerHTML = '';
    legend.innerHTML = '';

    const actions = [
      { name: 'ACCEPT', count: dist.ACCEPT, color: '#10B981' },
      { name: 'COUNTER', count: dist.COUNTER, color: '#3B82F6' },
      { name: 'REJECT', count: dist.REJECT, color: '#EF4444' },
      { name: 'ESCALATE', count: dist.ESCALATE, color: '#F59E0B' }
    ];

    const cx = 110, cy = 110, r = 78, strokeWidth = 22;
    const circumference = 2 * Math.PI * r;
    let accumulatedAngle = -90; // Start at top

    actions.forEach(item => {
      const pct = (item.count / total);
      const strokeDash = pct * circumference;
      const strokeGap = circumference - strokeDash;

      const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      circle.setAttribute('cx', cx);
      circle.setAttribute('cy', cy);
      circle.setAttribute('r', r);
      circle.setAttribute('fill', 'transparent');
      circle.setAttribute('stroke', item.color);
      circle.setAttribute('stroke-width', strokeWidth);
      circle.setAttribute('stroke-dasharray', `${strokeDash} ${strokeGap}`);
      circle.setAttribute('transform', `rotate(${accumulatedAngle} ${cx} ${cy})`);
      circle.style.transition = 'stroke-width 0.2s ease';
      circle.style.cursor = 'pointer';

      circle.addEventListener('mouseenter', () => {
        circle.setAttribute('stroke-width', strokeWidth + 6);
      });
      circle.addEventListener('mouseleave', () => {
        circle.setAttribute('stroke-width', strokeWidth);
      });

      svg.appendChild(circle);
      accumulatedAngle += (pct * 360);

      // Add to legend
      const legItem = document.createElement('div');
      legItem.className = 'legend-item';
      legItem.innerHTML = `
        <span class="legend-color-dot" style="background-color: ${item.color}"></span>
        <span class="legend-action">${item.name}</span>
        <span class="legend-count">${item.count}</span>
        <span class="legend-pct">${(pct * 100).toFixed(1)}%</span>
      `;
      legend.appendChild(legItem);
    });
  },

  async populateOverviewRecentTable() {
    const res = await fetch('/api/threads?limit=8');
    const data = await res.json();
    const tbody = document.getElementById('tbody-overview-recent');
    if (!tbody) return;

    tbody.innerHTML = '';
    data.records.forEach(row => {
      const tr = document.createElement('tr');
      const actionPillClass = `pill-${row.action.toLowerCase()}`;
      tr.innerHTML = `
        <td class="table-code"><strong>${row.thread_id}</strong></td>
        <td>${row.date}</td>
        <td><strong>${row.supplier}</strong></td>
        <td>${row.category}</td>
        <td>${row.quantity.toLocaleString()}</td>
        <td>Round ${row.round}</td>
        <td><span class="status-pill ${actionPillClass}">${row.action}</span></td>
        <td class="table-code">${row.label}</td>
        <td>
          <button class="btn-secondary" onclick="App.navigateTo('workspace'); App.loadDemoScenario('${row.thread_id}')">
            Inspect &rarr;
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  },

  async fetchThreadsForSelect() {
    const res = await fetch('/api/threads?limit=100');
    const data = await res.json();
    const select = document.getElementById('ws-thread-select');
    if (!select) return;

    select.innerHTML = '';
    data.records.forEach(row => {
      const opt = document.createElement('option');
      opt.value = row.thread_id;
      opt.textContent = `${row.thread_id} &bull; ${row.supplier} &bull; ${row.category} (R${row.round}) &rarr; ${row.action}`;
      if (row.thread_id === this.state.currentThreadId) opt.selected = true;
      select.appendChild(opt);
    });
  },

  handleThreadSelectChange(threadId) {
    this.loadThreadDetails(threadId);
  },

  loadDemoScenario(threadId) {
    const select = document.getElementById('ws-thread-select');
    if (select) {
      let found = false;
      for (let opt of select.options) {
        if (opt.value === threadId) {
          opt.selected = true;
          found = true;
          break;
        }
      }
      if (!found) {
        const opt = document.createElement('option');
        opt.value = threadId;
        opt.textContent = `${threadId} (Scenario)`;
        opt.selected = true;
        select.prepend(opt);
      }
    }
    this.loadThreadDetails(threadId);
  },

  async loadThreadDetails(threadId) {
    this.state.currentThreadId = threadId;
    const res = await fetch(`/api/thread/${threadId}`);
    if (!res.ok) return;

    const data = await res.json();
    this.state.currentThreadData = data;

    // Update metadata strip
    const metaStrip = document.getElementById('ws-meta-strip');
    if (metaStrip) {
      metaStrip.innerHTML = `
        <span class="meta-pill">Category: <strong>${data.category}</strong></span>
        <span class="meta-pill">Supplier: <strong>${data.supplier}</strong></span>
        <span class="meta-pill">Quantity: <strong>${data.quantity.toLocaleString()}</strong></span>
        <span class="meta-pill">Round: <strong>${data.round}</strong></span>
        <span class="meta-pill">Last Counter: <strong>${data.our_last_counter ? '₹' + data.our_last_counter.toLocaleString() : 'None (R1)'}</strong></span>
      `;
    }

    // Update email UI
    const elSub = document.getElementById('email-subject');
    if (elSub) elSub.textContent = `Re: Procurement Tender — ${data.category.toUpperCase()}`;

    const elThreadBadge = document.getElementById('email-thread-badge');
    if (elThreadBadge) elThreadBadge.textContent = `Thread #${data.thread_id}`;

    const elSender = document.getElementById('email-sender');
    if (elSender) elSender.textContent = `${data.supplier} Sales Operations`;

    const elCat = document.getElementById('email-cat');
    if (elCat) elCat.textContent = data.category;

    const elDate = document.getElementById('email-date');
    if (elDate) elDate.textContent = data.date;

    const elRoundTag = document.getElementById('latest-round-tag');
    if (elRoundTag) elRoundTag.textContent = `Negotiation Round ${data.round}`;

    // Earlier messages
    const earlierWrap = document.getElementById('earlier-messages-wrap');
    const earlierContent = document.getElementById('earlier-messages-content');
    if (data.earlier_message && earlierWrap && earlierContent) {
      earlierWrap.style.display = 'block';
      earlierContent.textContent = data.earlier_message;
    } else if (earlierWrap) {
      earlierWrap.style.display = 'none';
    }

    // Latest message
    const latestBody = document.getElementById('latest-message-body');
    if (latestBody) {
      latestBody.textContent = data.latest_message || data.supplier_message;
    }

    // Reset decision view until analyzed
    this.resetDecisionView(data.label);
  },

  toggleEarlierMessages() {
    const content = document.getElementById('earlier-messages-content');
    if (content) {
      const isVisible = content.style.display !== 'none';
      content.style.display = isVisible ? 'none' : 'block';
    }
  },

  resetDecisionView(existingLabel) {
    const hero = document.getElementById('decision-hero');
    hero.className = 'decision-hero-card';

    document.getElementById('dec-badge').textContent = 'SYNCED';
    document.getElementById('dec-rule-fired').textContent = 'Click "Run Procurement Analysis" to verify engine evaluation';
    document.getElementById('dec-label').textContent = existingLabel || '--';
    document.getElementById('dec-explanation').textContent = 'Press the button above to run the live Python agent on this negotiation thread.';

    // Reset metric tiles
    document.getElementById('m-norm-price').textContent = '--';
    document.getElementById('m-concession-l').textContent = '--';
    document.getElementById('m-target-walkaway').textContent = '--';
    document.getElementById('m-order-value').textContent = '--';
    document.getElementById('m-approval-limit').textContent = '--';
    document.getElementById('m-supplier-status').textContent = '--';

    const progBox = document.getElementById('analysis-progress-box');
    if (progBox) progBox.style.display = 'none';
  },

  // ==========================================================================
  // RUN PROCUREMENT ANALYSIS (LIVE ANIMATION + PYTHON EXECUTION)
  // ==========================================================================

  async runAnalysis() {
    const threadId = this.state.currentThreadId;
    const progBox = document.getElementById('analysis-progress-box');
    const stagesList = document.getElementById('stages-list');
    const timer = document.getElementById('progress-timer');
    const btn = document.getElementById('btn-run-analysis');

    btn.disabled = true;
    progBox.style.display = 'block';

    const startTime = performance.now();
    const interval = setInterval(() => {
      const elapsed = Math.round(performance.now() - startTime);
      if (timer) timer.textContent = `${elapsed} ms`;
    }, 20);

    // Reset stages
    for (let i = 1; i <= 10; i++) {
      const stage = document.getElementById(`stage-${i}`);
      stage.className = 'stage-item pending';
    }

    // Step-by-step smooth progress sequence
    for (let i = 1; i <= 10; i++) {
      const stage = document.getElementById(`stage-${i}`);
      stage.className = 'stage-item running';
      await new Promise(r => setTimeout(r, 60)); // 60ms per stage animation
      stage.className = 'stage-item done';
    }

    // Call actual backend Python API
    try {
      const res = await fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thread_id: threadId })
      });
      const data = await res.json();

      clearInterval(interval);
      if (timer) timer.textContent = `${Math.round(performance.now() - startTime)} ms &bull; DONE`;
      btn.disabled = false;

      this.renderDecisionResult(data);
    } catch (err) {
      console.error("[APP] Analysis failed:", err);
      clearInterval(interval);
      btn.disabled = false;
    }
  },

  renderDecisionResult(data) {
    const hero = document.getElementById('decision-hero');
    const action = data.action;
    const heroClass = `${action.toLowerCase()}-hero`;
    hero.className = `decision-hero-card ${heroClass}`;

    document.getElementById('dec-badge').textContent = action;
    document.getElementById('dec-rule-fired').textContent = `Reason: ${data.reason}`;
    document.getElementById('dec-label').textContent = data.label;

    let explanationText = "";
    if (action === 'ACCEPT') {
      explanationText = "Offer price is within acceptable concession threshold L(r) and total commitment is below corporate approval limit.";
    } else if (action === 'COUNTER') {
      explanationText = `Offer exceeds acceptable threshold L(r). Emitted counteroffer price of ₹${data.counter_price?.toLocaleString()} rounded to nearest rupee.`;
    } else if (action === 'REJECT') {
      if (data.reason === 'BLACKLISTED_SUPPLIER') {
        explanationText = "Supplier has status BLACKLISTED due to compliance/audit failure. Rejected immediately.";
      } else {
        explanationText = "Final round offer strictly exceeds walk-away price ceiling. Thread terminated.";
      }
    } else if (action === 'ESCALATE') {
      if (data.reason === 'PROMPT_INJECTION') {
        explanationText = "Adversarial prompt injection attempt detected in conversation transcript. Escalated to Security.";
      } else if (data.reason === 'BANNED_TERM') {
        explanationText = "Prohibited commercial contract clause detected in latest message. Escalated to Legal.";
      } else if (data.reason === 'OVER_APPROVAL_LIMIT') {
        explanationText = "Total contract commitment exceeds category single-order approval limit. Escalated to Executive Procurement.";
      } else {
        explanationText = "Missing or unparseable commercial information (missing price or unlisted currency). Escalated to Category Manager.";
      }
    }
    document.getElementById('dec-explanation').textContent = explanationText;

    // Populate metric tiles
    const diag = data.diagnostics || {};
    document.getElementById('m-norm-price').textContent = diag.normalized_price ? `₹${diag.normalized_price.toLocaleString(undefined, {maximumFractionDigits: 2})}` : 'MISSING';
    document.getElementById('m-concession-l').textContent = diag.concession_level_L ? `₹${diag.concession_level_L.toLocaleString(undefined, {maximumFractionDigits: 2})}` : '--';
    document.getElementById('m-target-walkaway').textContent = `₹${diag.target_price?.toLocaleString()} / ₹${diag.walkaway_price?.toLocaleString()}`;
    document.getElementById('m-order-value').textContent = diag.total_order_value ? `₹${diag.total_order_value.toLocaleString(undefined, {maximumFractionDigits: 0})}` : '--';
    document.getElementById('m-approval-limit').textContent = diag.approval_limit ? `₹${diag.approval_limit.toLocaleString()}` : '--';
    document.getElementById('m-supplier-status').textContent = diag.supplier_status || 'APPROVED';

    // Populate rule trace accordion
    const traceContainer = document.getElementById('trace-steps-container');
    if (traceContainer) {
      traceContainer.innerHTML = '';
      (data.rule_trace || []).forEach(tr => {
        const div = document.createElement('div');
        div.className = 'trace-step-item';
        div.innerHTML = `
          <span class="t-status ${tr.passed ? 'pass' : 'fail'}">${tr.passed ? '✓ PASS' : '✗ FIRED'}</span>
          <span class="t-name">${tr.name}</span>
          <span class="t-desc">${tr.details}</span>
        `;
        traceContainer.appendChild(div);
      });
    }
  },

  toggleDecisionTrace() {
    const body = document.getElementById('accordion-trace-body');
    const icon = document.getElementById('acc-icon');
    if (body) {
      const isVisible = body.style.display !== 'none';
      body.style.display = isVisible ? 'none' : 'block';
      if (icon) icon.innerHTML = isVisible ? '&blacktriangleright;' : '&blacktriangledown;';
    }
  },

  // ==========================================================================
  // VIEW 3: AGENT ARCHITECTURE
  // ==========================================================================

  showModuleDetails(moduleId) {
    const mod = this.modulesCatalog[moduleId];
    if (!mod) return;

    const drawer = document.getElementById('module-detail-drawer');
    document.getElementById('m-drawer-badge').textContent = mod.badge;
    document.getElementById('m-drawer-title').textContent = mod.title;
    document.getElementById('m-drawer-file').textContent = mod.file;
    document.getElementById('m-drawer-resp').textContent = mod.resp;
    document.getElementById('m-drawer-inputs').textContent = mod.inputs;
    document.getElementById('m-drawer-proc').textContent = mod.proc;
    document.getElementById('m-drawer-outputs').textContent = mod.outputs;

    drawer.style.display = 'block';
    drawer.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  },

  closeModuleDrawer() {
    const drawer = document.getElementById('module-detail-drawer');
    if (drawer) drawer.style.display = 'none';
  },

  // ==========================================================================
  // VIEW 4: SECURITY INTELLIGENCE
  // ==========================================================================

  switchSecTab(tabId) {
    document.querySelectorAll('.sec-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.sec-tab-pane').forEach(p => p.classList.remove('active'));

    event.target.classList.add('active');
    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add('active');
  },

  setInjectionText(text) {
    const ta = document.getElementById('injection-input');
    if (ta) ta.value = text;
  },

  setBannedText(text) {
    const ta = document.getElementById('banned-input');
    if (ta) ta.value = text;
  },

  async runInjectionScan() {
    const input = document.getElementById('injection-input').value.trim();
    if (!input) return;

    const res = await fetch('/api/security-scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input })
    });
    const data = await res.json();

    const box = document.getElementById('injection-scan-result');
    const pill = document.getElementById('inj-status-pill');
    const desc = document.getElementById('inj-detail-text');
    const code = document.getElementById('inj-action-code');

    box.style.display = 'block';
    if (data.has_prompt_injection) {
      pill.className = 'scan-pill flagged';
      pill.textContent = 'FLAGGED';
      desc.textContent = "Adversarial prompt injection signature detected in message text. Corporate policy mandates immediate escalation.";
      code.textContent = `Action Label: ${data.action_triggered}`;
    } else {
      pill.className = 'scan-pill clean';
      pill.textContent = 'CLEAN';
      desc.textContent = "No prompt injection patterns detected. Text passed security policy checks cleanly.";
      code.textContent = "Action Label: PASS (No security escalation)";
    }
  },

  async runBannedScan() {
    const input = document.getElementById('banned-input').value.trim();
    if (!input) return;

    const res = await fetch('/api/security-scan', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: input })
    });
    const data = await res.json();

    const box = document.getElementById('banned-scan-result');
    const pill = document.getElementById('banned-status-pill');
    const desc = document.getElementById('banned-detail-text');
    const code = document.getElementById('banned-action-code');

    box.style.display = 'block';
    if (data.has_banned_terms) {
      pill.className = 'scan-pill flagged';
      pill.textContent = 'FLAGGED';
      desc.textContent = "Prohibited commercial clause detected (auto-renewal, upfront >30%, unlimited liability, or exclusivity). Escalated to Legal.";
      code.textContent = `Action Label: ${data.action_triggered}`;
    } else {
      pill.className = 'scan-pill clean';
      pill.textContent = 'CLEAN';
      desc.textContent = "No banned commercial terms found. Proposal meets legal guidelines.";
      code.textContent = "Action Label: PASS (Proceeds to price evaluation)";
    }
  },

  // ==========================================================================
  // VIEW 5: DECISION ENGINE (CONCESSION CURVE SIMULATOR)
  // ==========================================================================

  initConcessionCanvas() {
    this.updateConcessionSim();
  },

  updateConcessionSim() {
    const rInput = document.getElementById('slider-round');
    const bInput = document.getElementById('slider-beta');
    if (!rInput || !bInput) return;

    const r = parseFloat(rInput.value);
    const beta = parseFloat(bInput.value);
    this.state.concessionSim.r = r;
    this.state.concessionSim.beta = beta;

    document.getElementById('val-round').textContent = r;
    document.getElementById('val-beta').textContent = beta.toFixed(1);

    const target = this.state.concessionSim.target;
    const walkaway = this.state.concessionSim.walkaway;
    const R = this.state.concessionSim.rounds;

    // Calculate L(r)
    let L = target;
    if (r === 1) {
      L = target;
    } else if (r >= R) {
      L = walkaway;
    } else {
      L = target + (walkaway - target) * Math.pow((r - 1) / (R - 1), beta);
    }

    const roundedL = Math.floor(L + 0.5);
    const simEl = document.getElementById('sim-l-val');
    if (simEl) simEl.textContent = `₹${roundedL}`;

    // Highlight active column
    for (let i = 1; i <= 3; i++) {
      const col = document.getElementById(`th-r${i}`);
      if (col) col.classList.toggle('active', i === r);
    }

    // Draw on canvas
    this.drawConcessionCanvas(target, walkaway, R, r, beta);
  },

  drawConcessionCanvas(target, walkaway, R, currentR, beta) {
    const canvas = document.getElementById('concession-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;

    ctx.clearRect(0, 0, w, h);

    const padLeft = 60, padRight = 30, padTop = 30, padBottom = 40;
    const plotW = w - padLeft - padRight;
    const plotH = h - padTop - padBottom;

    // Draw Grid Lines
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = 1;

    for (let i = 0; i <= 4; i++) {
      const y = padTop + (plotH / 4) * i;
      ctx.beginPath();
      ctx.moveTo(padLeft, y);
      ctx.lineTo(w - padRight, y);
      ctx.stroke();

      const priceLabel = Math.round(walkaway - ((walkaway - target) / 4) * i);
      ctx.fillStyle = '#64748B';
      ctx.font = '10px JetBrains Mono';
      ctx.textAlign = 'right';
      ctx.fillText(`₹${priceLabel}`, padLeft - 8, y + 3);
    }

    // X-axis round markers
    for (let rnd = 1; rnd <= R; rnd++) {
      const x = padLeft + ((rnd - 1) / (R - 1)) * plotW;
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
      ctx.beginPath();
      ctx.moveTo(x, padTop);
      ctx.lineTo(x, h - padBottom);
      ctx.stroke();

      ctx.fillStyle = rnd === currentR ? '#6366F1' : '#64748B';
      ctx.font = rnd === currentR ? 'bold 11px Inter' : '10px Inter';
      ctx.textAlign = 'center';
      ctx.fillText(`Round ${rnd}`, x, h - padBottom + 18);
    }

    // Plot Curve
    ctx.beginPath();
    ctx.strokeStyle = '#6366F1';
    ctx.lineWidth = 3;

    const points = [];
    for (let step = 0; step <= 50; step++) {
      const frac = step / 50;
      const roundVal = 1 + frac * (R - 1);
      const lVal = target + (walkaway - target) * Math.pow((roundVal - 1) / (R - 1), beta);
      const x = padLeft + frac * plotW;
      const y = h - padBottom - ((lVal - target) / (walkaway - target)) * plotH;
      points.push({ x, y, roundVal, lVal });

      if (step === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Area under curve fill
    ctx.lineTo(padLeft + plotW, h - padBottom);
    ctx.lineTo(padLeft, h - padBottom);
    ctx.fillStyle = 'rgba(99, 102, 241, 0.08)';
    ctx.fill();

    // Highlight Current Round Point
    const currentFrac = (currentR - 1) / (R - 1);
    const currentX = padLeft + currentFrac * plotW;
    const currentL = target + (walkaway - target) * Math.pow(currentFrac, beta);
    const currentY = h - padBottom - ((currentL - target) / (walkaway - target)) * plotH;

    ctx.beginPath();
    ctx.arc(currentX, currentY, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#3B82F6';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#FFFFFF';
    ctx.stroke();

    // Point Callout
    ctx.fillStyle = '#F8FAFC';
    ctx.font = 'bold 11px JetBrains Mono';
    ctx.textAlign = 'center';
    ctx.fillText(`L(${currentR}) = ₹${Math.floor(currentL + 0.5)}`, currentX, currentY - 12);
  },

  // ==========================================================================
  // VIEW 6: SUBMISSION ANALYTICS
  // ==========================================================================

  async fetchAnalyticsTable() {
    const page = this.state.analyticsPage;
    const limit = this.state.analyticsLimit;
    const action = this.state.analyticsAction;
    const search = this.state.analyticsSearch;

    const url = `/api/threads?page=${page}&limit=${limit}&action=${action}&search=${encodeURIComponent(search)}`;
    const res = await fetch(url);
    const data = await res.json();

    const tbody = document.getElementById('tbody-submission');
    const info = document.getElementById('pagination-info');
    const pageDisp = document.getElementById('page-display');
    const prevBtn = document.getElementById('btn-page-prev');
    const nextBtn = document.getElementById('btn-page-next');

    if (!tbody) return;
    tbody.innerHTML = '';

    data.records.forEach(row => {
      const tr = document.createElement('tr');
      const actionClass = `pill-${row.action.toLowerCase()}`;
      tr.innerHTML = `
        <td class="table-code"><strong>${row.thread_id}</strong></td>
        <td>${row.date}</td>
        <td><strong>${row.supplier}</strong></td>
        <td>${row.category}</td>
        <td>${row.quantity.toLocaleString()}</td>
        <td>Round ${row.round}</td>
        <td><span class="status-pill ${actionClass}">${row.action}</span></td>
        <td class="table-code">${row.label}</td>
        <td>
          <button class="btn-secondary" onclick="App.navigateTo('workspace'); App.loadDemoScenario('${row.thread_id}')">
            View &rarr;
          </button>
        </td>
      `;
      tbody.appendChild(tr);
    });

    const start = (page - 1) * limit + 1;
    const end = Math.min(start + data.records.length - 1, data.total);
    if (info) info.textContent = `Showing ${start} to ${end} of ${data.total.toLocaleString()} threads`;
    if (pageDisp) pageDisp.textContent = `${page} / ${data.total_pages}`;

    if (prevBtn) prevBtn.disabled = (page <= 1);
    if (nextBtn) nextBtn.disabled = (page >= data.total_pages);
  },

  prevPage() {
    if (this.state.analyticsPage > 1) {
      this.state.analyticsPage--;
      this.fetchAnalyticsTable();
    }
  },

  nextPage() {
    this.state.analyticsPage++;
    this.fetchAnalyticsTable();
  },

  // ==========================================================================
  // VIEW 7: PLAYBOOK EXPLORER
  // ==========================================================================

  async fetchPlaybook() {
    const res = await fetch('/api/playbook');
    const data = await res.json();
    this.state.playbook = data;

    this.renderCategories(data.categories);
    this.renderSuppliers(data.suppliers);
    this.renderAmendments(data.amendments);
    this.renderPrecedents(data.precedents);
  },

  switchPbTab(tabId) {
    document.querySelectorAll('.pb-tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.pb-tab-pane').forEach(p => p.classList.remove('active'));

    event.target.classList.add('active');
    const pane = document.getElementById(tabId);
    if (pane) pane.classList.add('active');
  },

  renderCategories(categories) {
    const container = document.getElementById('pb-categories-container');
    if (!container) return;
    container.innerHTML = '';

    categories.forEach(cat => {
      const card = document.createElement('div');
      card.className = 'cat-card';
      card.innerHTML = `
        <div class="cat-header">
          <span class="cat-name">${cat.name}</span>
          <span class="cat-gst-tag">${(cat.gst_rate * 100).toFixed(0)}% GST</span>
        </div>
        <div class="cat-props-grid">
          <div class="cat-prop-item"><span class="p-lbl">Unit:</span><span class="p-val">${cat.unit}</span></div>
          <div class="cat-prop-item"><span class="p-lbl">Target:</span><span class="p-val">₹${cat.target_price.toLocaleString()}</span></div>
          <div class="cat-prop-item"><span class="p-lbl">Walk-away:</span><span class="p-val">₹${cat.walkaway_price.toLocaleString()}</span></div>
          <div class="cat-prop-item"><span class="p-lbl">Rounds (R):</span><span class="p-val">${cat.total_rounds}</span></div>
          <div class="cat-prop-item"><span class="p-lbl">Exponent (&beta;):</span><span class="p-val">${cat.concession_exponent}</span></div>
          <div class="cat-prop-item"><span class="p-lbl">Approval Limit:</span><span class="p-val">₹${cat.approval_limit.toLocaleString()}</span></div>
        </div>
      `;
      container.appendChild(card);
    });
  },

  renderSuppliers(suppliers) {
    const container = document.getElementById('pb-suppliers-container');
    if (!container) return;
    container.innerHTML = '';

    suppliers.forEach(sup => {
      const card = document.createElement('div');
      card.className = 'sup-card';
      let statusColor = 'var(--color-accept)';
      if (sup.status === 'BLACKLISTED') statusColor = 'var(--color-reject)';
      if (sup.status === 'PROBATION') statusColor = 'var(--color-escalate)';

      let rateText = "";
      if (sup.contract_rates && Object.keys(sup.contract_rates).length > 0) {
        rateText = Object.entries(sup.contract_rates).map(([c, r]) => `${c}: ₹${r}`).join(', ');
      }

      card.innerHTML = `
        <div class="sup-top">
          <span class="sup-name">${sup.name}</span>
          <span class="status-pill" style="color: ${statusColor}; border-color: ${statusColor}; background: transparent;">${sup.status}</span>
        </div>
        ${rateText ? `<div style="font-size: 10px; color: #A5B4FC; margin-bottom: 4px;">Contract FX: ${rateText}</div>` : ''}
        <div class="sup-notes">${sup.notes || 'Standard commercial contract.'}</div>
      `;
      container.appendChild(card);
    });
  },

  filterSuppliers(query) {
    if (!this.state.playbook) return;
    const q = query.toLowerCase().trim();
    const filtered = this.state.playbook.suppliers.filter(s => 
      s.name.toLowerCase().includes(q) || s.status.toLowerCase().includes(q)
    );
    this.renderSuppliers(filtered);
  },

  renderAmendments(amendments) {
    const container = document.getElementById('pb-amendments-container');
    if (!container) return;
    container.innerHTML = '';

    amendments.forEach(amd => {
      const item = document.createElement('div');
      item.className = 'amd-item';
      item.innerHTML = `
        <span class="amd-id">${amd.id}</span>
        <span class="amd-date">Eff: ${amd.effective_date}</span>
        <span class="amd-cat">${amd.category}</span>
        <span class="amd-desc">Updated <strong>${amd.field_changed}</strong> to <strong>₹${amd.new_value.toLocaleString()}</strong></span>
      `;
      container.appendChild(item);
    });
  },

  renderPrecedents(precedents) {
    const container = document.getElementById('pb-precedents-container');
    if (!container) return;
    container.innerHTML = '';

    precedents.forEach(prec => {
      const card = document.createElement('div');
      card.className = 'prec-card';
      card.innerHTML = `
        <div class="prec-id">${prec.id}</div>
        <div class="prec-cat">${prec.category || 'Negotiation Policy Case'}</div>
        <div class="prec-desc">${prec.description}</div>
      `;
      container.appendChild(card);
    });
  }
};

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  App.init();
});
