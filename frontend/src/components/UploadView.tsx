import { useEffect, useState } from "react";
import { getJobStatus, listMissions, uploadVideo } from "../api/client";
import type { Job, UploadMeta, Video } from "../types";
import { titleOf } from "../utils";
import { Card, Icon, Steps, type StepState } from "./ui";

type Stage = "idle" | "uploading" | Job["status"];

const ORDER: Stage[] = ["uploading", "queued", "transcribing", "indexing", "done"];
const STEPS: { label: string; stages: Stage[] }[] = [
  { label: "Envoi du fichier", stages: ["uploading"] },
  { label: "Transcription, lecture du texte ou de l'image", stages: ["queued", "transcribing"] },
  { label: "Contrôle des doublons et indexation", stages: ["indexing"] },
  { label: "Prête pour la recherche", stages: ["done"] },
];

const LANGUAGES: { value: NonNullable<UploadMeta["language"]>; label: string }[] = [
  { value: "auto", label: "Détection automatique" },
  { value: "fr", label: "Français" },
  { value: "en", label: "Anglais" },
  { value: "de", label: "Allemand" },
  { value: "es", label: "Espagnol" },
  { value: "it", label: "Italien" },
];

const EMPTY: UploadMeta = { language: "auto" };

function fmtSize(bytes: number): string {
  return bytes > 1e9 ? `${(bytes / 1e9).toFixed(1)} Go` : `${(bytes / 1e6).toFixed(1)} Mo`;
}

