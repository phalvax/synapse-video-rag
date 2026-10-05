"""L4 Agent : question → passages → réponse prouvée, ou abstention explicite.

Ordre des garde-fous (CLAUDE.md section 7), du moins cher au plus cher :
1. seuil d'abstention sur le score du reranker → AUCUN appel LLM ;
2. sources encadrées en <source> (données, pas instructions) ;
3. sortie JSON validée par Pydantic (une nouvelle tentative, puis abstention) ;
4. chaque citation vérifiée mot pour mot dans son extrait ;
5. sans citation vérifiée → abstention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from kb.adapters.base import LLM
from kb.adapters.factory import build_llm
from kb.agent.guardrails import (
    answer_numbers,
    enforce_verified,
    number_window,
    parse_output,
    verify_citations,
    wrap_sources,
)
from kb.agent.prompts import ANSWER_SCHEMA, SYSTEM, USER_TEMPLATE
from kb.agent.query import translate_query
from kb.config import Settings
from kb.eval.metrics import cost_usd
from kb.index.search import Hit, Searcher, SearchResult
from kb.schemas import Answer, Citation

MODES = ("strict", "synthese")
MAX_SEARCH_LANGUAGES = 3  # au-delà, le coût (traduction + recherche par langue) l'emporte


class _LlmCitation(BaseModel):
    source_id: str
    quote: str


class _LlmAnswer(BaseModel):
    """Ce que le LLM est autorisé à renvoyer (il ne décide JAMAIS de `verified`)."""

    answer: str | None = None
    not_found: bool = False
    citations: list[_LlmCitation] = Field(default_factory=list)


@dataclass
class AgentResult:
    answer: Answer
    mode: str
    hits: list[Hit] = field(default_factory=list)  # pistes affichées même en cas d'abstention
    retrieval_score: float | None = None
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: dict[str, float] = field(default_factory=dict)
    note: str = ""
    search_query: str = ""  # question réellement envoyée à la recherche (traduite ou non)


class Agent:
    def __init__(self, settings: Settings, searcher: Searcher, llm: LLM | None = None,
                 missions: dict[str, list[str]] | None = None,
                 languages: set[str] | None = None) -> None:
        self.settings = settings
        self.searcher = searcher
        self._llm = llm
        self.missions = missions or {}  # mission → video_ids (Video.mission)
        self.languages = languages or set()  # langues du corpus (vidéos ET documents)

    @classmethod
    def load(cls, settings: Settings, llm: LLM | None = None) -> Agent:
        return cls(settings, Searcher.load(settings, with_reranker=True), llm,
                   missions=load_missions(settings), languages=corpus_languages(settings))

    @property
    def llm(self) -> LLM:
        if self._llm is None:
            self._llm = build_llm(self.settings)
        return self._llm

    def ask(self, question: str, mode: str = "synthese",
            filters: dict | None = None) -> AgentResult:
        if mode not in MODES:
            raise ValueError(f"mode inconnu : {mode} (attendu : {MODES})")
        r = self.settings.retrieval
        t0 = time.perf_counter()
        usage = getattr(self.llm, "usage", None) if r.query_language or mode != "strict" else None
        before = (usage.input_tokens, usage.output_tokens) if usage is not None else (0, 0)
        # La recherche voit la question traduite dans CHAQUE langue du corpus ; le LLM, l'originale.
        # Pourquoi : le reranker note mal une question dans une autre langue que le passage
        # (mesuré le 24/09). Corpus mixte (réunions EN + comptes rendus FR) → une recherche par
        # langue, et chaque passage garde son meilleur score.
        query, calls = question, 0
        targets = [r.query_language] if r.query_language else []
        targets += sorted(lang for lang in self.languages if lang not in targets)
        queries: list[str] = []
        for lang in targets[:MAX_SEARCH_LANGUAGES]:
            q = translate_query(self.llm, question, lang)
            calls += 1
            if q not in queries:
                queries.append(q)
        if queries:
            query = queries[0]
        filters, scoped = scope_to_mission(question, filters, self.missions)
        t_search = time.perf_counter()
        found = self.searcher.search(query, mode="hybrid_rerank", k=r.rerank_top_n,
                                     filters=filters)
        for extra in queries[1:]:
            found = merge_results(found, self.searcher.search(
                extra, mode="hybrid_rerank", k=r.rerank_top_n, filters=filters),
                r.rerank_top_n, r.abstain_threshold)
        res = AgentResult(answer=Answer(not_found=True), mode=mode, hits=found.hits,
                          retrieval_score=found.best_score, llm_calls=calls, search_query=query,
                          latency_ms={"translate": round(1000 * (t_search - t0)),
                                      "search": round(1000 * (time.perf_counter() - t_search))})
        self._count_usage(res, usage, before)
        scope_note = f"recherche limitée à la mission {scoped} · " if scoped else ""

        # Garde-fou 1 : rien d'assez pertinent → on ne fait même pas parler le LLM.
        if found.abstain or not found.hits:
            res.note = scope_note + (
                f"abstention avant génération : score {found.best_score:.2f} < seuil "
                f"{r.abstain_threshold}" if found.best_score is not None
                else "aucun passage trouvé")
            res.latency_ms["total"] = round(1000 * (time.perf_counter() - t0))
            return res

        sources = found.hits[: r.answer_sources]
        if mode == "strict":  # Mode strict : extraits vérifiés, zéro génération
            res.answer = _strict_answer(sources, found.best_score)
            res.note = scope_note + "mode strict : extraits seuls, aucun texte généré"
            res.latency_ms["total"] = round(1000 * (time.perf_counter() - t0))
            return res

        t1 = time.perf_counter()
        answer, calls, note = self._generate(question, sources)
        res.llm_calls, res.note = res.llm_calls + calls, note
        self._count_usage(res, usage, before)
        res.latency_ms["llm"] = round(1000 * (time.perf_counter() - t1))
        res.latency_ms["total"] = round(1000 * (time.perf_counter() - t0))

        # Garde-fous 4 et 5 : citations vérifiées dans le texte source, sinon abstention.
        chunks = {h.chunk.chunk_id: h.chunk for h in sources}
        kept = enforce_verified(verify_citations(answer, chunks))
        # Une citation rattachée à une autre source (mauvaise étiquette du LLM) prend la
        # seconde de SA source : le clic doit ouvrir le moment où la phrase est dite.
        moment_of = {h.chunk.chunk_id: h.moment_s for h in sources}
        chunk_of = {h.chunk.chunk_id: h.chunk for h in sources}
        locate = getattr(self.searcher, "locate_quote", None)

        def when(c: Citation) -> float:
            """Là où la citation est dite / affichée ; à défaut, le moment le plus proche."""
            exact = locate(chunk_of[c.chunk_id], c.quote) if locate and c.chunk_id in chunk_of \
                else None
            return exact if exact is not None else moment_of.get(c.chunk_id, c.start_s)

        page_of = {h.chunk.chunk_id: h.chunk.page for h in sources}
        nature_of = {h.chunk.chunk_id: h.chunk.modality for h in sources}
        kept = kept.model_copy(update={"citations": [
            c.model_copy(update={"start_s": when(c),
                                 "page": page_of.get(c.chunk_id),
                                 "modality": nature_of.get(c.chunk_id)})
            for c in kept.citations]})
        if kept.not_found and not answer.not_found:
            res.note = "abstention : aucune citation retrouvée mot pour mot dans les sources"
        elif not kept.not_found:
            kept, missing = _back_numbers(kept, sources, moment_of)
            if missing:  # un chiffre que personne n'a prononcé : on ne l'affiche pas
                kept = Answer(not_found=True)
                res.note = (f"abstention : {', '.join(sorted(missing))} (dans la réponse) "
                            "n'apparaît dans aucune source")
        res.answer = kept.model_copy(
            update={"confidence": 0.0 if kept.not_found else round(found.best_score or 0.0, 3)}
        )
        if only_generated_evidence(res.answer):
            res.note = VISUAL_ONLY_NOTE  # vu le 27/09 : réponse fausse appuyée sur une description
        res.note = scope_note + res.note
        return res

    def _count_usage(self, res: AgentResult, usage, before: tuple[int, int]) -> None:
        """Tokens et coût de CETTE question (l'usage de l'adapter est cumulé sur sa vie)."""
        if usage is None:
            return
        res.input_tokens = usage.input_tokens - before[0]
        res.output_tokens = usage.output_tokens - before[1]
        res.cost_usd = cost_usd(res.input_tokens, res.output_tokens,
                                self.settings.llm.input_per_m, self.settings.llm.output_per_m)

    def _generate(self, question: str, sources: list[Hit]) -> tuple[Answer, int, str]:
        """Appelle le LLM, valide le JSON, retente une fois, puis s'abstient."""
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER_TEMPLATE.format(
                sources=wrap_sources([h.chunk for h in sources]), question=question)},
        ]
        last_error = ""
        for attempt in (1, 2):
            raw = self.llm.complete(messages, json_schema=ANSWER_SCHEMA)
            try:
                return _to_answer(parse_output(raw, _LlmAnswer), sources), attempt, ""
            except ValueError as exc:
                last_error = str(exc)[:200]
                messages = messages + [
                    {"role": "assistant", "content": raw[:2000]},
                    {"role": "user", "content": "Ta réponse n'était pas du JSON valide au format "
                                                "demandé. Renvoie UNIQUEMENT le JSON."},
                ]
        return Answer(not_found=True), 2, f"abstention : JSON invalide ({last_error})"


