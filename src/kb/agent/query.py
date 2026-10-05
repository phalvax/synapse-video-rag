"""Réécriture de la question pour la RECHERCHE seulement (la réponse garde la question d'origine).

Pourquoi (mesuré le 24/09, golden set v0, rapport search_free_2026-09-17) : le reranker note mal
une question française face à un transcript anglais — score médian 0,41 en FR contre 0,90 en EN,
et 4 questions FR sur 16 abstenues à tort sous le seuil ; BM25 ne trouve aucun mot commun.
Traduire la question dans la langue du corpus avant la recherche règle les deux.
"""

from __future__ import annotations

from kb.adapters.base import LLM

LANG_NAMES = {"en": "English", "fr": "French", "de": "German", "es": "Spanish", "it": "Italian"}

PROMPT = """Translate the search question below into {lang}.
Keep names, numbers, acronyms and technical terms exactly as written.
If it is already in {lang}, return it unchanged.
Output ONLY the translated question, nothing else.

Question: {question}"""


def translate_query(llm: LLM, question: str, lang: str) -> str:
    """Question traduite dans `lang` ; la question d'origine si la sortie est inexploitable."""
    raw = llm.complete(
        [{"role": "user", "content": PROMPT.format(lang=LANG_NAMES.get(lang, lang),
                                                    question=question)}],
        temperature=0,
    )
    text = (raw or "").strip()
    if text.lower().startswith("question:"):
        text = text[len("question:"):]
    text = text.strip().strip('"«» ').strip()
    # Garde-fou : une « traduction » vide, multi-lignes ou 3× plus longue n'est pas une question.
    if not text or "\n" in text or len(text) > 3 * len(question) + 20:
        return question
    return text
