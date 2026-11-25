# Contract Clause Risk-Flagging and Redline-Suggestion Agent (Backend)

> **IMPORTANT LEGAL NOTICE: ADVISORY ONLY**  
> This system is designed as an advisory assistant to help identify contractual risks against a predefined corporate negotiation playbook. **It does not provide legal advice.** All flagged risks, commentary, and redline suggestions are recommendations only and **must be reviewed and approved by qualified legal professionals** before taking any action or executing any agreement.

---

## Overview

An AI-powered agentic contract review MVP that:
1. Parses contract documents (`.docx`).
2. Extracts clauses and compares them against a corporate negotiation playbook.
3. Classifies clause risks (`Acceptable`, `Needs Negotiation`, `Unacceptable`).
4. Generates proposed redlines with rationale aligned with playbook rules.
5. Produces structured review reports for legal counsel oversight.

## Technology Stack

- **Backend Framework**: Python 3.10+, FastAPI, Uvicorn
- **Agentic Workflow**: LangGraph
- **Vector Store**: ChromaDB
- **LLM & Embeddings**: Provider-agnostic interface (default: Google Gemini via `google-genai`)
- **Data Parsing**: `python-docx`
- **Validation**: Pydantic v2

---

## Directory Structure

```
backend/
├── app/
│   ├── api/          # FastAPI routers and route handlers (e.g., /health)
│   ├── core/         # Settings, config, and system-wide utilities
│   ├── graph/        # LangGraph workflow definitions (subsequent steps)
│   ├── models/       # Pydantic schemas (PlaybookRule, Clause, Analysis, etc.)
│   ├── services/     # Business logic, LLM wrappers, vector store service
│   └── main.py       # FastAPI application entry point
├── data/
│   ├── playbook.json # Company negotiation playbook (10 clause types)
│   └── samples/      # Synthetic sample contracts (.docx) & expected findings
├── tests/            # Automated test suite (pytest)
├── .env.example      # Environment variable template
├── requirements.txt  # Python package dependencies
└── README.md         # Backend documentation
```

---

## Quickstart

### 1. Install Dependencies

```bash
cd backend
python3 -m pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and provide your Gemini API key:

```bash
cp .env.example .env
```

Edit `.env`:
```env
LLM_PROVIDER=gemini
LLM_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=text-embedding-004
CHROMA_PATH=./data/chroma
DB_PATH=./data/app.db
```

### 3. Run FastAPI Application

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Visit the interactive API docs at `http://localhost:8000/docs` or test the health endpoint:

```bash
curl http://localhost:8000/health
```

---

## CLI Utilities and Testing

### 1. Run Automated Tests
All unit and integration tests run offline without live API keys:
```bash
PYTHONPATH=backend pytest backend/tests/ -v
```

### 2. Segment Contracts (CLI Demo)
Inspect paragraph extraction, preamble detection, and substantive clause segmentation:
```bash
python3 backend/scripts/segment_demo.py backend/data/samples/sample_contract_compliant.docx
```

### 3. Playbook Vector Search (CLI Demo)
Test rule retrieval against specific clause text:
```bash
python3 backend/scripts/playbook_demo.py "In no event shall either party be liable for more than 1x annual fees."
```

### 4. Contract Analysis Pipeline (LangGraph Demo)
Run the full LangGraph per-clause classification, retrieval, risk analysis, redline generation, and non-LLM grounding pipeline:
```bash
python3 backend/scripts/analyze_demo.py backend/data/samples/sample_contract_needs_negotiation.docx
```

### 5. Benchmark Evaluation Runner
Evaluate the pipeline against expected risk findings across the 3 synthetic sample contracts:
```bash
python3 backend/scripts/eval_samples.py
```

---

## Contract Review & Human Approval API

### Endpoints Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/contracts/upload` | Multipart file upload (`.docx` / `.pdf`), triggers async analysis |
| `GET` | `/reviews` | List all reviews with risk counts and pending decision metrics |
| `GET` | `/reviews/{review_id}` | Full review detail, clauses, current decisions, and missing clauses |
| `GET` | `/reviews/{review_id}/status` | Lightweight polling for review status and progress |
| `GET` | `/reviews/{review_id}/clauses/{clause_id}` | Clause text, analysis, cited PlaybookRule objects, decision history |
| `POST` | `/reviews/{review_id}/clauses/{clause_id}/decision` | Record approved, edited, or rejected decision (appends to audit log) |
| `POST` | `/reviews/{review_id}/finalize` | Finalize and lock review (requires all necessary decisions) |
| `GET` | `/reviews/{review_id}/report` | Generate report in `json`, `md`, or `docx` (finalized reviews only) |

### 6. Generate & Export Review Reports (CLI Demo)
Seed a synthetic finalized review with approvals/edits/rejections and export reports without API keys:
```bash
python3 backend/scripts/report_demo.py --seed
```
Export reports for an existing finalized review ID:
```bash
python3 backend/scripts/report_demo.py <review_id> --format all
```
Generated reports are stored in `backend/data/reports/`.



