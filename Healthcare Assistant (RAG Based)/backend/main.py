"""
Healthcare Assistant - Backend API (FastAPI)

This is a REST API version of the original Streamlit app. It exposes the
same three-agent pipeline (SQL agent for patient records, RAG agent for
hospital policies, general LLM assistant) over HTTP so any frontend (the
bundled static frontend/, a mobile app, curl, etc.) can talk to it.

On top of the original pipeline this version adds:
  - Role-based access control + SQL validation for the patient-records agent
  - Append-only audit logging of every access
  - Confidence-scored routing with tiered fallback
  - Measurable RAG evaluation metrics and page/section-level citations
  - Healthcare safety screening, response validation, and escalation rules

Run with:
    uvicorn main:app --reload --port 8000
"""
import threading
import time
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.config import DATASET_PATH, GROQ_API_KEY
from src.database import PatientDatabase
from src.llm import GroqLLM
from src.router import Orchestrator
from src.sql_agent import SQLAgent
from src.rag_agent import RAGAgent
from src.access_control import Role, normalize_role, has_sql_access
from src.audit import AuditLogger
from src.safety import screen_query, validate_response

ROOT = Path(__file__).parent

app = FastAPI(title="Healthcare Assistant API", version="2.0")

# Allow the static frontend (served from any origin/port, e.g. file://, a
# separate dev server, or a different host) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------
# One-time, expensive startup work: load the patient DB and build the RAG
# embedding index. These do NOT depend on the Groq API key, so they only
# need to happen once no matter how many different keys users try.
# -----------------------------------------------------------------------
db = PatientDatabase(DATASET_PATH, ROOT / "data" / "healthcare.db")
rag = RAGAgent(llm=None)  # embeddings/index built once; llm swapped in per-request below
audit = AuditLogger(ROOT / "data" / "audit.db")

# Cache one GroqLLM instance per API key so repeated requests with the same
# key don't reconnect every time.
_llm_cache = {}
_llm_lock = threading.Lock()


def get_llm(api_key: Optional[str]) -> GroqLLM:
    key = api_key or GROQ_API_KEY
    with _llm_lock:
        if key not in _llm_cache:
            _llm_cache[key] = GroqLLM(key)
        return _llm_cache[key]


# rag holds a single embedding index but its `.llm` attribute decides which
# API key is used to *generate* the final answer from retrieved context.
# Requests are serialized with a lock so concurrent users can't stomp on
# each other's `.llm` swap.
_rag_lock = threading.Lock()


# -----------------------------------------------------------------------
# Health tips + local fallbacks (ported unchanged from the Streamlit app)
# -----------------------------------------------------------------------
HEALTH_TIPS = [
    "Stay hydrated throughout the day, especially when recovering from illness.",
    "Adequate sleep supports the body's normal recovery and immune function.",
    "Wash your hands regularly and avoid touching your face to reduce infection spread.",
    "Choose balanced meals with vegetables, fruit, protein and whole grains when possible.",
    "Gentle movement can be helpful when you feel well enough; avoid pushing through significant symptoms.",
    "Follow the treatment and medication instructions provided by your healthcare professional.",
    "If symptoms are getting worse rather than better, contact a healthcare professional for advice.",
    "Keep commonly used medicines stored safely and follow the label or clinician's instructions.",
    "Taking short breaks during a busy day can help reduce fatigue and improve concentration.",
    "For recovery, prioritize rest, fluids, nutrition and any follow-up recommended by your clinician.",
]

RECOVERY_TERMS = [
    "recover", "recovery", "cold", "flu", "fever", "cough", "sore throat",
    "infection", "illness", "sick", "tired", "fatigue", "pain", "healing",
    "after surgery", "post surgery", "wound", "vomit", "diarrhea", "dehydration",
]

