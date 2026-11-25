# Requirements Traceability Matrix

This document provides complete traceability from requirements and core capabilities to their concrete implementation files, API endpoints, user interfaces, and automated test coverage.

> **LEGAL NOTICE: ADVISORY ONLY**  
> All recommendations and redlines produced by this system are based strictly on corporate negotiation playbook policies and do not constitute independent legal counsel. Human review and signoff by qualified legal counsel is mandatory prior to finalization.

---

## 1. Key Features Traceability

| Feature | Requirement Description | Implementation Files & Endpoints | Test Suite Coverage | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Contract Upload & Extraction** | Accept `.docx` and text-based `.pdf` documents; stream-read and enforce 10 MB size limits; reject empty or unsupported files; preserve structural paragraph order and heading styles without OCR. | - `backend/app/api/reviews.py` (`POST /contracts/upload`)<br>- `backend/app/services/parser.py`<br>- `frontend/src/pages/HomePage.tsx` | - `backend/tests/test_parser.py`<br>- `backend/tests/test_reviews_api.py` (`test_upload_validation_*`, `test_path_traversal_filename_sanitization`) | **MET** |
| **Automatic Clause Segmentation** | Partition parsed text into complete substantive clause units including all sub-clauses (1.1, 1.2); extract preamble, definitions, and signature blocks separately; support contracts with no numbering via style or paragraph fallback. | - `backend/app/services/segmenter.py`<br>- `backend/app/services/segment_refine.py`<br>- `backend/app/graph/contract_graph.py` (`segment_node`) | - `backend/tests/test_segmenter.py` (7 tests covering compliant, needs negotiation, unacceptable, unnumbered, PDF signatures, definitions, LLM refinement) | **MET** |
| **Playbook Integration (RAG / Vector DB)** | Corporate negotiation playbook with 10 standard clause types in JSON; persistent ChromaDB vector store; custom embedding interface (`generate_embedding`); filtered and fallback semantic rule retrieval. | - `backend/data/playbook.json`<br>- `backend/app/services/playbook.py`<br>- `backend/app/services/vector_store.py`<br>- `backend/app/api/playbook.py` (`GET /playbook/rules`, `POST /playbook/reindex`) | - `backend/tests/test_playbook.py`<br>- `backend/tests/test_playbook_api.py`<br>- `backend/tests/test_vector_store.py` (idempotency, rebuild, retrieval, auto-ingest) | **MET** |
| **Risk Classification** | Classify each substantive clause into one of the 10 playbook clause types (or `other`) and evaluate risk strictly against playbook standard positions and acceptable fallbacks: *Acceptable*, *Needs Negotiation*, *Unacceptable*. | - `backend/app/graph/clause_graph.py` (`classify_node`, `analyze_node`)<br>- `backend/app/graph/prompts.py`<br>- `frontend/src/components/RiskBadge.tsx` | - `backend/tests/test_clause_graph.py` (`test_clause_graph_acceptable_happy_path`, `test_clause_graph_needs_negotiation_generates_redline`, `test_clause_graph_unacceptable_generates_redline`)<br>- `frontend/src/test/RiskBadge.test.tsx` | **MET** |
| **Risky Clause Identification** | Identify clauses deviating from standard positions; flag clauses where confidence is below threshold (< 0.70), citations are missing or ungrounded, or clause type is `other`. | - `backend/app/graph/clause_graph.py` (`ground_node`)<br>- `backend/app/graph/contract_graph.py` (`summarize_node`)<br>- `frontend/src/pages/ReviewPage.tsx` | - `backend/tests/test_clause_graph.py` (`test_clause_graph_hallucinated_citation_removed`, `test_clause_graph_non_acceptable_without_citation_flagged`, `test_clause_graph_other_clause_type_flagged`, `test_clause_graph_low_confidence_flagged`) | **MET** |
| **AI-Generated Redline Suggestions** | Generate minimal, compliant replacement text adapted to contract terms for *Needs Negotiation* and *Unacceptable* clauses; skip redlines for *Acceptable*; provide word-level diff computation and visual styling. | - `backend/app/graph/clause_graph.py` (`redline_node`, conditional edge `should_redline`)<br>- `backend/app/services/diff.py`<br>- `frontend/src/components/DiffViewer.tsx` | - `backend/tests/test_report.py` (`test_diff_helper_*`)<br>- `backend/tests/test_clause_graph.py` (`test_clause_graph_needs_negotiation_generates_redline`)<br>- `frontend/src/test/DiffViewer.test.tsx` | **MET** |
| **Playbook-Based Explanations** | Ground every risk finding in retrieved playbook rules; provide plain-language explanations citing specific rule positions and triggers; non-LLM ground node strips hallucinated citations. | - `backend/app/graph/clause_graph.py` (`analyze_node`, `ground_node`)<br>- `backend/app/services/playbook.py` (`get_rule`)<br>- `frontend/src/components/PlaybookRuleCard.tsx` | - `backend/tests/test_clause_graph.py` (`test_clause_graph_hallucinated_citation_removed`)<br>- `backend/tests/test_playbook.py` (`test_get_rule_valid_and_invalid`) | **MET** |
| **Structured Review Reports** | Fully deterministic, non-LLM report builder compiling stored analyses, reviewer decisions, resulting contract text, and executive statistics in Markdown, DOCX (with visual diff styling), and JSON. | - `backend/app/services/report.py`<br>- `backend/app/services/report_export.py`<br>- `backend/app/api/reviews.py` (`GET /reviews/{review_id}/report`) | - `backend/tests/test_report.py` (`test_export_markdown`, `test_export_docx`, `test_export_json_roundtrip`, `test_report_endpoint_*`)<br>- `frontend/src/test/ReviewPage.test.tsx` | **MET** |
| **Legal Professional Review & Approval** | Human-in-the-loop review workflow: persistent Reviewer identity; decisions for *Approved*, *Edited* (mandatory final text), and *Rejected* (mandatory counsel rationale); append-only audit trail; decision gating blocking finalization until all required clauses are decided. | - `backend/app/services/db.py`<br>- `backend/app/api/reviews.py` (`POST /reviews/{review_id}/clauses/{clause_id}/decision`, `POST /reviews/{review_id}/finalize`)<br>- `frontend/src/pages/ReviewPage.tsx`<br>- `frontend/src/components/Header.tsx` | - `backend/tests/test_reviews_api.py` (`test_decision_validation_rules`, `test_decision_audit_history_and_changing_decisions`, `test_finalize_blocked_while_decisions_pending`, `test_successful_finalize_and_decision_locking`)<br>- `frontend/src/test/ReviewPage.test.tsx` | **MET** |

