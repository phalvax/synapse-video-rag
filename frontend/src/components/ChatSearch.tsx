import { useEffect, useRef, useState } from "react";
import { ask } from "../api/client";
import type { Answer, Mode, Video } from "../types";
import { NATURE, fmtLoc, titleOf } from "../utils";
import { Badge, Card, ConfidenceBar, Hint, Icon, Segmented, SourceCard, Steps, type StepState } from "./ui";

interface Props {
  videos: Video[];
  onCitationClick: (videoId: string, startS: number, page?: number | null) => void;
  /** Vidéo du lecteur quand « Chercher seulement dans cette vidéo » est coché. */
  scopeVideoId?: string;
  /** Ouvre l'écran Point mission sur cette mission. */
  onOpenMission?: (mission: string) => void;
}

const EXAMPLES = [
  "Quel est le prix de vente de la télécommande ?",
  "Fais-moi un point sur la mission ES2004",
  "What did the team decide about the buttons?",
  "Quelle forme de télécommande a été proposée dans ES2002 ?",
];

const MODES: { value: Mode; label: string }[] = [
  { value: "synthese", label: "Synthèse" },
  { value: "strict", label: "Strict" },
];

const MODE_HELP =
  "Synthèse : le LLM rédige une réponse courte, chaque citation est vérifiée mot pour mot dans " +
  "le transcript. Strict : uniquement des extraits exacts du transcript, aucun texte généré.";

export default function ChatSearch({ videos, onCitationClick, scopeVideoId, onOpenMission }: Props) {
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("synthese");
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asked, setAsked] = useState("");
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [duration, setDuration] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(0);

  useEffect(() => {
    if (!loading) return;
    const id = setInterval(() => setElapsed((Date.now() - started.current) / 1000), 250);
    return () => clearInterval(id);
  }, [loading]);

  async function run(q: string) {
    if (!q.trim() || loading) return;
    setQuestion(q);
    setAsked(q);
    setLoading(true);
    setError(null);
    setAnswer(null);
    setElapsed(0);
    started.current = Date.now();
    try {
      const filters = scopeVideoId ? { video_id: scopeVideoId } : null;
      setAnswer(await ask({ question: q, mode, filters }));
      setDuration((Date.now() - started.current) / 1000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erreur inconnue");
    } finally {
      setLoading(false);
    }
  }

  const title = (id: string) => titleOf(id, videos);
  const empty = !answer && !loading && !error;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">
          Retrouvez une info dans vos réunions
        </h1>
        <p className="mt-1 text-[15px] text-muted">Avec la preuve et la minute exacte.</p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(question);
        }}
      >
        <Card className="p-2 focus-within:border-accent">
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                run(question);
              }
            }}
            placeholder="Posez votre question… (Entrée pour envoyer)"
            rows={2}
            aria-label="Question"
            className="w-full resize-none bg-transparent px-3 py-2 text-[16px] text-ink
                       placeholder:text-muted focus:outline-none"
          />
          <div className="flex items-center gap-3 px-1 pb-1">
            <Segmented label="Mode de réponse" options={MODES} value={mode} onChange={setMode} />
            <Hint text={MODE_HELP} />
            {scopeVideoId && (
              <Badge tone="accent">Dans : {title(scopeVideoId)}</Badge>
            )}
            <button
              type="submit"
              disabled={loading || !question.trim()}
              className="ml-auto inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm
                         font-medium text-accent-ink transition-colors hover:bg-accent-hover
                         disabled:cursor-not-allowed disabled:opacity-40"
            >
              {loading ? "Recherche…" : "Demander"}
              <Icon.send />
            </button>
          </div>
        </Card>
      </form>

      {empty && (
        <div className="anim-in">
          <p className="mb-2 text-sm text-muted">Essayez :</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => run(ex)}
                className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-ink-2
                           transition-colors hover:border-accent hover:text-accent"
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      {loading && <Waiting mode={mode} elapsed={elapsed} />}

      {error && (
        <Card className="anim-in border-danger/40 bg-danger-soft p-4 text-sm text-danger">
          Erreur : {error}
        </Card>
      )}

      {answer && (
        <AnswerView
          answer={answer}
          question={asked}
          duration={duration}
          title={title}
          onCitationClick={onCitationClick}
          onOpenMission={onOpenMission}
        />
      )}
    </div>
  );
}

/** Étapes indicatives (estimées d'après le temps écoulé : le serveur ne les diffuse pas). */
function Waiting({ mode, elapsed }: { mode: Mode; elapsed: number }) {
  const labels =
    mode === "strict"
      ? ["Traduction de la question", "Recherche des passages", "Sélection des extraits exacts"]
      : [
          "Traduction de la question",
          "Recherche des passages",
          "Rédaction de la réponse",
          "Vérification des citations",
        ];
  const current = elapsed < 3 ? 0 : elapsed < 15 || mode === "strict" ? 1 : 2;
  const steps = labels.map((label, i) => ({
    label,
    state: (i < current ? "done" : i === current ? "active" : "todo") as StepState,
    detail: i === current ? `${Math.floor(elapsed)} s` : undefined,
  }));
  return (
    <Card className="anim-in p-5">
      <Steps steps={steps} />
      <p className="mt-4 text-xs text-muted">
        Étapes indicatives · LLM local sur CPU : compter 40 s à 2 min pour une réponse rédigée.
      </p>
    </Card>
  );
}

