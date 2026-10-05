"""Point de situation (L3) SANS réseau ni modèle : le LLM est remplacé par un faux."""

import json

from kb.schemas import Segment, Video
from kb.structure.recap import (
    Evidence,
    RecapPoint,
    VideoRecap,
    _pick,
    load_mission_recap,
    make_windows,
    mission_recap_path,
    order_videos,
    recap_mission,
    recap_video,
    save,
)

SEGS = [
    Segment(video_id="m1", seg_id=0, start_s=0.0, end_s=5.0, text="okay let's start the meeting"),
    Segment(video_id="m1", seg_id=1, start_s=5.0, end_s=11.0,
            text="we're going to be selling this remote control for 25 euro"),
    Segment(video_id="m1", seg_id=2, start_s=11.0, end_s=18.0,
            text="and we decided the buttons will be rubber ones"),
]
VIDEO = Video(video_id="m1", title="Kick-off", source_uri="m1.wav", duration_s=18.0)


class FakeLLM:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[list[dict]] = []

    def complete(self, messages, json_schema=None, temperature=None):
        self.prompts.append(messages)
        return self.replies.pop(0) if self.replies else "{}"


def _point(text: str, start: float = 5.0) -> RecapPoint:
    return RecapPoint(kind="decision", text=text,
                      evidence=Evidence(video_id="m1", start_s=start, quote="…"))


def test_windows_cover_all_segments_in_order():
    windows = make_windows(SEGS, max_tokens=12)
    assert [s.seg_id for w in windows for s in w.segments] == [0, 1, 2]
    assert len(windows) > 1


def test_video_recap_keeps_only_proven_points_with_their_second():
    window = json.dumps({"summary": "Prix et boutons.", "points": [
        {"kind": "decision", "text": "Prix de vente fixé à 25 €",
         "quote": "selling this remote control for 25 euro"},
        {"kind": "decision", "text": "Boutons en caoutchouc",
         "quote": "The buttons will be RUBBER ones"},             # casse différente → recalée
        {"kind": "issue", "text": "Budget dépassé", "quote": "we are way over budget now"},
    ]})
    video = json.dumps({"subject": "Lancement", "summary": "…", "participants": [],
                        "key_points": ["P2", "P9", "P1"]})       # P9 n'existe pas
    recap = recap_video(VIDEO, SEGS, FakeLLM(window, video), log=lambda *_: None)
    assert recap.dropped_points == 1                              # citation inventée écartée
    assert [p.text for p in recap.key_points] == ["Boutons en caoutchouc",
                                                  "Prix de vente fixé à 25 €"]
    price = recap.key_points[1].evidence
    assert price.start_s == 5.0 and price.quote in SEGS[1].text   # seconde du bon segment
    assert recap.key_points[0].evidence.quote == "the buttons will be rubber ones"


def test_mission_recap_maps_ids_to_proven_points_and_ignores_invented_ones():
    v1 = VideoRecap(video_id="a", title="Réunion 1", subject="…", summary="…",
                    key_points=[_point("Prix fixé")])
    v2 = VideoRecap(video_id="b", title="Réunion 2", subject="…", summary="…",
                    key_points=[_point("Boutons caoutchouc"), _point("Tester le prototype")])
    llm = FakeLLM(json.dumps({"subject": "Télécommande", "status": "Design en cours.",
                              "decisions": ["K1", "K2", "K2"], "open_issues": ["K42"],
                              "next_steps": ["[K3]"]}))
    recap = recap_mission("ES2002", [v1, v2], llm, model_name="fake")
    assert [p.text for p in recap.decisions] == ["Prix fixé", "Boutons caoutchouc"]
    assert recap.open_issues == [] and [p.text for p in recap.next_steps] == ["Tester le prototype"]
    prompt = llm.prompts[0][1]["content"]
    assert prompt.index("Réunion 1/2") < prompt.index("Réunion 2/2")  # ordre chronologique


