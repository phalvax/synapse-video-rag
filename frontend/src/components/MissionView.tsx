import { useEffect, useState, type ReactNode } from "react";
import { getMissionRecap, listMissions } from "../api/client";
import type { MissionInfo, MissionRecap, RecapPoint, Video } from "../types";
import { fmtLoc, titleOf } from "../utils";
import { Card, Icon, Segmented } from "./ui";

interface Props {
  videos: Video[];
  onOpen: (videoId: string, startS: number, page?: number | null) => void;
  /** Mission à afficher d'emblée (ouverte depuis le chat). */
  initialMission?: string;
}

export default function MissionView({ videos, onOpen, initialMission }: Props) {
  const [missions, setMissions] = useState<MissionInfo[]>([]);
  const [selected, setSelected] = useState("");
  const [recap, setRecap] = useState<MissionRecap | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listMissions()
      .then((ms) => {
        setMissions(ms);
        const wanted = ms.find((m) => m.mission === initialMission);
        const first = wanted ?? ms.find((m) => m.recap_available) ?? ms[0];
        if (first) setSelected(first.mission);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, [initialMission]);

  useEffect(() => {
    if (!selected) return;
    setRecap(null);
    setError(null);
    getMissionRecap(selected).then(setRecap).catch((e) => setError(String(e.message ?? e)));
  }, [selected]);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Point mission</h1>
          <p className="mt-1 text-[15px] text-muted">
            Où en est le projet, d'après ses réunions — chaque point renvoie à sa preuve.
          </p>
        </div>
        {missions.length > 0 && (
          <Segmented
            label="Mission"
            options={missions.map((m) => ({ value: m.mission, label: m.mission }))}
            value={selected}
            onChange={setSelected}
          />
        )}
      </header>

      {missions.length === 0 && !error && (
        <Card className="p-6 text-sm text-muted">
          Aucune mission. Rattachez des réunions avec{" "}
          <code className="rounded bg-surface-2 px-1.5 py-0.5 text-ink-2">
            python -m kb.cli recap NOM video_id…
          </code>
        </Card>
      )}
      {error && (
        <Card className="border-danger/40 bg-danger-soft p-4 text-sm text-danger">{error}</Card>
      )}

      {recap && (
        <div key={recap.mission} className="anim-in flex flex-col gap-6">
          <Card className="p-6">
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Objet du projet</p>
            <p className="mt-1 text-[16px] font-medium text-ink">{recap.subject || "—"}</p>
            <p className="mt-5 text-xs font-medium uppercase tracking-wide text-muted">Où en est-on</p>
            <p className="mt-1 max-w-4xl text-[16px] leading-relaxed text-ink">{recap.status || "—"}</p>
            <p className="mt-5 text-xs text-muted">
              Synthèse rédigée par {recap.model || "le LLM"} le{" "}
              {recap.generated_at.replace("T", " à ").slice(0, 18)} à partir de{" "}
              {recap.videos.length} réunion(s). Les textes sont générés ; les extraits sont exacts.
            </p>
          </Card>

          <div className="grid gap-5 lg:grid-cols-3">
            <Column title="Décisions" icon={<Icon.check />} bar="bg-ok" points={recap.decisions}
                    videos={videos} onOpen={onOpen} />
            <Column title="Points ouverts" icon={<Icon.alert />} bar="bg-warn" points={recap.open_issues}
                    videos={videos} onOpen={onOpen} />
            <Column title="Prochaines étapes" icon={<Icon.arrow />} bar="bg-accent"
                    points={recap.next_steps} videos={videos} onOpen={onOpen} />
          </div>

          <section>
            <h2 className="mb-4 text-sm font-semibold text-ink">
              Réunions, de la plus ancienne à la plus récente
            </h2>
            <ol className="relative grid gap-4" style={{ gridTemplateColumns: `repeat(${Math.max(1, recap.videos.length)}, minmax(0, 1fr))` }}>
              <span aria-hidden className="absolute left-4 right-4 top-4 h-px bg-line-strong" />
              {recap.videos.map((v, i) => (
                <li key={v.video_id} className="relative">
                  <span
                    className={`relative z-10 flex h-8 w-8 items-center justify-center rounded-full border-2 text-sm font-semibold ${
                      i === recap.videos.length - 1
                        ? "border-accent bg-accent text-accent-ink"
                        : "border-line-strong bg-surface text-ink-2"
                    }`}
                  >
                    {i + 1}
                  </span>
                  <button
                    onClick={() => onOpen(v.video_id, 0)}
                    className="mt-3 w-full rounded-xl border border-line bg-surface p-4 text-left
                               shadow-card transition-colors hover:border-accent"
                  >
                    <p className="text-xs font-medium text-accent">
                      {titleOf(v.video_id, videos)}
                      {i === recap.videos.length - 1 && " · la plus récente"}
                    </p>
                    <p className="mt-1 text-sm font-medium text-ink">{v.subject || v.title}</p>
                    <p className="mt-2 line-clamp-5 text-sm leading-relaxed text-muted">{v.summary}</p>
                  </button>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
    </div>
  );
}

function Column({
  title,
  icon,
  bar,
  points,
  videos,
  onOpen,
}: {
  title: string;
  icon: ReactNode;
  bar: string;
  points: RecapPoint[];
  videos: Video[];
  onOpen: (videoId: string, startS: number, page?: number | null) => void;
}) {
  return (
    <Card className="overflow-hidden">
      <div className={`h-1 ${bar}`} />
      <div className="flex items-center gap-2 px-4 pb-2 pt-3.5 text-ink">
        <span className="text-muted">{icon}</span>
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="ml-auto text-xs tabular-nums text-muted">{points.length}</span>
      </div>
      {points.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-muted">Aucun point relevé.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line">
          {points.map((p, i) => (
            <li key={i}>
              <button
                onClick={() => onOpen(p.evidence.video_id, p.evidence.start_s, p.evidence.page)}
                className="group w-full px-4 py-3 text-left transition-colors hover:bg-surface-2"
              >
                <p className="text-sm leading-snug text-ink">{p.text}</p>
                <p className="mt-1.5 flex items-center gap-1.5 text-xs text-accent">
                  <span className="scale-75"><Icon.play /></span>
                  {titleOf(p.evidence.video_id, videos)} · {fmtLoc(p.evidence)}
                </p>
                <p className="mt-1 line-clamp-2 text-xs italic text-muted">« {p.evidence.quote} »</p>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
