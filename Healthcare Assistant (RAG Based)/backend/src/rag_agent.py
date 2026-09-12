import re
from pathlib import Path

import numpy as np

from .config import POLICY_DIR, EMBEDDING_MODEL, TOP_K
from .evaluation import evaluate_rag_answer


class RAGAgent:
    """
    Retrieval-augmented policy Q&A agent.

    Each retrieved chunk carries page-level evidence (source file, section
    heading, and the exact line range within that file it came from) so a
    reader can jump straight to the passage a claim is based on, and the
    generated answer is annotated with numbered inline citation markers
    ([1], [2], ...) that map 1:1 onto the `sources` list returned alongside
    it. A measurable groundedness/relevance score (see evaluation.py) is
    also computed for every answer.
    """

    def __init__(self, llm=None):
        self.llm = llm
        self.chunks = []
        self._build()

    def _build(self):
        for path in sorted(Path(POLICY_DIR).glob('*.md')):
            text = path.read_text(encoding='utf-8')
            lines = text.splitlines()
            title = lines[0].lstrip('# ').strip()

            # Track each paragraph's line range and nearest preceding
            # section heading (## ...) for page/section-level evidence.
            # Paragraphs may open with a heading line immediately followed
            # by body text on the next line with no blank line between them
            # (as in this policy corpus), so headings are split out of the
            # paragraph before deciding whether the remainder is a content
            # chunk.
            current_section = title
            line_no = 1
            for para in text.split('\n\n'):
                para_line_list = para.split('\n')
                para_lines = len(para_line_list)
                start_line = line_no
                end_line = line_no + para_lines - 1
                line_no = end_line + 2  # +1 blank separator, +1 to move past it

                body_lines = para_line_list
                heading_match = re.match(r'^#{1,3}\s+(.*)', para_line_list[0].strip())
                if heading_match:
                    current_section = heading_match.group(1).strip()
                    body_lines = para_line_list[1:]
                    start_line += 1  # body starts after the heading line

                stripped = '\n'.join(body_lines).strip()
                if len(stripped) > 40:
                    self.chunks.append({
                        'source': path.name,
                        'title': title,
                        'section': current_section,
                        'chunk': len(self.chunks),
                        'text': stripped,
                        'line_start': start_line,
                        'line_end': end_line,
                    })

        texts = [c['text'] for c in self.chunks]
        try:
            from sentence_transformers import SentenceTransformer
            import faiss
            self.embedder = SentenceTransformer(EMBEDDING_MODEL)
            v = np.asarray(self.embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False), dtype='float32')
            self.index = faiss.IndexFlatIP(v.shape[1])
            self.index.add(v)
            self.mode = 'FAISS + SentenceTransformers'
        except Exception:
            from sklearn.feature_extraction.text import TfidfVectorizer
            import faiss
            self.vectorizer = TfidfVectorizer(stop_words='english', ngram_range=(1, 2))
            v = self.vectorizer.fit_transform(texts).toarray().astype('float32')
            v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-8
            self.index = faiss.IndexFlatIP(v.shape[1])
            self.index.add(v)
            self.mode = 'FAISS + TF-IDF fallback'

    def retrieve(self, q, k=TOP_K):
        if self.mode.startswith('FAISS + Sentence'):
            v = np.asarray(self.embedder.encode([q], normalize_embeddings=True), dtype='float32')
        else:
            v = self.vectorizer.transform([q]).toarray().astype('float32')
            v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-8
        scores, ids = self.index.search(v, min(k, len(self.chunks)))
        return [(self.chunks[int(i)], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]

    def answer(self, q):
        got = self.retrieve(q)
        context = '\n\n---\n\n'.join(
            f"[{i+1}] Source: {c['title']} \u2013 Section: {c['section']} (lines {c['line_start']}-{c['line_end']})\n{c['text']}"
            for i, (c, s) in enumerate(got)
        )

        if self.llm and self.llm.available:
            sys = (
                'Answer ONLY from the supplied synthetic hospital policy context. If the '
                'context does not cover the question, say so plainly rather than guessing. '
                'Every factual claim must end with a bracketed citation number like [1] or '
                '[2] matching the numbered source it came from. Do not invent policy or '
                'citations that are not in the provided context.'
            )
            ans = self.llm.chat(
                [{'role': 'system', 'content': sys},
                 {'role': 'user', 'content': f'Context:\n{context}\n\nQuestion: {q}'}],
                .1, 800,
            )
            if ans and not re.search(r'\[\d+\]', ans) and got:
                # Model forgot citations - append a plain reference line so
                # the answer is still traceable to its evidence.
                ans = ans.rstrip() + "\n\n(See sources " + ", ".join(f"[{i+1}]" for i in range(len(got))) + " below.)"
        else:
            ans = 'Retrieved policy context (configure GROQ_API_KEY for generated answers):\n\n' + context

        sources = [
            {
                'citation': i + 1,
                'title': c['title'],
                'section': c['section'],
                'source': c['source'],
                'line_range': f"{c['line_start']}-{c['line_end']}",
                'score': round(s, 3),
                'text': c['text'],
            }
            for i, (c, s) in enumerate(got)
        ]

        eval_result = evaluate_rag_answer(q, ans or '', got)

        return ans, sources, eval_result.as_dict()