RECOVERY_TIPS = [
    "Get plenty of rest and avoid strenuous activity while you feel unwell.",
    "Drink water and other suitable fluids to help prevent dehydration.",
    "Choose light, balanced meals as tolerated and continue any prescribed diet.",
    "Take medicines only according to the label or your healthcare professional's instructions.",
]


def recovery_tips_for(query: str) -> List[str]:
    q = query.lower()
    if not any(term in q for term in RECOVERY_TERMS):
        return []
    return RECOVERY_TIPS


def local_health_fallback(query: str) -> Optional[str]:
    q = query.lower().strip()
    if any(x in q for x in ["common cold", "having cold", "i have cold", "got a cold", "cold what should i do", "cold what can i do"]):
        return (
            "For a typical common cold, most people improve within about 7-10 days, although a cough or other symptoms can sometimes last longer. "
            "Rest, drink plenty of fluids, eat nourishing foods as tolerated, and use symptom-relief medicines only as directed on the label or by a healthcare professional. "
            "Seek medical care if you have trouble breathing, chest pain, severe dehydration, confusion, a very high or persistent fever, symptoms that are getting worse, or symptoms that are not improving as expected."
        )
    if "fever" in q:
        return (
            "For a mild fever, rest, drink fluids, and monitor how you feel. Follow the label or your clinician's advice if using fever-reducing medicine. "
            "Seek medical care for a very high or persistent fever, severe weakness, confusion, breathing difficulty, chest pain, or other concerning symptoms."
        )
    if "cough" in q:
        return (
            "For a mild cough, rest, stay hydrated, and avoid smoke or other irritants. Warm fluids may soothe the throat. "
            "Get medical advice if the cough is severe, lasts longer than expected, produces significant blood, or comes with breathing difficulty or chest pain."
        )
    return None


GENERAL_SYSTEM_PROMPT = (
    "You are Healthcare Assistant, a concise and empathetic general-health information assistant. "
    "Answer the user's question directly in plain English. For common minor illnesses such as a cold, "
    "give practical self-care guidance, a realistic general recovery timeframe when appropriate, and clear red flags. "
    "Do not diagnose, prescribe, or invent patient/hospital-policy facts. Never claim certainty about an individual patient's condition. "
    "For severe, worsening, urgent, or unusual symptoms, recommend prompt professional medical care. "
    "Keep the answer useful and reasonably concise."
)


# -----------------------------------------------------------------------
# Request / response models
# -----------------------------------------------------------------------
class ChatRequest(BaseModel):
    query: str
    api_key: Optional[str] = None
    role: Optional[str] = None
    user_id: Optional[str] = None


class ChatResponse(BaseModel):
    role: str = "assistant"
    content: str
    agent: str
    elapsed: float
    recovery_tips: List[str] = []
    sql: Optional[str] = None
    rows: Optional[list] = None
    sources: Optional[list] = None
    confidence: Optional[float] = None
    routing_method: Optional[str] = None
    evaluation: Optional[dict] = None
    safety_flags: List[str] = []
    escalated: bool = False
    access_role: Optional[str] = None
    warnings: List[str] = []


# -----------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------
@app.get("/api/health")
def health(api_key: Optional[str] = None):
    llm = get_llm(api_key)
    return {
        "status": "ok",
        "groq_connected": llm.available,
        "patient_records": db.stats(),
        "audit_events": audit.stats(),
    }