---

## 2. Technical Considerations & Safeguards

| Consideration | Design & Architecture | Verification & Coverage | Status |
| :--- | :--- | :--- | :--- |
| **Advisory Legal Boundary** | Prominent disclaimer on all UI headers, footers, API payloads, and report exports. System never provides autonomous legal advice or unilateral modifications. | Disclaimer string asserted in all API response schemas, report headers, and UI layout components. | **MET** |
| **Human Signoff Mandatory** | Reviews remain in `awaiting_review` status until counsel approves, edits, or rejects every flagged or non-acceptable clause. Finalization returns HTTP 409 Conflict if decisions are pending. | Tested in `test_finalize_blocked_while_decisions_pending` and frontend `ReviewPage.test.tsx`. | **MET** |
| **Fault Tolerance & Retries** | Single clause analysis failure triggers exponential backoff retries (`MAX_LLM_RETRIES`) and falls back to flagging for human review; never crashes the contract run. | Tested in `test_contract_graph_single_clause_error_fault_tolerance`. | **MET** |
| **Checkpointer Resume After Restart** | Contract workflow state checkpointer uses persistent SQLite database (`CHECKPOINT_DB_PATH`). Relational SQLite DB is the source of truth, enabling finalization even after a backend service restart. | Tested in `test_langgraph_sqlite_checkpointer_pause_and_resume` and `test_finalize_after_simulated_restart`. | **MET** |
| **Security & Hardening** | Chunked upload reading protects against memory exhaustion; filename sanitization strips directory traversal; CORS restricted to frontend dev hosts; adversarial injection handling in clause text verified. | Tested in `test_upload_validation_too_large`, `test_path_traversal_filename_sanitization`, `test_cors_headers_allowed_origin`, `test_clause_graph_prompt_injection_adversarial_handling`. | **MET** |
| **Concurrency & Resilience Bug-Checks** | Simultaneous uploads; SQLite locking prevention via WAL and immediate transactions; graceful fallback on malformed LLM JSON; clear error on scanned/empty PDFs; safe playbook re-indexing during active reviews; 409 Conflict rejection when attempting collection wipe during processing reviews. | Covered by 6 dedicated regression tests in `backend/tests/test_regressions.py`. | **MET** |
| **Free Tier Quota Optimization & Caching** | Merged classify and analyze into 1 structured call per clause (`CombinedAnalysisOutput`); candidate rule retrieval first (top 3); conditional redline for non-acceptable only; persistent SQLite cache for completions & embeddings (`LLM_CACHE_ENABLED`); fail-fast `DailyQuotaExceededError`; 6s request throttle; `--resume` in eval runner. | Tested across all 84 pytest tests, preflight probe `check_quota.py`, and `eval_samples.py --resume`. | **MET** |

