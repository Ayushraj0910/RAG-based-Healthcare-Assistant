"""
Healthcare-specific safety layer.

Two directions of checking:

1. INPUT SIDE  - `screen_query` looks at the user's question for red-flag
                 emergency language (chest pain, suicidal ideation,
                 anaphylaxis, stroke symptoms, etc.) and, when found,
                 produces an escalation notice that is prepended to (or
                 replaces) whatever the downstream agent would have said.
                 This runs before routing so an emergency is never answered
                 with a slow RAG/SQL detour.

2. OUTPUT SIDE - `validate_response` inspects the *generated* answer for
                 unsafe patterns before it is returned to the user:
                 specific drug-dosage instructions, definitive diagnostic
                 claims ("you have X"), or a missing safety disclaimer on
                 medical-advice-shaped answers. Violations either get the
                 answer rewritten with a safety note appended or, for the
                 worst cases, replaced entirely with a safe fallback.

Both stages return structured flags so the caller can audit-log them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# ---------------------------------------------------------------------------
# Emergency / escalation detection (input side)
# ---------------------------------------------------------------------------
EMERGENCY_PATTERNS = [
    (r"\bchest pain\b", "possible cardiac emergency"),
    (r"\b(can't|cannot|difficulty) breath", "respiratory distress"),
    (r"\bshortness of breath\b", "respiratory distress"),
    (r"\bsuicid", "suicidal ideation"),
    (r"\bkill myself\b|\bend(ing)? (it all|my life)\b|\bwant to die\b|\bdon'?t want to (be alive|live)\b", "suicidal ideation"),
    (r"\bno reason to live\b|\bbetter off dead\b|\bcan'?t go on\b", "suicidal ideation"),
    (r"\bsevere bleeding\b|\bwon'?t stop bleeding\b", "uncontrolled hemorrhage"),
    (r"\bstroke\b|\bface drooping\b|\bslurred speech\b|\bnumbness on one side\b", "possible stroke"),
    (r"\banaphyla|\ballergic reaction.*(swelling|throat)\b|\bthroat.*swelling\b", "possible anaphylaxis"),
    (r"\boverdose|\btoo many pills\b|\bpoisoned\b|\bpoisoning\b", "possible overdose/poisoning"),
    (r"\bunconscious\b|\bnot breathing\b|\bno pulse\b|\bunresponsive\b", "unresponsive patient"),
    (r"\bseizure\b", "active seizure"),
    (r"\bsevere allergic\b", "possible severe allergic reaction"),
    (r"\bthoughts of harming\b|\bhurt (myself|someone)\b", "risk of harm"),
]

EMERGENCY_NOTICE = (
    "\u26A0\uFE0F This may describe a medical emergency ({reasons}). "
    "If this is happening now, call your local emergency number (e.g. 911 in the US) "
    "or go to the nearest emergency department immediately. "
    "If you are in crisis or thinking about suicide, you can also contact the 988 "
    "Suicide & Crisis Lifeline (call or text 988 in the US) for immediate support.\n\n"
)


@dataclass
class ScreenResult:
    is_emergency: bool
    reasons: List[str] = field(default_factory=list)
    notice: str = ""


def screen_query(query: str) -> ScreenResult:
    q = query.lower()
    reasons = []
    for pattern, label in EMERGENCY_PATTERNS:
        if re.search(pattern, q):
            reasons.append(label)
    if not reasons:
        return ScreenResult(is_emergency=False)
    notice = EMERGENCY_NOTICE.format(reasons=", ".join(dict.fromkeys(reasons)))
    return ScreenResult(is_emergency=True, reasons=reasons, notice=notice)


# ---------------------------------------------------------------------------
# Response validation (output side)
# ---------------------------------------------------------------------------
DOSAGE_PATTERN = re.compile(
    r"\btake\s+\d+(\.\d+)?\s*(mg|mcg|milligrams|micrograms|ml|milliliters|tablets|pills)\b",
    re.IGNORECASE,
)
DEFINITIVE_DIAGNOSIS_PATTERN = re.compile(
    r"\byou (have|are suffering from|are diagnosed with)\b|\byou definitely have\b",
    re.IGNORECASE,
)
PRESCRIPTIVE_PATTERN = re.compile(
    r"\bi (prescribe|am prescribing)\b|\byou should stop taking\b|\bstop your medication\b",
    re.IGNORECASE,
)

SAFETY_DISCLAIMER_MARKERS = [
    "not a substitute", "consult", "healthcare professional", "seek medical",
    "medical advice", "clinician", "doctor", "emergency",
]

MEDICAL_ADVICE_SHAPED_MARKERS = [
    "recovery", "symptom", "treat", "medication", "dose", "dosage", "diagnos",
    "illness", "condition", "fever", "cough", "pain", "infection",
]

STANDARD_DISCLAIMER = (
    "\n\n_This is general health information, not medical advice or a diagnosis. "
    "Please consult a healthcare professional for guidance specific to your situation, "
    "and seek urgent care for severe or worsening symptoms._"
)


@dataclass
class ValidationResult:
    text: str
    flags: List[str] = field(default_factory=list)
    escalated: bool = False
    blocked: bool = False


def validate_response(answer: str, *, query: str = "", agent: str = "") -> ValidationResult:
    """
    Inspect a generated answer for unsafe healthcare-response patterns and
    return a (possibly amended) safe version along with flags describing
    what was found/changed.
    """
    if not answer:
        return ValidationResult(text=answer or "", flags=[])

    flags: List[str] = []
    text = answer
    blocked = False

    if DEFINITIVE_DIAGNOSIS_PATTERN.search(text):
        flags.append("definitive_diagnosis_claim")
        text = DEFINITIVE_DIAGNOSIS_PATTERN.sub("this may be consistent with", text)

    if PRESCRIPTIVE_PATTERN.search(text):
        flags.append("prescriptive_instruction_blocked")
        blocked = True
        text = (
            "I can't provide prescriptive medical instructions (such as prescribing or "
            "telling you to stop a medication). Please discuss this with a licensed "
            "healthcare professional. " + text
        )

    if DOSAGE_PATTERN.search(text):
        flags.append("specific_dosage_removed")
        text = DOSAGE_PATTERN.sub(
            "follow the dosing instructions on the label or from your pharmacist/clinician",
            text,
        )

    low = text.lower()
    looks_like_medical_advice = any(m in low for m in MEDICAL_ADVICE_SHAPED_MARKERS)
    has_disclaimer = any(m in low for m in SAFETY_DISCLAIMER_MARKERS)
    if looks_like_medical_advice and not has_disclaimer:
        flags.append("disclaimer_added")
        text = text.rstrip() + STANDARD_DISCLAIMER

    escalation = screen_query(query) if query else ScreenResult(is_emergency=False)
    if escalation.is_emergency:
        flags.append("emergency_escalation")
        text = escalation.notice + text

    return ValidationResult(text=text, flags=flags, escalated=escalation.is_emergency, blocked=blocked)