export default function UploadView({ videos, onDone }: { videos: Video[]; onDone?: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [meta, setMeta] = useState<UploadMeta>(EMPTY);
  const [missions, setMissions] = useState<string[]>([]);
  const [stage, setStage] = useState<Stage>("idle");
  const [lastStage, setLastStage] = useState<Stage>("idle"); // étape atteinte avant un échec
  const [pct, setPct] = useState(0);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    listMissions().then((ms) => setMissions(ms.map((m) => m.mission))).catch(() => {});
  }, []);

  const busy = stage !== "idle" && stage !== "done" && stage !== "failed" && stage !== "duplicate";
  const set = (k: keyof UploadMeta) => (e: { target: { value: string } }) =>
    setMeta((m) => ({ ...m, [k]: e.target.value }));

  function advance(s: Stage) {
    setStage(s);
    if (s !== "failed" && s !== "duplicate") setLastStage(s);
  }

  function pick(f: File | undefined) {
    if (!f || busy) return;
    setFile(f);
    setStage("idle");
    setError(null);
    setJob(null);
    // Titre proposé depuis le nom du fichier : l'utilisateur le corrige s'il veut.
    setMeta((m) => ({ ...m, title: m.title || f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ") }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!file || busy) return;
    advance("uploading");
    setPct(0);
    setError(null);
    setJob(null);
    try {
      const { job_id } = await uploadVideo(file, setPct, meta);
      advance("queued");
      const poll = async () => {
        try {
          const j = await getJobStatus(job_id);
          setJob(j);
          advance(j.status);
          if (j.status === "failed") setError(j.error ?? "Échec du traitement.");
          else if (j.status === "done") onDone?.();
          else if (j.status !== "duplicate") setTimeout(poll, 1000);
        } catch (err) {
          setStage("failed");
          setError(err instanceof Error ? err.message : "Erreur inconnue");
        }
      };
      poll();
    } catch (err) {
      setStage("failed");
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    }
  }

  const reached = ORDER.indexOf(stage === "failed" || stage === "duplicate" ? lastStage : stage);
  const steps = STEPS.map((s) => {
    const first = ORDER.indexOf(s.stages[0]);
    const last = ORDER.indexOf(s.stages[s.stages.length - 1]);
    let state: StepState =
      stage === "done" || reached > last ? "done" : reached >= first ? "active" : "todo";
    if ((stage === "failed" || stage === "duplicate") && state === "active") state = "todo";
    return {
      label: s.label,
      state,
      detail: s.stages[0] === "uploading" && stage === "uploading" ? `${pct} %` : undefined,
    };
  });

  const field =
    "w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink " +
    "placeholder:text-muted focus:border-accent focus:outline-none disabled:opacity-60";

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Importer un enregistrement ou un document</h1>
        <p className="mt-1 text-[15px] text-muted">
          Réunion, formation, présentation, compte rendu PDF… Le contexte saisi ici (mission, date, auteur) est
          rarement prononcé : il rend la recherche et le point mission plus précis.
        </p>
      </header>

      <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            pick(e.dataTransfer.files?.[0]);
          }}
          className={`flex min-h-64 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl
                      border-2 border-dashed p-8 text-center transition-colors ${
                        dragging
                          ? "border-accent bg-accent-soft"
                          : file
                            ? "border-accent/60 bg-surface"
                            : "border-line-strong bg-surface hover:border-accent"
                      }`}
        >
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-accent-soft text-accent">
            {file ? <Icon.wave /> : <Icon.upload />}
          </span>
          {file ? (
            <>
              <span className="max-w-full truncate text-[15px] font-medium text-ink">{file.name}</span>
              <span className="text-sm text-muted">{fmtSize(file.size)} · cliquez pour changer</span>
            </>
          ) : (
            <>
              <span className="text-[15px] font-medium text-ink">
                Déposez un fichier ici, ou cliquez pour le choisir
              </span>
              <span className="text-sm text-muted">
                Vidéo, audio, PDF (même scanné) ou image (schéma, photo de tableau)
              </span>
            </>
          )}
          <input
            type="file"
            accept="video/*,audio/*,image/*,.pdf,application/pdf"
            className="hidden"
            disabled={busy}
            onChange={(e) => pick(e.target.files?.[0])}
          />
        </label>

        <Card className="p-5">
          <fieldset disabled={busy} className="grid gap-4 sm:grid-cols-2">
            <legend className="mb-3 text-sm font-semibold text-ink">
              Contexte <span className="font-normal text-muted">— facultatif, mais recommandé</span>
            </legend>
            <label className="sm:col-span-2">
              <span className="mb-1 block text-sm text-ink-2">Titre</span>
              <input className={field} value={meta.title ?? ""} onChange={set("title")}
                     placeholder="Ex. Revue de conception — télécommande" />
            </label>
            <label>
              <span className="mb-1 block text-sm text-ink-2">Mission / projet</span>
              <input className={field} list="missions" value={meta.mission ?? ""}
                     onChange={set("mission")} placeholder="Ex. ES2002" />
              <datalist id="missions">
                {missions.map((m) => <option key={m} value={m} />)}
              </datalist>
            </label>
            <label>
              <span className="mb-1 block text-sm text-ink-2">Date de l'enregistrement</span>
              <input type="date" className={field} value={meta.date ?? ""} onChange={set("date")} />
            </label>
            <label>
              <span className="mb-1 block text-sm text-ink-2">Auteur / intervenant principal</span>
              <input className={field} value={meta.author ?? ""} onChange={set("author")}
                     placeholder="Ex. Laura Martin" />
            </label>
            <label>
              <span className="mb-1 block text-sm text-ink-2">Contact</span>
              <input className={field} value={meta.contact ?? ""} onChange={set("contact")}
                     placeholder="Ex. laura.martin@… ou poste" />
            </label>
            <label className="sm:col-span-2">
              <span className="mb-1 block text-sm text-ink-2">Description</span>
              <textarea className={`${field} resize-none`} rows={3} value={meta.description ?? ""}
                        onChange={set("description")}
                        placeholder="De quoi parle cet enregistrement ? Décisions, problème traité…" />
            </label>
            <label>
              <span className="mb-1 block text-sm text-ink-2">Langue</span>
              <select className={field} value={meta.language ?? "auto"} onChange={set("language")}>
                {LANGUAGES.map((l) => <option key={l.value} value={l.value}>{l.label}</option>)}
              </select>
            </label>
            <div className="flex items-end">
              <button
                type="submit"
                disabled={!file || busy}
                className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-4
                           py-2 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover
                           disabled:cursor-not-allowed disabled:opacity-40"
              >
                {busy ? "Traitement…" : "Importer"}
                <Icon.upload />
              </button>
            </div>
          </fieldset>
        </Card>
      </form>

      {stage === "duplicate" && job?.duplicate_of && (
        <div className="anim-in rounded-xl border border-warn-line bg-warn-soft p-4 text-sm">
          <p className="font-medium text-warn">Contenu déjà présent — rien n'a été ajouté à l'index</p>
          <p className="mt-1 text-ink-2">
            {Math.round((job.similarity ?? 0) * 100)} % de ce transcript existe déjà dans «{" "}
            {titleOf(job.duplicate_of, videos)} ». Le fichier a été mis de côté (dossier
            <code className="mx-1 rounded bg-surface-2 px-1">data/duplicates/</code>), pas supprimé.
          </p>
        </div>
      )}

      {stage !== "idle" && stage !== "duplicate" && (
        <Card className="anim-in p-5">
          <p className="mb-4 truncate text-sm font-medium text-ink">{meta.title || file?.name}</p>
          {stage === "uploading" && (
            <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-surface-2">
              <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${pct}%` }} />
            </div>
          )}
          <Steps steps={steps} />
          {stage === "done" && (
            <p className="mt-4 text-sm text-ok">
              Prête : posez vos questions dans Recherche. Seul ce fichier a été indexé.
            </p>
          )}
          {error && <p className="mt-4 text-sm text-danger">{error}</p>}
          <p className="mt-4 text-xs text-muted">
            Sur CPU, la transcription prend environ un tiers de la durée de l'enregistrement.
          </p>
        </Card>
      )}
    </div>
  );
}
