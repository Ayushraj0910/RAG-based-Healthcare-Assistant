# 🏥 Healthcare RAG Assistant

A secure, explainable healthcare chatbot combining **SQL** and **RAG** agents over patient records and hospital policies — with role-based access control, validated SQL generation, confidence-scored routing, cited policy answers, and safety escalation for medical emergencies.

Built as a **FastAPI backend** + **vanilla HTML/CSS/JS frontend** (no build step required).

---

## ✨ Features

| Area | What it does |
|---|---|
| 🧭 **Smart Routing** | Confidence-scored classification between patient-record, policy, and general-health questions, with automatic fallback when confidence is low |
| 🗄️ **Patient Records (SQL Agent)** | Natural-language → SQL over a synthetic hospital dataset, with strict SQL validation (no stacked queries, no `SELECT *`, no unsafe keywords) |
| 📚 **Hospital Policies (RAG Agent)** | FAISS-based retrieval with numbered inline citations `[1]`, `[2]` mapped to exact source, section, and line-range evidence |
| 🔐 **Role-Based Access Control** | Four roles (`admin`, `clinician`, `billing`, `front_desk`) scope both query generation and result columns, following HIPAA's "minimum necessary" principle |
| 📝 **Audit Logging** | Append-only log of every access — who, what, when, and whether it was denied or escalated |
| 📊 **RAG Evaluation Metrics** | Real-time groundedness, relevance, and coverage scoring to flag possible hallucination or weak retrieval — no extra LLM call needed |
| 🚨 **Safety Screening & Escalation** | Detects emergency language (chest pain, suicidal ideation, stroke symptoms, etc.) before routing, and validates every generated answer (blocks prescriptive advice, strips specific dosages, adds disclaimers) |

---

## 🗂️ Project Structure

```
healthcare_rag_assistant_app/
├── backend/                      FastAPI REST API
│   ├── main.py                    Routes: /api/chat, /api/health, /api/tips, /api/audit, /api/roles
│   ├── src/
│   │   ├── config.py                 Paths + env settings
│   │   ├── database.py               SQLite patient DB (loaded from CSV)
│   │   ├── llm.py                    Groq LLM wrapper
│   │   ├── router.py                 Confidence-scored routing + fallback
│   │   ├── sql_agent.py              NL → SQL, role-scoped
│   │   ├── rag_agent.py              FAISS retrieval + page-level citations
│   │   ├── access_control.py         SQL validation + RBAC
│   │   ├── audit.py                  Append-only audit log
│   │   ├── safety.py                 Emergency screening + response validation
│   │   └── evaluation.py             RAG quality metrics + routing confidence
│   ├── data/
│   │   ├── healthcare_dataset.csv
│   │   └── policies/*.md
│   ├── requirements.txt
│   └── .env.example
└── frontend/                      Static web client (no build step)
    ├── index.html
    ├── style.css
    └── app.js
```

---

## 🚀 Getting Started

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The first request to the RAG agent builds the policy embedding index (falls back to TF-IDF automatically if `sentence-transformers` isn't installed).

Optional: copy `.env.example` to `.env` and set `GROQ_API_KEY` so you don't need to paste it into the UI every time.

### 2. Frontend

```bash
cd frontend
python -m http.server 5500
```

Open `http://localhost:5500` in your browser.

If the backend runs somewhere other than `http://localhost:8000`, point the frontend at it before `app.js` loads:

```html
<script>window.HEALTHCARE_API_BASE = "https://your-backend-host";</script>
```

---

## 🔌 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | API status, Groq connection, DB/audit stats |
| `GET` | `/api/tips` | Currently-rotating health tip |
| `GET` | `/api/roles` | Available RBAC roles |
| `GET` | `/api/audit` | Recent audit-log events |
| `POST` | `/api/chat` | Main chat endpoint — send `{ "query": "...", "api_key": "...", "role": "..." }` |

`POST /api/chat` returns the answer plus routing confidence, safety flags/escalation status, and either generated SQL + role-filtered rows (patient questions) or numbered citations with line-level evidence and evaluation metrics (policy questions).

---

## 🛡️ Safety & Security Details

- **SQL validation** — every query, whether template- or LLM-generated, is parsed with `sqlparse` and checked against an allow-list before touching SQLite. Rejects stacked statements, comments, `SELECT *`, non-SELECT statements, unknown tables, and out-of-role columns.
- **RBAC** — `admin` / `clinician` / `billing` / `front_desk` roles each see only the patient-record columns relevant to their job.
- **Audit trail** — every access is logged with timestamp, role, query, executed SQL, row count, confidence, and safety flags.
- **Routing confidence** — keyword-match confidence triggers an LLM-classifier fallback when ambiguous, and defaults to the general assistant rather than guessing.
- **Citations** — every policy answer traces back to an exact file, section, and line range.
- **Evaluation metrics** — groundedness, relevance, and coverage scores flag possible hallucination or weak retrieval on every answer.
- **Emergency escalation** — incoming questions are screened for crisis language before routing, and outgoing answers are checked for unsafe dosage/diagnostic/prescriptive content.

---

## ⚠️ Disclaimer

This project uses **synthetic data** for demonstration and academic purposes only. It is **not a substitute for professional medical advice, diagnosis, or treatment**. Do not use it with real patient data or in a production clinical setting without a full security and compliance review.

---