function AnswerView({
  answer,
  question,
  duration,
  title,
  onCitationClick,
  onOpenMission,
}: {
  answer: Answer;
  question: string;
  duration: number | null;
  title: (id: string) => string;
  onCitationClick: (videoId: string, startS: number, page?: number | null) => void;
  onOpenMission?: (mission: string) => void;
}) {
  const took = duration !== null && (
    <span className="text-xs text-muted">
      Réponse en {Math.max(1, Math.round(duration))} s
      {answer.model && ` · ${answer.model.split(":").pop()}`}
    </span>
  );

  if (answer.not_found) {
    const leads = answer.leads ?? [];
    // Deux motifs différents : rien d'assez pertinent (le LLM n'est même pas appelé), ou une
    // réponse rédigée dont aucune citation n'a été retrouvée mot pour mot.
    const beforeLlm = (answer.note ?? "").includes("avant génération");
    return (
      <section className="anim-in flex flex-col gap-3">
        <div className="rounded-xl border border-warn-line bg-warn-soft p-4">
          <div className="flex items-start gap-3 text-warn">
            <Icon.alert />
            <div className="min-w-0 flex-1">
              <p className="font-medium">Pas de réponse prouvée</p>
              <p className="mt-0.5 text-sm text-ink-2">
                {beforeLlm
                  ? "Aucun passage assez pertinent dans les enregistrements : l'outil ne rédige rien plutôt que d'inventer."
                  : "Aucune citation de la réponse rédigée n'a été retrouvée mot pour mot : l'outil préfère ne pas répondre plutôt que d'inventer."}
              </p>
              {answer.note && <p className="mt-2 text-xs text-muted">{answer.note}</p>}
            </div>
            {took}
          </div>
        </div>
        {leads.length > 0 && (
          <>
            <p className="text-sm text-muted">
              Passages les plus proches — extraits exacts, à vérifier vous-même :
            </p>
            {leads.map((l, i) => (
              <SourceCard
                key={i}
                title={title(l.video_id)}
                time={fmtLoc(l)}
                quote={l.text}
                badge={
                  <Badge>
                    piste{l.modality ? ` · ${NATURE[l.modality] ?? l.modality}` : ""}
                    {l.score !== null ? ` · score ${l.score.toFixed(2)}` : ""}
                  </Badge>
                }
                onPlay={() => onCitationClick(l.video_id, l.start_s, l.page)}
              />
            ))}
          </>
        )}
      </section>
    );
  }

  const strict = (answer.answer ?? "").startsWith("[mode strict]");
  return (
    <section className="anim-in flex flex-col gap-3">
      <Card className="p-5">
        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">{question}</p>
        {answer.mission && (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <Badge tone="accent">Point mission {answer.mission} · synthèse générée</Badge>
            {onOpenMission && (
              <button
                onClick={() => onOpenMission(answer.mission!)}
                className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
              >
                Ouvrir le point mission complet <Icon.arrow />
              </button>
            )}
          </div>
        )}
        {answer.citations.length > 0 && answer.citations.every((c) => c.modality === "visual") && (
          <div className="mb-3 flex gap-2 rounded-lg border border-warn-line bg-warn-soft p-3 text-sm text-warn">
            <Icon.alert />
            <span>
              Cette réponse ne s'appuie que sur une <strong>description d'image générée par l'IA</strong>,
              pas sur un texte original : vérifiez-la sur l'image avant de vous y fier.
            </span>
          </div>
        )}
        {strict ? (
          <p className="text-[15px] text-ink-2">
            Mode strict : voici les extraits exacts du transcript, sans aucun texte généré.
          </p>
        ) : (
          <p className="text-[17px] leading-relaxed text-ink">
            {/* Les renvois [S1] servent au contrôle des citations ; les preuves sont listées dessous. */}
            {(answer.answer ?? "").replace(/\s*\[S\d+\]/g, "")}
          </p>
        )}
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
          {answer.mission ? (
            <span className="text-xs text-muted">{answer.note}</span>
          ) : (
            <ConfidenceBar score={answer.confidence} />
          )}
          {took}
        </div>
      </Card>

      {answer.citations.length > 0 && (
        <>
          <h3 className="mt-2 text-sm font-semibold text-ink">
            {strict
              ? "Extraits"
              : answer.citations.every((c) => c.modality === "visual")
                ? "Sources (descriptions générées)"
                : "Sources vérifiées"}{" "}
            ({answer.citations.length})
          </h3>
          {answer.citations.map((c, i) => (
            <SourceCard
              key={i}
              title={title(c.video_id)}
              time={fmtLoc(c)}
              quote={c.quote}
              badge={
                !c.verified ? (
                  <Badge tone="warn">non vérifiée</Badge>
                ) : c.modality === "visual" ? (
                  // Texte GÉNÉRÉ par le LLM de vision : retrouvé dans la source, mais pas une preuve.
                  <Badge tone="warn">{NATURE.visual}</Badge>
                ) : (
                  <Badge tone="ok">
                    <span className="scale-75">
                      <Icon.check />
                    </span>
                    {c.modality === "ocr" ? `vérifiée · ${NATURE.ocr}` : "vérifiée"}
                  </Badge>
                )
              }
              onPlay={() => onCitationClick(c.video_id, c.start_s, c.page)}
            />
          ))}
        </>
      )}
    </section>
  );
}
