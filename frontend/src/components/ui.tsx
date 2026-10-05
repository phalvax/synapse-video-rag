// Petit kit d'interface RAG16 : tout passe par les rôles de couleur de index.css.
import type { ReactNode, SVGProps } from "react";

// --- Icônes (traits fins, 20 px) -------------------------------------------------------------

function Svg(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={20}
      height={20}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  );
}

export const Icon = {
  search: () => (
    <Svg>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </Svg>
  ),
  mission: () => (
    <Svg>
      <path d="M4 5h16M4 12h10M4 19h7" />
      <circle cx="18" cy="17" r="3" />
    </Svg>
  ),
  upload: () => (
    <Svg>
      <path d="M12 16V4m0 0-4 4m4-4 4 4" />
      <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
    </Svg>
  ),
  chart: () => (
    <Svg>
      <path d="M4 20V10m6 10V4m6 16v-7m4 7H3" />
    </Svg>
  ),
  sun: () => (
    <Svg>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Svg>
  ),
  moon: () => (
    <Svg>
      <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
    </Svg>
  ),
  play: () => (
    <Svg viewBox="0 0 24 24" fill="currentColor" stroke="none">
      <path d="M8 5.5v13a1 1 0 0 0 1.5.9l10-6.5a1 1 0 0 0 0-1.7l-10-6.5A1 1 0 0 0 8 5.5Z" />
    </Svg>
  ),
  check: () => (
    <Svg>
      <path d="m5 12.5 4.5 4.5L19 7.5" />
    </Svg>
  ),
  alert: () => (
    <Svg>
      <path d="M12 4 2.5 20h19L12 4Z" />
      <path d="M12 10v4m0 3h.01" />
    </Svg>
  ),
  arrow: () => (
    <Svg>
      <path d="M5 12h14m-5-5 5 5-5 5" />
    </Svg>
  ),
  info: () => (
    <Svg>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5m0-8h.01" />
    </Svg>
  ),
  send: () => (
    <Svg>
      <path d="M5 12h13m-5-6 6 6-6 6" />
    </Svg>
  ),
  wave: () => (
    <Svg>
      <path d="M3 12h2m3-5v10m4-13v16m4-11v6m4-3h1" />
    </Svg>
  ),
};

// --- Briques ---------------------------------------------------------------------------------

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-line bg-surface shadow-card ${className}`}>
      {children}
    </div>
  );
}

type Tone = "neutral" | "ok" | "warn" | "accent";

const TONE: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2",
  ok: "bg-ok-soft text-ok",
  warn: "bg-warn-soft text-warn",
  accent: "bg-accent-soft text-accent",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3">
      <h2 className="text-sm font-semibold tracking-tight text-ink">{children}</h2>
      {hint && <p className="mt-0.5 text-sm text-muted">{hint}</p>}
    </div>
  );
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg bg-surface-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            value === o.value
              ? "bg-surface text-ink shadow-card"
              : "text-muted hover:text-ink"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Info-bulle au survol / focus (texte court). */
export function Hint({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex">
      <button type="button" aria-label={text} className="text-muted hover:text-ink">
        <Icon.info />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full left-1/2 z-20 mb-2 w-64 -translate-x-1/2
                   rounded-lg bg-ink px-3 py-2 text-xs leading-relaxed text-surface opacity-0
                   shadow-card transition-opacity group-hover:opacity-100 group-focus-within:opacity-100"
      >
        {text}
      </span>
    </span>
  );
}

/** Score de recherche (reranker) — un score, pas une probabilité. */
export function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(1, score)) * 100;
  return (
    <div
      className="flex items-center gap-2 text-xs text-muted"
      title="Score du reranker pour le meilleur passage : un score de pertinence, pas une probabilité."
    >
      <span>Score de recherche</span>
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-surface-2">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular-nums text-ink-2">{score.toFixed(2)}</span>
      <span>· pas une probabilité</span>
    </div>
  );
}

/** Carte « source » : un extrait EXACT du transcript, cliquable → lecteur à la bonne seconde. */
export function SourceCard({
  title,
  time,
  quote,
  badge,
  heading,
  onPlay,
}: {
  title: string;
  time: string;
  quote: string;
  badge?: ReactNode;
  heading?: ReactNode;
  onPlay: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onPlay}
      className="anim-in group flex w-full gap-3 rounded-xl border border-line bg-surface p-3.5 text-left
                 transition-colors hover:border-accent hover:bg-accent-soft/40"
    >
      <span
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft
                   text-accent transition-colors group-hover:bg-accent group-hover:text-accent-ink"
      >
        <span className="scale-75">
          <Icon.play />
        </span>
      </span>
      <span className="min-w-0 flex-1">
        {heading && <span className="mb-1 block text-[15px] font-medium text-ink">{heading}</span>}
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <span className="font-medium text-ink-2">{title}</span>
          <span className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs tabular-nums text-ink-2">
            {time}
          </span>
          {badge}
        </span>
        <span className="mt-1.5 line-clamp-3 block text-sm italic leading-relaxed text-muted">
          « {quote} »
        </span>
      </span>
    </button>
  );
}

export type StepState = "done" | "active" | "todo";

/** Étapes qui s'allument (attente d'une réponse, traitement d'un upload). */
export function Steps({ steps }: { steps: { label: string; state: StepState; detail?: string }[] }) {
  return (
    <ol className="flex flex-col gap-2.5">
      {steps.map((s) => (
        <li key={s.label} className="flex items-center gap-3 text-sm">
          <span
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${
              s.state === "done"
                ? "border-ok bg-ok text-surface"
                : s.state === "active"
                  ? "anim-pulse border-accent text-accent"
                  : "border-line-strong text-transparent"
            }`}
          >
            {s.state === "done" ? (
              <span className="scale-75">
                <Icon.check />
              </span>
            ) : (
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
            )}
          </span>
          <span className={s.state === "todo" ? "text-muted" : "text-ink"}>{s.label}</span>
          {s.detail && <span className="ml-auto tabular-nums text-muted">{s.detail}</span>}
        </li>
      ))}
    </ol>
  );
}