VISUAL_ONLY_NOTE = ("réponse appuyée uniquement sur une description d'image GÉNÉRÉE par l'IA : "
                    "à vérifier sur l'image, ce n'est pas une preuve")


def only_generated_evidence(answer: Answer) -> bool:
    """Vrai si la réponse n'a pour preuves QUE des descriptions générées d'images : les
    citations existent bien dans la source, mais cette source est elle-même du texte généré.
    (27/09 : « la puce est alimentée par l'émetteur infrarouge », faux, passait sinon.)"""
    return (not answer.not_found and bool(answer.citations)
            and all(c.modality == "visual" for c in answer.citations))


def corpus_languages(settings: Settings) -> set[str]:
    """Langues présentes dans le corpus (champ `language` des vidéos et documents)."""
    from kb.jsonl import read_jsonl
    from kb.schemas import Video

    if not settings.videos_file.exists():
        return set()
    return {v.language for v in read_jsonl(settings.videos_file, Video) if v.language}


def merge_results(a: SearchResult, b: SearchResult, k: int, threshold: float) -> SearchResult:
    """Fusion de deux recherches : un passage garde son MEILLEUR score de rerank."""
    best: dict[str, Hit] = {}
    for h in [*a.hits, *b.hits]:
        cur = best.get(h.chunk.chunk_id)
        if cur is None or (h.rerank_score or 0.0) > (cur.rerank_score or 0.0):
            best[h.chunk.chunk_id] = h
    hits = sorted(best.values(), key=lambda h: h.rerank_score or 0.0, reverse=True)[:k]
    score = hits[0].rerank_score if hits else None
    return SearchResult(hits=hits, best_score=score, abstain=score is None or score < threshold,
                        timings_ms={"total": a.timings_ms.get("total", 0.0)
                                    + b.timings_ms.get("total", 0.0)})


