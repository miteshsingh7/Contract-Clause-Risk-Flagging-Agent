# 3-Minute Demo Script: Contract Clause Risk-Flagging & Redline-Suggestion Agent

This script guides a presenter or evaluator through a live 3-minute demonstration of the advisory legal agent, showcasing automated segmentation, playbook-grounded risk classification, word-level redline diffing, human decision gating, and deterministic report generation.

---

## Preparation (Before the Demo)

1. **Terminal 1 (Backend)**:
   ```bash
   cd backend && uvicorn app.main:app --port 8000
   ```
2. **Terminal 2 (Frontend)**:
   ```bash
   cd frontend && npm run dev
   ```
3. **Terminal 3 (Seed Data)**:
   ```bash
   PYTHONPATH=backend python3 backend/scripts/report_demo.py --seed-awaiting
   ```
   *Note the printed Review URL: `http://localhost:5173/reviews/demo-awaiting-xxxx`.*

---

## Demo Script (Timeline)

### 0:00 – 0:30 | Introduction & The Advisory Boundary
- **Action**: Open `http://localhost:5173` in the browser.
- **What to Point Out**:
  - Point to the permanent yellow disclaimer banner at the very top: *"Advisory only: recommendations are based on the company playbook and must be reviewed and approved by qualified legal professionals."*
  - Point to the **Reviewer Name** field in the top-right navbar. Type `Sarah Jenkins (Senior Legal Counsel)` into the input.
- **What to Say**:
  > *"Welcome. Reviewing third-party contracts against corporate negotiation policies is traditionally time-consuming and inconsistent. Our Agent automates clause extraction, segments substantive provisions, and evaluates risks strictly against our company negotiation playbook. Crucially, this system is ADVISORY ONLY: it never makes independent legal decisions, and no contract change is finalized without human legal approval."*

---

### 0:30 – 1:15 | The Review Workspace & Policy Grounding
- **Action**: Click on the seeded contract review link (or navigate to `/reviews/demo-awaiting-xxxx`).
- **What to Point Out**:
  - **Summary Metric Strip**: 5 substantive clauses (2 Needs Negotiation, 2 Unacceptable, 1 Acceptable, 5 pending decisions).
  - **Left Panel**: Filterable clause list. Select **Section 1: Limitation of Liability**.
  - **Right Panel**: Show original contract wording and AI Policy Evaluation.
  - Expand the **Grounding Playbook Rules** accordion card for rule **LOL-01**.
- **What to Say**:
  > *"Here is the review workspace. On the left, we see all substantive clauses categorized and color-coded: emerald for Acceptable, amber for Needs Negotiation, and rose for Unacceptable. On the right, notice how our agent grounds its findings directly in our company playbook. Rule LOL-01 mandates an aggregate cap of 12 months fees paid. Because the supplier offered only 6 months, our system flags it as 'Needs Negotiation' and cites the exact fallback position."*

---

### 1:15 – 2:00 | Redline Diff Viewer & Reviewer Decisions
- **Action**:
  1. Scroll to the **Suggested Redline Diff** viewer.
  2. Point out green underline insertions and red strikethrough deletions.
  3. Click the **Clean Text** toggle button, then toggle back to **Diff View**.
  4. In the decision form below:
     - Click **Approve** on Section 1. Click **Save Decision**.
     - Navigate to **Section 2: Indemnification** (Unacceptable unilateral customer indemnity).
     - Click **Edit**, modify the text in the textarea to add a custom indemnity cap, and click **Save Decision**.
     - Navigate to **Section 5: Governing Law** (Foreign English Law).
     - Click **Reject**, enter the mandatory note: *"Counterparty refused NY law; escalated to General Counsel."* Click **Save Decision**.
- **What to Say**:
  > *"When a clause deviates, our agent generates minimal replacement language adapted to the agreement. Our diff viewer provides clear word-level visual cues with an explicit 'AI suggestion, not yet approved' notice. As counsel, I have total control: I can approve the AI suggestion, edit it into a custom negotiation compromise, or reject it entirely with an audit trail note explaining the commercial rationale."*

---

### 2:00 – 2:40 | Decision Gating & Permanent Finalization
- **Action**:
  1. Look at the top-right **Finalize & Lock Review** button.
  2. Point out that it is currently **disabled** with a badge showing *"2 left"* (clauses 3 and 4 still need decisions).
  3. Quickly approve the remaining 2 clauses.
  4. Point out that the **Finalize & Lock Review** button is now **enabled**!
  5. Click **Finalize & Lock Review**.
  6. In the confirmation modal (*"This permanently locks all clause decisions. Are you sure?"*), click **Yes, Finalize & Lock**.
- **What to Say**:
  > *"Notice how the system mechanically enforces legal oversight: the Finalize button is locked until every substantive clause has a recorded human decision. Now that all 5 clauses have been reviewed, we click Finalize. The confirmation dialog warns that all decisions will be permanently locked. Once confirmed, the LangGraph checkpointer completes, the decision forms become read-only, and executive audit reports become available."*

---

### 2:40 – 3:00 | Deterministic Report Exports & Wrap-up
- **Action**:
  1. Point to the download buttons that appeared: **Markdown**, **Word (.docx)**, and **JSON**.
  2. Click **Word (.docx)** to download the executive review document.
  3. Show the downloaded Word document with formatted tables and color-coded redlines.
- **What to Say**:
  > *"Finally, the system generates comprehensive, non-LLM deterministic review reports in Word, Markdown, or JSON. The Word document includes our executive risk breakdown, missing clause findings, reviewer names, and exact redline diffs ready to send to opposing counsel. In under 3 minutes, our legal team reviewed, redlined, and approved a complex contract with complete consistency and policy compliance. Thank you!"*
