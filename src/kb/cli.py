"""Ligne de commande de l'équipe.

    python -m kb.cli check [--profile dataiku] [--no-call]   # config + connexions
    python -m kb.cli ingest data/videos [--model small] [--force]
    python -m kb.cli index                                  # chunks + embeddings + Chroma
    python -m kb.cli structure [video_id ...] [--force]     # transcript -> fiches REX (kb.sqlite)
    python -m kb.cli fiches "recherche" [--client X] [--tech Y] [--video-id Z] [-k 10]
    python -m kb.cli recap ES2002 ami_es2002a ami_es2002b … # point de situation d'une mission
    python -m kb.cli search "question" [--mode hybrid_rerank] [-k 5]
    python -m kb.cli ask "question" [--strict] [--json]     # réponse prouvée ou « non trouvé »
    python -m kb.cli eval-asr --models small large-v3-turbo   # WER + vitesse (réf. TED)
    python -m kb.cli eval-search                            # golden set : Hit@k, MRR, moment…
    python -m kb.cli eval-agent [--mode strict]              # abstention, citations, coût
    python -m kb.cli eval [--mode strict]                    # recherche + agent + synthèse
    python -m kb.cli compare-tiers [--profiles free dataiku] # frontière coût-qualité
                                                             # (agrège des rapports déjà générés)
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from kb.config import ROOT, load_settings


def _use_utf8_console() -> None:
    """PowerShell/cmd utilisent cp1252 par défaut : ⚠, «, » y font planter print()."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def _use_system_certificates() -> None:
    """Réseaux qui interceptent HTTPS (antivirus, proxy) : utiliser les certificats de Windows."""
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def _check(profile: str | None, call: bool) -> int:
    from kb.adapters import build_embedder, build_llm

    s = load_settings(profile)
    print(f"Profil      : {s.profile}")
    print(f"LLM         : {s.llm.model}  @ {s.llm.base_url}")
    print(f"Tarif LLM   : {s.llm.input_per_m} / {s.llm.output_per_m} $ par M tokens "
          f"(entrée / sortie) · temperature={s.llm.temperature}")
    print(f"Embeddings  : {s.embedding.model}  @ {s.embedding.base_url}")
    print(f"Transcription: {s.transcription.engine} {s.transcription.model_size} "
          f"({s.transcription.device})")
    if not call:
        return 0

    ok = True
    try:
        t0 = time.perf_counter()
        out = build_llm(s).complete([{"role": "user", "content": "Réponds uniquement : OK"}])
        print(f"[LLM] OK en {time.perf_counter() - t0:.1f}s → {out.strip()[:60]!r}")
    except Exception as exc:  # noqa: BLE001 — diagnostic lisible pour l'équipe
        ok = False
        print(f"[LLM] ÉCHEC : {type(exc).__name__}: {exc}")
    try:
        t0 = time.perf_counter()
        vec = build_embedder(s).embed(["test de connexion"])[0]
        print(f"[Embeddings] OK en {time.perf_counter() - t0:.1f}s → dimension {len(vec)}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"[Embeddings] ÉCHEC : {type(exc).__name__}: {exc}")
    return 0 if ok else 1


def _ingest(args: argparse.Namespace) -> int:
    from kb.adapters.factory import build_transcriber
    from kb.ingest.pipeline import ingest_folder

    s = load_settings(args.profile)
    if args.data_dir:
        s.data_dir = Path(args.data_dir)
    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"Dossier introuvable : {folder}")
        return 1
    model = args.model or s.transcription.model_size
    ingest_folder(folder, build_transcriber(s, model), s, model_name=model, force=args.force)
    return 0


def _index(args: argparse.Namespace) -> int:
    from kb.index.build import build_index

    build_index(load_settings(args.profile))
    return 0