@app.get("/api/tips")
def tips():
    tip_index = int(time.time() // 25) % len(HEALTH_TIPS)
    return {"tip": HEALTH_TIPS[tip_index]}


@app.get("/api/audit")
def get_audit_log(limit: int = 100):
    """Read-only view of recent access/audit events (admin/ops use)."""
    return {"events": audit.recent(limit), "stats": audit.stats()}


@app.get("/api/roles")
def get_roles():
    """Expose available RBAC roles so a UI can offer a role picker."""
    return {"roles": sorted(Role.ALL), "default": Role.DEFAULT}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_user_role: Optional[str] = Header(default=None)):
    query = req.query.strip()
    role = normalize_role(req.role or x_user_role)
    llm = get_llm(req.api_key)
    orchestrator = Orchestrator(llm)
    sql_agent = SQLAgent(db, llm)

    t0 = time.time()

    # --- Safety screen runs before routing: an emergency-shaped question
    # should never be delayed by a RAG/SQL detour. ---
    screen = screen_query(query)

    decision = orchestrator.route(query)
    agent = decision.agent
    tips_for_query = recovery_tips_for(query)

    if agent == "SQL_AGENT":
        if not has_sql_access(role):
            audit.log(agent="Patient Records", query=query, user_id=req.user_id, role=role,
                       status="denied", detail="role lacks SQL access")
            return ChatResponse(
                content="Your current role does not have permission to view patient records.",
                agent="Access Denied", elapsed=time.time() - t0, confidence=decision.confidence,
                routing_method=decision.method, access_role=role,
            )
        result = sql_agent.run(query, role=role)
        answer = sql_agent.summarize(query, result["rows"])
        validated = validate_response(answer, query=query, agent="Patient Records")
        audit.log(
            agent="Patient Records", query=query, user_id=req.user_id, role=role,
            sql=result["sql"], row_count=len(result["rows"]), confidence=decision.confidence,
            safety_flags=validated.flags, escalated=validated.escalated,
            status="blocked_sql" if result.get("validation_error") else "ok",
            detail=result.get("validation_error"),
        )
        warnings = list(result.get("warnings") or [])
        if result.get("validation_error"):
            warnings.append(f"Generated SQL was rejected and a safe fallback query was used ({result['validation_error']}).")
        return ChatResponse(
            content=validated.text,
            agent="Patient Records",
            elapsed=time.time() - t0,
            recovery_tips=tips_for_query,
            sql=result["sql"],
            rows=result["rows"],
            confidence=decision.confidence,
            routing_method=decision.method,
            safety_flags=validated.flags,
            escalated=validated.escalated,
            access_role=role,
            warnings=warnings,
        )

    if agent == "RAG_AGENT":
        with _rag_lock:
            rag.llm = llm
            answer, sources, eval_metrics = rag.answer(query)
        validated = validate_response(answer, query=query, agent="Hospital Policies")
        audit.log(
            agent="Hospital Policies", query=query, user_id=req.user_id, role=role,
            row_count=len(sources), confidence=decision.confidence,
            safety_flags=validated.flags + eval_metrics.get("flags", []),
            escalated=validated.escalated, status="ok",
        )
        return ChatResponse(
            content=validated.text,
            agent="Hospital Policies",
            elapsed=time.time() - t0,
            recovery_tips=tips_for_query,
            sources=sources,
            confidence=decision.confidence,
            routing_method=decision.method,
            evaluation=eval_metrics,
            safety_flags=validated.flags,
            escalated=validated.escalated,
            access_role=role,
        )

    # GENERAL
    if llm.available:
        answer = llm.chat(
            [
                {"role": "system", "content": GENERAL_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            0.2,
            650,
        )
    else:
        answer = local_health_fallback(query) or (
            "I can help with general health information, patient-record questions, and hospital policies. "
            "For a general health question, please describe your symptoms or concern and I will provide general guidance."
        )

    validated = validate_response(answer, query=query, agent="Healthcare Assistant")
    audit.log(
        agent="Healthcare Assistant", query=query, user_id=req.user_id, role=role,
        confidence=decision.confidence, safety_flags=validated.flags,
        escalated=validated.escalated, status="ok",
    )

    return ChatResponse(
        content=validated.text,
        agent="Healthcare Assistant",
        elapsed=time.time() - t0,
        recovery_tips=tips_for_query,
        confidence=decision.confidence,
        routing_method=decision.method,
        safety_flags=validated.flags,
        escalated=validated.escalated,
        access_role=role,
    )