def test_invalid_json_twice_gives_an_empty_but_valid_recap():
    recap = recap_mission("X", [], FakeLLM("pas du json", "toujours pas"))
    assert recap.subject == "" and recap.decisions == []


def test_pick_is_case_and_bracket_tolerant():
    table = {"P1": _point("a"), "P2": _point("b")}
    assert [p.text for p in _pick(["p2", "[P1]", "P7"], table)] == ["b", "a"]


def test_videos_are_ordered_oldest_first():
    vids = [Video(video_id=i, title=i, source_uri="x", duration_s=1) for i in ("es_d", "es_a")]
    assert [v.video_id for v in order_videos(vids)] == ["es_a", "es_d"]


def test_recap_roundtrip_on_disk(tmp_path):
    recap = recap_mission("ES2002", [], FakeLLM(json.dumps(
        {"subject": "S", "status": "E", "decisions": [], "open_issues": [], "next_steps": []})))
    save(recap, mission_recap_path(tmp_path, "ES2002"))
    assert load_mission_recap(tmp_path, "ES2002").status == "E"
    assert load_mission_recap(tmp_path, "absente") is None


def test_point_with_a_number_absent_from_its_quote_is_dropped():
    window = json.dumps({"summary": "…", "points": [
        {"kind": "decision", "text": "Dimensions finales : 2,5 cm × 2 cm",
         "quote": "and we decided the buttons will be rubber ones"},
        {"kind": "decision", "text": "Prix fixé à 25 €",
         "quote": "selling this remote control for 25 euro"},
    ]})
    recap = recap_video(VIDEO, SEGS, FakeLLM(window, "{}"), log=lambda *_: None)
    assert recap.dropped_points == 1
    assert [p.text for p in recap.windows[0].points] == ["Prix fixé à 25 €"]


def test_a_point_goes_in_one_list_only_and_participants_are_cleaned():
    v = VideoRecap(video_id="a", title="R", subject="…", summary="…", participants=["[", "Laura"],
                   key_points=[_point("Boutons caoutchouc")])
    llm = FakeLLM(json.dumps({"subject": "S", "status": "E", "decisions": ["K1"],
                              "open_issues": [], "next_steps": ["K1"]}))
    recap = recap_mission("M", [v], llm)
    assert len(recap.decisions) == 1 and recap.next_steps == []
    assert recap.videos[0].participants == ["Laura"]


def test_number_point_gets_the_extract_that_contains_the_number():
    segs = SEGS + [Segment(video_id="m1", seg_id=3, start_s=18.0, end_s=22.0,
                           text="width wise about two centimeters We'll say 2.5.")]
    window = json.dumps({"summary": "…", "points": [
        {"kind": "decision", "text": "Largeur retenue : 2,5 cm",
         "quote": "and we decided the buttons will be rubber ones"}]})   # bonne phrase ? non
    recap = recap_video(VIDEO, segs, FakeLLM(window, "{}"), log=lambda *_: None)
    ev = recap.windows[0].points[0].evidence
    assert "2.5" in ev.quote and ev.start_s == 18.0 and recap.dropped_points == 0


def test_summary_sentences_with_unspoken_numbers_are_removed():
    from kb.structure.recap import spoken_only

    text = "Le prix est de 25 euros. La télécommande mesure 7 cm. Le design est simple."
    assert spoken_only(text, {"25", "2.5"}) == "Le prix est de 25 euros. Le design est simple."


def test_identifiers_are_not_numbers():
    from kb.structure.recap import numbers

    assert numbers("La mission ES2002 (réunion es2004d) : 2,5 cm et 4.25.") == {"2.5", "4.25"}


def test_file_names_are_stripped_from_generated_texts():
    from kb.structure.recap import strip_ids

    ids = ["Ami es2004d", "ami_es2004d"]
    assert strip_ids('Le prototype "Ami es2004d" a reçu 4.25.', ids) == "Le prototype a reçu 4.25."
    out = strip_ids("Refonte de la télécommande (ami_es2004d).", ids)
    assert out == "Refonte de la télécommande."