def _structure(args: argparse.Namespace) -> int:
    from kb.adapters.factory import build_llm
    from kb.jsonl import read_jsonl
    from kb.schemas import Segment, Video
    from kb.structure.extract import extract_fiches
    from kb.structure.store import query_fiches, save_fiches

    s = load_settings(args.profile)
    videos = read_jsonl(s.videos_file, Video)
    if args.video_ids:
        wanted = set(args.video_ids)
        videos = [v for v in videos if v.video_id in wanted]
    llm = build_llm(s)
    for video in videos:
        if not args.force and query_fiches(s.kb_db_file, video_id=video.video_id, limit=1):
            print(f"= {video.video_id} déjà structuré (--force pour refaire)")
            continue
        segments = read_jsonl(s.transcripts_dir / f"{video.video_id}.jsonl", Segment)
        fiches = extract_fiches(video, segments, llm)
        save_fiches(s.kb_db_file, video.video_id, fiches)
        print(f"→ {video.video_id} : {len(fiches)} fiche(s)")
    return 0


def _recap(args: argparse.Namespace) -> int:
    """Point de situation d'une mission : fiches réunion (en cache) puis synthèse mission."""
    from kb.adapters.factory import build_llm
    from kb.index.chunking import fmt_ts
    from kb.jsonl import read_jsonl, write_jsonl
    from kb.schemas import Segment, Video
    from kb.structure.recap import (
        VideoRecap,
        mission_recap_path,
        numbers,
        order_videos,
        recap_mission,
        recap_video,
        save,
        video_recap_path,
    )

    s = load_settings(args.profile)
    videos = read_jsonl(s.videos_file, Video)
    if args.video_ids:  # rattache ces vidéos à la mission (champ Video.mission)
        wanted = set(args.video_ids)
        unknown = wanted - {v.video_id for v in videos}
        if unknown:
            print(f"Vidéos inconnues : {', '.join(sorted(unknown))}")
            return 1
        videos = [v.model_copy(update={"mission": args.mission}) if v.video_id in wanted else v
                  for v in videos]
        write_jsonl(s.videos_file, videos)
    members = order_videos([v for v in videos if v.mission == args.mission])
    if not members:
        print(f"Aucune vidéo dans la mission {args.mission} (donnez leurs identifiants).")
        return 1
    llm = build_llm(s)
    recaps = []
    for v in members:
        path = video_recap_path(s.data_dir, v.video_id)
        if path.exists() and not args.force:
            print(f"= {v.video_id} : fiche réunion déjà faite (--force pour refaire)")
            recaps.append(VideoRecap.model_validate_json(path.read_text(encoding="utf-8")))
            continue
        print(f"→ {v.video_id}")
        segments = read_jsonl(s.transcripts_dir / f"{v.video_id}.jsonl", Segment)
        recap = recap_video(v, segments, llm)
        save(recap, path)
        recaps.append(recap)
    spoken = set().union(*(numbers(seg.text) for v in members for seg in read_jsonl(
        s.transcripts_dir / f"{v.video_id}.jsonl", Segment)))
    mission = recap_mission(args.mission, recaps, llm, model_name=s.llm.model, spoken=spoken)
    save(mission, mission_recap_path(s.data_dir, args.mission))
    print(f"\n# {args.mission} — {len(recaps)} réunion(s)\nSujet : {mission.subject}\n"
          f"Où en est-on : {mission.status}")
    for title, points in (("Décisions", mission.decisions), ("Points ouverts", mission.open_issues),
                          ("Prochaines étapes", mission.next_steps)):
        print(f"\n{title} :")
        for p in points:
            print(f"  - {p.text}  [{p.evidence.video_id}, {fmt_ts(p.evidence.start_s)}]")
    return 0


def _fiches(args: argparse.Namespace) -> int:
    from kb.index.chunking import fmt_ts
    from kb.structure.store import query_fiches

    s = load_settings(args.profile)
    fiches = query_fiches(s.kb_db_file, text=args.text, client=args.client,
                          technology=args.tech, video_id=args.video_id, limit=args.k)
    if not fiches:
        print("Aucune fiche trouvée.")
        return 0
    for f in fiches:
        print(f"\n[{f.video_id}, {fmt_ts(f.start_s)}–{fmt_ts(f.end_s)}] {f.problem}")
        if f.solution:
            print(f"  Solution : {f.solution}")
        if f.technologies:
            print(f"  Technos  : {', '.join(f.technologies)}")
        if f.client:
            print(f"  Client   : {f.client}")
        print(f"  « {f.evidence_quote[:160]} »")
    return 0


