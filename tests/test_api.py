"""Tests de l'API SANS réseau ni modèle : l'agent et les paramètres sont remplacés par des faux."""

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

import kb.api.app as api
from kb.config import load_settings
from kb.jsonl import write_jsonl
from kb.schemas import Answer, Citation, Video
from kb.structure.store import save_fiches

VIDEO = Video(video_id="v1", title="Migration Redis", source_uri="v1.wav", duration_s=120.0)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = load_settings("free")
    s.data_dir = tmp_path
    monkeypatch.setattr(api, "load_settings", lambda profile=None: s)
    return s


@pytest.fixture
def client(settings):
    return TestClient(api.app)


def test_list_and_get_video(client, settings):
    write_jsonl(settings.videos_file, [VIDEO])
    assert client.get("/videos").json() == [VIDEO.model_dump(mode="json")]
    assert client.get("/videos/v1").json()["title"] == "Migration Redis"
    assert client.get("/videos/absent").status_code == 404


def test_video_media_serves_the_source_file(client, settings):
    write_jsonl(settings.videos_file, [VIDEO])
    (settings.data_dir / "videos").mkdir(parents=True)
    (settings.data_dir / "videos" / "v1.wav").write_bytes(b"RIFF....fake wav")
    resp = client.get("/videos/v1/media")
    assert resp.status_code == 200 and resp.content == b"RIFF....fake wav"


def test_video_media_joins_parts_so_late_citations_are_reachable(client, settings, monkeypatch):
    import io
    import wave

    import numpy as np

    import kb.adapters.transcribe_fw as fw

    video = Video(video_id="v2", title="En 2 morceaux", source_uri="v2_seg01.wav;v2_seg02.wav",
                  duration_s=3.0)
    write_jsonl(settings.videos_file, [video])
    (settings.data_dir / "videos").mkdir(parents=True)
    for name in ("v2_seg01.wav", "v2_seg02.wav"):
        (settings.data_dir / "videos" / name).write_bytes(b"x")
    decoded = []
    monkeypatch.setattr(fw, "load_audio",
                        lambda parts: decoded.append(len(parts)) or np.zeros(3 * fw.SAMPLE_RATE))
    resp = client.get("/videos/v2/media")
    with wave.open(io.BytesIO(resp.content)) as w:
        assert w.getnframes() / w.getframerate() == 3.0  # durée totale, pas le 1er morceau
    client.get("/videos/v2/media")
    assert decoded == [2]  # 2e appel servi depuis le cache


def test_video_media_404_when_file_missing(client, settings):
    write_jsonl(settings.videos_file, [VIDEO])
    assert client.get("/videos/v1/media").status_code == 404


def test_video_fiches_uses_query_fiches(client, settings):
    from kb.schemas import FicheREX

    fiche = FicheREX(fiche_id="v1__01", video_id="v1", problem="Cache saturé",
                     start_s=10, end_s=20, evidence_quote="le cache Redis saturait la mémoire")
    save_fiches(settings.kb_db_file, "v1", [fiche])
    resp = client.get("/videos/v1/fiches")
    assert resp.status_code == 200 and len(resp.json()) == 1
    assert resp.json()[0]["fiche_id"] == "v1__01"


def test_video_segments_returns_transcript(client, settings):
    from kb.jsonl import write_jsonl as write
    from kb.schemas import Segment

    seg = Segment(video_id="v1", seg_id=0, start_s=0, end_s=4, text="Bonjour.")
    write(settings.transcripts_dir / "v1.jsonl", [seg])
    resp = client.get("/videos/v1/segments")
    assert resp.status_code == 200 and len(resp.json()) == 1
    assert resp.json()[0]["text"] == "Bonjour."


def test_video_segments_empty_when_not_transcribed(client, settings):
    assert client.get("/videos/v1/segments").json() == []