def load_missions(settings: Settings) -> dict[str, list[str]]:
    """mission → video_ids, depuis videos.jsonl (champ rempli par `kb.cli recap`)."""
    from kb.jsonl import read_jsonl
    from kb.schemas import Video

    if not settings.videos_file.exists():
        return {}
    out: dict[str, list[str]] = {}
    for v in read_jsonl(settings.videos_file, Video):
        if v.mission:
            out.setdefault(v.mission, []).append(v.video_id)
    return out


def scope_to_mission(question: str, filters: dict | None,
                     missions: dict[str, list[str]]) -> tuple[dict | None, str | None]:
    """« l'équipe ES2004 » → recherche limitée aux réunions de ES2004 (le nom de la mission
    n'est jamais prononcé dans les réunions : sans ce filtre, l'autre équipe peut sortir).
    Un filtre vidéo déjà choisi par l'utilisateur est prioritaire."""
    from kb.agent.router import named_missions

    if filters and "video_id" in filters:
        return filters, None
    named = named_missions(question, list(missions))
    if len(named) != 1:
        return filters, None
    return {**(filters or {}), "video_id": missions[named[0]]}, named[0]


def _back_numbers(answer: Answer, sources: list[Hit],
                  moment_of: dict[str, float]) -> tuple[Answer, set[str]]:
    """Chaque nombre de la réponse doit figurer dans une citation vérifiée.

    Vu le 25/09 : « vendue à 25 euros » appuyée par une citation vraie mais sans « 25 ».
    Si le nombre est dans une source fournie, on ajoute l'extrait EXACT qui le contient
    (preuve du chiffre) ; sinon on renvoie les nombres sans preuve (→ abstention).
    """
    cited = set().union(*(answer_numbers(c.quote) for c in answer.citations))
    citations, missing = list(answer.citations), set()
    for n in sorted(answer_numbers(answer.answer) - cited):
        if n in cited:  # déjà prouvé par un extrait ajouté pour un autre nombre (« 12,50 »)
            continue
        for h in sources:
            window = number_window(h.chunk.text, n)
            if window:
                citations.append(Citation(chunk_id=h.chunk.chunk_id, video_id=h.chunk.video_id,
                                          page=h.chunk.page, modality=h.chunk.modality,
                                          start_s=moment_of.get(h.chunk.chunk_id, h.moment_s),
                                          quote=window, verified=True))
                cited |= answer_numbers(window)
                break
        else:
            missing.add(n)
    return answer.model_copy(update={"citations": citations}), missing


def _strict_answer(sources: list[Hit], score: float | None) -> Answer:
    """Mode strict : les extraits tels quels — rien n'est rédigé, donc rien n'est inventé."""
    citations = [
        Citation(chunk_id=h.chunk.chunk_id, video_id=h.chunk.video_id, start_s=h.moment_s,
                 page=h.chunk.page, modality=h.chunk.modality,
                 quote=h.moment_text.strip(), verified=True)
        for h in sources
    ]
    return Answer(answer="[mode strict] " + " … ".join(c.quote for c in citations),
                  confidence=round(score or 0.0, 3), citations=citations)


def _to_answer(draft: _LlmAnswer, sources: list[Hit]) -> Answer:
    """Traduit les `source_id` (S1, S2…) en chunk_id, video_id et timestamp cliquable."""
    by_id: dict[str, Hit] = {f"S{i}": h for i, h in enumerate(sources, start=1)}
    if draft.not_found or not draft.answer:
        return Answer(not_found=True)
    citations = [
        Citation(chunk_id=by_id[c.source_id].chunk.chunk_id,
                 page=by_id[c.source_id].chunk.page,
                 video_id=by_id[c.source_id].chunk.video_id,
                 start_s=by_id[c.source_id].moment_s,  # seconde à ouvrir dans la vidéo
                 quote=c.quote)
        for c in draft.citations
        if c.source_id in by_id
    ]
    return Answer(answer=draft.answer, citations=citations)