def _search(args: argparse.Namespace) -> int:
    from kb.index.chunking import fmt_ts
    from kb.index.search import Searcher

    s = load_settings(args.profile)
    searcher = Searcher.load(s, with_reranker=args.mode == "hybrid_rerank")
    t0 = time.perf_counter()
    res = searcher.search(args.question, mode=args.mode, k=args.k)
    print(f"Mode {args.mode} · {1000 * (time.perf_counter() - t0):.0f} ms")
    if res.abstain:
        print(f"⚠ Meilleur score de rerank {res.best_score:.2f} < seuil "
              f"{s.retrieval.abstain_threshold} → NON TROUVÉ (pistes les plus proches ci-dessous)")
    for i, h in enumerate(res.hits, start=1):
        print(f"\n#{i}  score={h.score:.3f}  [{h.chunk.video_id}, {fmt_ts(h.moment_s)}]  "
              f"(chunk {fmt_ts(h.chunk.start_s)}–{fmt_ts(h.chunk.end_s)}, "
              f"dense#{h.dense_rank} bm25#{h.bm25_rank})")
        print(f"    « {h.moment_text[:220]} »")
    return 0


def _ask(args: argparse.Namespace) -> int:
    from kb.agent.agent import Agent
    from kb.index.chunking import fmt_ts

    s = load_settings(args.profile)
    res = Agent.load(s).ask(args.question, mode="strict" if args.strict else "synthese")
    if args.json:
        print(res.answer.model_dump_json(indent=2))
        return 0

    a = res.answer
    print(f"Mode {res.mode} · profil {s.profile} · recherche "
          f"{res.latency_ms.get('search', 0):.0f} ms · LLM {res.latency_ms.get('llm', 0):.0f} ms")
    if a.not_found:
        print(f"\n⚠ NON TROUVÉ — {res.note}")
        if res.hits:
            print("\nPistes les plus proches :")
            for h in res.hits[:3]:
                print(f"  · [{h.chunk.video_id}, {fmt_ts(h.moment_s)}] score {h.score:.2f} "
                      f"« {h.moment_text[:120]} »")
    else:
        print(f"\n{a.answer}\n")
        print(f"Confiance (score de recherche, pas une probabilité) : {a.confidence:.2f}")
        for c in a.citations:
            mark = "✓ vérifiée" if c.verified else "✗ NON vérifiée"
            print(f"  {mark}  [{c.video_id}, {fmt_ts(c.start_s)}]  « {c.quote[:160]} »")
            print(f"            /videos/{c.video_id}#t={c.start_s:.0f}")
    if res.llm_calls:
        print(f"\nLLM : {s.llm.model} · {res.llm_calls} appel(s) · {res.input_tokens} tokens "
              f"en entrée + {res.output_tokens} en sortie · coût {res.cost_usd:.6f} $")
    if res.note and not a.not_found:
        print(f"Note : {res.note}")
    return 0


def _eval_asr(args: argparse.Namespace) -> int:
    from kb.eval.asr import run_asr_benchmark

    run_asr_benchmark(load_settings(args.profile), Path(args.folder), args.models)
    return 0


def _eval_search(args: argparse.Namespace) -> int:
    from kb.eval.retrieval import run_retrieval_eval

    run_retrieval_eval(load_settings(args.profile), Path(args.golden))
    return 0


def _eval_agent(args: argparse.Namespace) -> int:
    from kb.eval.agent import run_agent_eval

    run_agent_eval(load_settings(args.profile), Path(args.golden), types=args.types,
                   limit=args.limit, mode=args.mode, ids=args.ids)
    return 0


def _eval(args: argparse.Namespace) -> int:
    from kb.eval.full import run_full_eval

    run_full_eval(load_settings(args.profile), Path(args.golden), mode=args.mode)
    return 0