def test_list_fiches_across_videos_with_text_filter(client, settings):
    from kb.schemas import FicheREX

    save_fiches(settings.kb_db_file, "v1", [
        FicheREX(fiche_id="v1__01", video_id="v1", problem="Cache Redis saturé",
                 start_s=10, end_s=20, evidence_quote="cache Redis saturait la mémoire"),
    ])
    save_fiches(settings.kb_db_file, "v2", [
        FicheREX(fiche_id="v2__01", video_id="v2", problem="Panne réseau intermittente",
                 start_s=5, end_s=15, evidence_quote="coupure réseau intermittente"),
    ])
    assert {f["fiche_id"] for f in client.get("/fiches").json()} == {"v1__01", "v2__01"}
    resp = client.get("/fiches", params={"text": "cache"})
    assert [f["fiche_id"] for f in resp.json()] == ["v1__01"]


def test_job_status_unknown_is_404(client):
    assert client.get("/jobs/absent").status_code == 404


def test_upload_saves_file_and_starts_a_background_job(client, settings, monkeypatch):
    started = []
    monkeypatch.setattr(api, "run_in_background",
                        lambda job_id, fn, *a: started.append((job_id, fn, a)))
    resp = client.post("/videos", files={"file": ("clip.wav", b"fake audio bytes", "audio/wav")})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert started and started[0][0] == job_id
    assert (settings.data_dir / "videos" / "clip.wav").read_bytes() == b"fake audio bytes"
    assert client.get(f"/jobs/{job_id}").json()["status"] == "queued"


@dataclass
class FakeAgentResult:
    answer: Answer


class FakeAgent:
    def __init__(self, answer: Answer) -> None:
        self._answer = answer
        self.calls: list[tuple] = []

    def ask(self, question, mode="synthese", filters=None):
        self.calls.append((question, mode, filters))
        return FakeAgentResult(answer=self._answer)