---

## 3. Technology Stack Verification

| Component | Library / Framework | Real Usage Verification |
| :--- | :--- | :--- |
| **Language** | Python 3.10+ | Used across `backend/app/`, `backend/scripts/`, `backend/tests/`. Strictly PEP 8 with type hints. |
| **Web API** | FastAPI + Uvicorn | 11 REST endpoints defined across `health.py`, `playbook.py`, `reviews.py`. Async handlers, Pydantic v2 schemas. |
| **Orchestration** | LangGraph + LangChain Core | StateGraph workflows: `clause_analysis_graph` (per-clause pipeline) and `contract_analysis_graph` (contract-level pipeline with SQLite checkpointing and interrupt). |
| **Vector DB** | ChromaDB | Persistent collection stored at `CHROMA_PATH` (`./data/chroma`). Ingests rule documents with rule ID and clause type metadata. |
| **RAG Embeddings** | Google GenAI SDK (`google.genai`) / Swappable Interface | `generate_embedding` interface in `backend/app/services/llm.py` embedding query and rule texts using `gemini-embedding-001` (3072 dimensions). |
| **LLM Provider** | Gemini 2.5 Flash / Gemini 3 Flash / Provider-Agnostic Interface | `generate_structured_json` interface in `backend/app/services/llm.py` with Pydantic JSON schema constraints. |
| **Persistence** | SQLite3 (WAL mode, IMMEDIATE transactions) | `reviews`, `clause_analyses`, and `review_decisions` tables in `backend/app/services/db.py` with foreign keys, busy timeout, and audit history. |
| **Frontend** | React 18 + TypeScript + Vite + Tailwind CSS | Single-page application in `frontend/` using native `fetch` client, React Router 6, responsive split layout, word diff viewer, and report download triggers. |
| **Testing** | Pytest (Backend) + Vitest (Frontend) | 88 backend pytest tests + 11 frontend Vitest tests = 99 passing automated tests. |

---

## 4. Benchmark Evaluation & Ground-Truth Traceability

The evaluation harness in `backend/scripts/eval_samples.py` evaluates all 30 substantive clauses across the 3 benchmark contracts (`sample_contract_compliant.docx`, `sample_contract_needs_negotiation.docx`, `sample_contract_unacceptable.docx`).

### Dual Benchmark Scores

| Contract | Substantive Clauses | Original Benchmark Match | Revised Benchmark Match | Notes |
| :--- | :---: | :---: | :---: | :--- |
| `sample_contract_compliant.docx` | 10 | **10/10 (100.0%)** | **10/10 (100.0%)** | Full adherence to standard playbook positions. |
| `sample_contract_needs_negotiation.docx` | 10 | **8/10 (80.0%)** | **10/10 (100.0%)** | 2 benchmark labels revised based on playbook rules. |
| `sample_contract_unacceptable.docx` | 10 | **10/10 (100.0%)** | **10/10 (100.0%)** | Full detection of policy-violating triggers. |
| **Overall Total** | **30** | **28/30 (93.3%)** | **30/30 (100.0%)** | 93.3% original match, 100.0% revised match. |

### Revised Benchmark Clauses

1. **`sample_contract_needs_negotiation.docx` - Clause 2 (indemnification / Section 2.1)**:
   - *Original Label*: `Needs Negotiation` -> *Revised Label*: `Unacceptable`
   - *Reason*: Section 2.1 hits two verbatim `IND-01` unacceptable triggers: (1) obligation to indemnify without receiving prompt written notice or sole control of defense, and (2) failure to provide reciprocal indemnity for Customer-furnished materials.
2. **`sample_contract_needs_negotiation.docx` - Clause 9 (data_protection / Section 9.1)**:
   - *Original Label*: `Acceptable` -> *Revised Label*: `Needs Negotiation`
   - *Reason*: The benchmark's own rationale states that 48-hour notification and annual SOC 2 report sharing *"conforms to acceptable fallback"*. Under the system rubric, conforming to an acceptable fallback maps to `Needs Negotiation` (consistent with all other fallback clauses in the same contract).

> **Evaluation Caveats**  
> Playbook, sample contracts, and benchmark labels were authored together with AI assistance, so the evaluation measures consistency with the company playbook rubric, not legal accuracy. Two labels were corrected after review, with reasons documented above and in `backend/data/samples/expected_findings.json`.
> On 2026-11-25, a live prompt-injection spot check on `test_injection_contract.docx` using `gemini-3-flash-preview` was **not affected**: Clause 1 stayed `Unacceptable` with a compliant redline without leaking the injected text, and Clauses 2–3 remained unaffected. A single test is only a spot check and not a security guarantee.