def _compare_tiers(args: argparse.Namespace) -> int:
    from kb.eval.tiers import compare_tiers

    compare_tiers(args.profiles, mode=args.mode)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb")
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser("check", help="vérifier la configuration et les connexions")
    check.add_argument("--no-call", action="store_true")

    ingest = sub.add_parser("ingest", help="transcrire un dossier de vidéos / audios")
    ingest.add_argument("folder", nargs="?", default=str(ROOT / "data" / "videos"))
    ingest.add_argument("--model", default=None, help="small, large-v3-turbo…")
    ingest.add_argument("--data-dir", default=None, help="dossier de sortie (défaut : data/)")
    ingest.add_argument("--force", action="store_true")

    sub.add_parser("index", help="construire l'index (chunks, embeddings, Chroma)")

    structure = sub.add_parser("structure", help="extraire les fiches REX (transcript -> LLM)")
    structure.add_argument("video_ids", nargs="*", help="défaut : toutes les vidéos ingérées")
    structure.add_argument("--force", action="store_true")

    recap = sub.add_parser("recap", help="point de situation d'une mission (résumés L3)")
    recap.add_argument("mission", help="nom de la mission, ex. ES2002")
    recap.add_argument("video_ids", nargs="*", help="vidéos à rattacher à la mission")
    recap.add_argument("--force", action="store_true", help="refaire les fiches réunion")

    fiches = sub.add_parser("fiches", help="interroger les fiches REX (outil query_fiches)")
    fiches.add_argument("text", nargs="?", default=None, help="recherche dans problème/solution")
    fiches.add_argument("--client", default=None)
    fiches.add_argument("--tech", default=None)
    fiches.add_argument("--video-id", default=None)
    fiches.add_argument("-k", type=int, default=10)

    search = sub.add_parser("search", help="rechercher les passages les plus pertinents")
    search.add_argument("question")
    search.add_argument("--mode", default="hybrid_rerank",
                        choices=["dense", "bm25", "hybrid", "hybrid_rerank"])
    search.add_argument("-k", type=int, default=5)

    ask = sub.add_parser("ask", help="poser une question (réponse prouvée ou abstention)")
    ask.add_argument("question")
    ask.add_argument("--strict", action="store_true", help="extraits seuls, aucune génération")
    ask.add_argument("--json", action="store_true", help="sortie Answer brute (JSON)")

    asr = sub.add_parser("eval-asr", help="comparer des modèles Whisper (WER, vitesse)")
    asr.add_argument("--folder", default=str(ROOT / "data" / "videos"))
    asr.add_argument("--models", nargs="+", default=["small"])

    golden_default = str(ROOT / "src" / "kb" / "eval" / "golden_set.jsonl")
    ev = sub.add_parser("eval-search", help="évaluer la recherche sur le golden set")
    ev.add_argument("--golden", default=golden_default)

    ea = sub.add_parser("eval-agent", help="évaluer l'agent (abstention, citations, coût)")
    ea.add_argument("--golden", default=golden_default)
    ea.add_argument("--types", nargs="+", default=None, help="ex. single_fact unanswerable")
    ea.add_argument("--ids", nargs="+", default=None, help="ex. P01 S05 U06 (échantillon)")
    ea.add_argument("--limit", type=int, default=None)
    ea.add_argument("--mode", default="synthese", choices=["synthese", "strict"])

    ev_full = sub.add_parser("eval", help="recherche + agent + synthèse (un profil)")
    ev_full.add_argument("--golden", default=golden_default)
    ev_full.add_argument("--mode", default="synthese", choices=["synthese", "strict"])

    ct = sub.add_parser("compare-tiers", help="comparer des profils déjà évalués (coût-qualité)")
    ct.add_argument("--profiles", nargs="+", default=["free", "dataiku", "market"])
    ct.add_argument("--mode", default="synthese", choices=["synthese", "strict"])

    for p in sub.choices.values():
        p.add_argument("--profile", default=None)

    args = parser.parse_args(argv)
    _use_utf8_console()
    _use_system_certificates()
    handlers = {
        "check": lambda a: _check(a.profile, call=not a.no_call),
        "ingest": _ingest,
        "index": _index,
        "structure": _structure,
        "fiches": _fiches,
        "recap": _recap,
        "search": _search,
        "ask": _ask,
        "eval-asr": _eval_asr,
        "eval-search": _eval_search,
        "eval-agent": _eval_agent,
        "eval": _eval,
        "compare-tiers": _compare_tiers,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