def test_ask_delegates_to_the_agent(client, monkeypatch):
    answer = Answer(answer="Éviction LRU. [S1]", confidence=0.9,
                    citations=[Citation(chunk_id="v1__000", video_id="v1", start_s=12.0,
                                        quote="…", verified=True)])
    fake = FakeAgent(answer)
    monkeypatch.setattr(api, "_agent", lambda profile, model=None: fake)
    resp = client.post("/ask", json={"question": "Comment corriger le cache ?", "mode": "strict"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "Éviction LRU. [S1]"
    assert fake.calls == [("Comment corriger le cache ?", "strict", None)]


def test_ask_abstention_returns_transcript_leads_not_citations(client, monkeypatch):
    from kb.index.search import Hit
    from kb.schemas import Chunk

    chunk = Chunk(chunk_id="v1__000", video_id="v1", start_s=0, end_s=120, context_header="",
                  text="He felt his own age, 44, wrote Mailer in the Armies of the Night.")
    hits = [Hit(chunk=chunk, score=0.07, rerank_score=0.0724, moment_s=34.0,
                moment_text=" He felt his own age, 44, wrote Mailer in the Armies of the Night. ")]

    class AbstainingAgent:
        def ask(self, question, mode="synthese", filters=None):
            return type("R", (), {"answer": Answer(not_found=True), "hits": hits,
                                  "note": "abstention avant génération", "search_query": "q"})()

    monkeypatch.setattr(api, "_agent", lambda profile, model=None: AbstainingAgent())
    body = client.post("/ask", json={"question": "Quel livre ?"}).json()
    assert body["not_found"] and body["citations"] == []  # une piste n'est pas une preuve
    assert body["leads"] == [{"video_id": "v1", "start_s": 34.0, "score": 0.072, "page": None,
                              "modality": None,
                              "text": "He felt his own age, 44, wrote Mailer in the Armies of the "
                                      "Night."}]
    assert body["note"] == "abstention avant génération"


def test_ask_answer_has_no_leads(client, monkeypatch):
    answer = Answer(answer="Mailer. [S1]", confidence=0.9,
                    citations=[Citation(chunk_id="v1__000", video_id="v1", start_s=34.0,
                                        quote="wrote Mailer", verified=True)])
    monkeypatch.setattr(api, "_agent", lambda profile, model=None: FakeAgent(answer))
    assert client.post("/ask", json={"question": "Quel livre ?"}).json()["leads"] == []


def test_metrics_returns_null_kpis_without_any_report(client, monkeypatch, tmp_path):
    import kb.eval.summary as summary_module

    monkeypatch.setattr(summary_module, "REPORTS_DIR", tmp_path)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert all(v is None for v in body["kpis"].values())
    assert body["risk_coverage"] is None


def test_metrics_corpus_reads_its_own_reports(client, monkeypatch, tmp_path):
    import kb.eval.summary as summary_module

    monkeypatch.setattr(summary_module, "REPORTS_DIR", tmp_path)
    header = "id,type,lang,mode,answerable,hit1,hit5,moment_hit,best_score\n"
    (tmp_path / "search_free_2026-09-17.csv").write_text(
        header + "T1,single_fact,en,hybrid_rerank,True,True,True,True,0.9\n", encoding="utf-8")
    (tmp_path / "ami_search_free_2026-09-25.csv").write_text(
        header + "M1,single_fact,en,hybrid_rerank,True,False,False,False,0.2\n", encoding="utf-8")
    (tmp_path / "asr_2026-09-17.md").write_text("`large-v3-turbo` : WER **2.0%**", "utf-8")

    ted = client.get("/metrics").json()
    ami = client.get("/metrics", params={"corpus": "ami"}).json()
    assert ted["corpus"] == "ted" and ted["kpis"]["recall_at_5"] == 1.0
    assert ted["kpis"]["wer"] == 0.02
    assert ami["kpis"]["recall_at_5"] == 0.0 and ami["kpis"]["wer"] is None  # WER : TED seulement
    assert ami["sources"]["search"] == "ami_search_free_2026-09-25.csv"
    assert client.get("/metrics", params={"corpus": "xyz"}).status_code == 400


def test_tiers_reports_missing_profiles(client, monkeypatch, tmp_path):
    import kb.eval.tiers as tiers_module

    monkeypatch.setattr(tiers_module, "REPORTS_DIR", tmp_path)  # isolé des vrais rapports du repo
    resp = client.get("/tiers", params={"profiles": ["free"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["rows"] == [] and body["missing"] == ["free"]


def test_experts_groups_verified_fiches_by_author(client, settings):
    from kb.schemas import FicheREX

    save_fiches(settings.kb_db_file, "v1", [
        FicheREX(fiche_id="v1__01", video_id="v1", problem="Cache Redis saturé",
                 technologies=["Redis"], author="Jean Dupont", client="Synchrone",
                 start_s=10, end_s=20, evidence_quote="cache Redis saturait la mémoire"),
        FicheREX(fiche_id="v1__02", video_id="v1", problem="Panne réseau",
                 author=None, start_s=30, end_s=40, evidence_quote="coupure réseau intermittente"),
    ])
    resp = client.get("/experts", params={"topic": "Redis"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1 and body[0]["author"] == "Jean Dupont" and body[0]["fiches"] == 1


def test_missions_list_and_recap(client, settings):
    from kb.structure.recap import MissionRecap, mission_recap_path, save

    videos = [Video(video_id=i, title=i, source_uri=f"{i}.wav", duration_s=60, mission="ES2002")
              for i in ("es_b", "es_a")] + [VIDEO]
    write_jsonl(settings.videos_file, videos)
    assert client.get("/missions").json() == [
        {"mission": "ES2002", "video_ids": ["es_a", "es_b"], "recap_available": False,
         "generated_at": None}]
    assert client.get("/missions/ES2002/recap").status_code == 404

    save(MissionRecap(mission="ES2002", videos=[], subject="Télécommande", status="Design",
                      generated_at="2026-09-25T11:00:00"),
         mission_recap_path(settings.data_dir, "ES2002"))
    assert client.get("/missions").json()[0]["recap_available"] is True
    assert client.get("/missions/ES2002/recap").json()["status"] == "Design"


def test_ask_routes_status_questions_to_the_mission_recap(client, settings, monkeypatch):
    from kb.structure.recap import Evidence, MissionRecap, RecapPoint, mission_recap_path, save

    write_jsonl(settings.videos_file, [
        Video(video_id="es_a", title="a", source_uri="a.wav", duration_s=60, mission="ES2002")])
    point = RecapPoint(kind="decision", text="Boîtier en caoutchouc", evidence=Evidence(
        video_id="es_a", start_s=57.0, quote="a combination of LCD and rubber"))
    save(MissionRecap(mission="ES2002", videos=[], subject="Télécommande",
                      status="Prototype en production.", decisions=[point],
                      generated_at="2026-09-25T12:00:00"),
         mission_recap_path(settings.data_dir, "ES2002"))
    monkeypatch.setattr(api, "_agent",
                        lambda profile, model=None: pytest.fail("l'agent ne doit pas tourner"))
    body = client.post("/ask", json={"question": "Où en est la mission ES2002 ?"}).json()
    assert body["mission"] == "ES2002" and body["answer"] == "Prototype en production."
    assert body["citations"][0]["start_s"] == 57.0 and body["citations"][0]["verified"]


def test_ordinary_question_still_goes_to_the_agent(client, settings, monkeypatch):
    answer = Answer(answer="25 euros. [S1]", confidence=0.9,
                    citations=[Citation(chunk_id="c", video_id="v1", start_s=1.0,
                                        quote="for 25 euro", verified=True)])
    monkeypatch.setattr(api, "_agent", lambda profile, model=None: FakeAgent(answer))
    body = client.post("/ask", json={"question": "Quel est le prix de vente ?"}).json()
    assert body["mission"] is None and body["answer"] == "25 euros. [S1]"


def test_models_lists_the_three_dataiku_models_with_prices(client, settings, monkeypatch):
    dk = load_settings("dataiku")
    monkeypatch.setattr(api, "load_settings", lambda profile=None: dk)
    body = client.get("/models", params={"profile": "dataiku"}).json()
    ids = [m["id"] for m in body["models"]]
    assert ids[0] == body["default"] and len(ids) == 3
    assert any(i.endswith("gpt-5.6-sol") for i in ids)
    sol = next(m for m in body["models"] if m["id"].endswith("sol"))
    assert (sol["input_per_m"], sol["output_per_m"]) == (5, 30)


def test_ask_uses_the_selected_model_and_says_so(client, settings, monkeypatch):
    dk = load_settings("dataiku")
    monkeypatch.setattr(api, "load_settings", lambda profile=None: dk.model_copy(deep=True))
    built = []

    class Loaded:
        def __init__(self, s):
            self.settings = s

        def ask(self, question, mode="synthese", filters=None):
            return FakeAgentResult(answer=Answer(not_found=True))

    monkeypatch.setattr(api.Agent, "load", lambda s: built.append(s.llm.model) or Loaded(s))
    monkeypatch.setattr(api, "_agents", {})
    terra = "openai:challenge_llm:gpt-5.6-terra"
    body = client.post("/ask", json={"question": "Prix ?", "profile": "dataiku",
                                     "model": terra}).json()
    assert body["model"] == terra and built == [terra]  # Terra, pas Luna
    client.post("/ask", json={"question": "Prix ?", "profile": "dataiku"})
    assert built[-1].endswith("luna")  # sans choix : le défaut ; agent distinct du précédent
    bad = client.post("/ask", json={"question": "Prix ?", "profile": "dataiku", "model": "gpt-9"})
    assert bad.status_code == 400 and "gpt-5.6-sol" in bad.json()["detail"]


def test_selected_model_carries_its_own_price():
    llm = load_settings("dataiku").llm
    sol = llm.with_model("openai:challenge_llm:gpt-5.6-sol")
    assert (sol.model, sol.input_per_m, sol.output_per_m) == (
        "openai:challenge_llm:gpt-5.6-sol", 5, 30)
    assert llm.model.endswith("luna")  # l'original n'est pas modifié
