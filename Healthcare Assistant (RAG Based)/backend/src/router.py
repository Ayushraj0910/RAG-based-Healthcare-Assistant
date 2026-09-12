from .evaluation import RouteDecision

# Confidence below this triggers a fallback (LLM classification if
# available, otherwise a clarification response instead of guessing).
LOW_CONFIDENCE_THRESHOLD = 0.55


class Orchestrator:
    POLICY_TERMS = ['policy', 'policies', 'guideline', 'guidelines', 'hipaa', 'privacy',
                    'disclosure', 'consent', 'fmla', 'leave', 'billing policy',
                    'financial assistance', 'payment plan', 'bed allocation',
                    'emergency admission policy', 'medication safety']
    DATA_TERMS = ['patient', 'patients', 'record', 'records', 'doctor', 'hospital', 'room',
                  'admitted', 'admission', 'discharge', 'medication', 'diagnosed',
                  'diagnosis', 'blood type', 'test result', 'billing amount', 'insurance',
                  'how many', 'count', 'list']

    def __init__(self, llm=None):
        self.llm = llm

    def _keyword_match(self, x: str):
        """Return (agent, matched_terms) for keyword-based routing, scored by
        how many distinct signal terms fired (more matches => higher
        confidence) rather than a flat guess."""
        policy_hits = [t for t in self.POLICY_TERMS if t in x]
        data_hits = [t for t in self.DATA_TERMS if t in x]
        if policy_hits and not data_hits:
            return 'RAG_AGENT', policy_hits
        if data_hits and not policy_hits:
            return 'SQL_AGENT', data_hits
        if policy_hits and data_hits:
            # Both fired: prefer whichever has more/stronger signal, but
            # this ambiguity itself lowers confidence (handled by caller).
            if len(policy_hits) >= len(data_hits):
                return 'RAG_AGENT', policy_hits
            return 'SQL_AGENT', data_hits
        return None, []

    def _confidence_from_matches(self, matched_terms, ambiguous: bool) -> float:
        if not matched_terms:
            return 0.0
        # Diminishing returns: 1 term -> 0.6, 2 -> 0.75, 3+ -> 0.9
        base = min(0.6 + 0.15 * (len(matched_terms) - 1), 0.9)
        if ambiguous:
            base -= 0.25
        return max(0.0, round(base, 3))

    def classify(self, q: str) -> str:
        """Backward-compatible simple interface: returns just the agent
        label. Prefer `route()` for confidence/fallback details."""
        return self.route(q).agent

    def route(self, q: str) -> RouteDecision:
        x = q.lower()
        policy_hits = [t for t in self.POLICY_TERMS if t in x]
        data_hits = [t for t in self.DATA_TERMS if t in x]
        ambiguous = bool(policy_hits) and bool(data_hits)

        agent, matched = self._keyword_match(x)
        if agent:
            confidence = self._confidence_from_matches(matched, ambiguous)
            if confidence >= LOW_CONFIDENCE_THRESHOLD:
                return RouteDecision(agent=agent, confidence=confidence, method="keyword",
                                      matched_terms=matched)
            # Low-confidence keyword hit: try to confirm/override with the
            # LLM classifier if one is available; otherwise fall through to
            # keeping the keyword guess but flagged with its low confidence.
            fallback = self._llm_classify(q)
            if fallback:
                return fallback
            return RouteDecision(agent=agent, confidence=confidence, method="keyword",
                                  matched_terms=matched)

        # No keyword signal at all: try the LLM classifier, then fall back
        # to GENERAL with an explicit low-confidence, no-match label.
        fallback = self._llm_classify(q)
        if fallback:
            return fallback
        return RouteDecision(agent="GENERAL", confidence=0.3, method="default", matched_terms=[])

    def _llm_classify(self, q: str):
        if not (self.llm and self.llm.available):
            return None
        p = ('Classify as SQL_AGENT for patient database questions, RAG_AGENT for hospital '
             'policy questions, GENERAL otherwise. Return only the label.')
        try:
            out = self.llm.chat([{'role': 'system', 'content': p}, {'role': 'user', 'content': q}], 0, 20)
        except Exception:
            return None
        out = (out or '').strip()
        if out in {'SQL_AGENT', 'RAG_AGENT', 'GENERAL'}:
            # LLM classification without keyword corroboration gets a
            # moderate (not maximal) confidence score.
            return RouteDecision(agent=out, confidence=0.65, method="llm", matched_terms=[])
        return None
