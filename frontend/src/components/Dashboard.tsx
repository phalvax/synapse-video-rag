import { useEffect, useRef, useState } from "react";
import { getMetrics, getTiers, type Corpus } from "../api/client";
import type { Kpis, RiskCoveragePoint, TierRow } from "../types";
import { Card, SectionTitle, Segmented } from "./ui";

// Palette catégorielle dataviz (3 premiers slots, validés all-pairs en clair ET en sombre sur nos
// fonds — validate_palette.js). Les valeurs vivent dans index.css (--series-1..3) : elles suivent
// le thème. La couleur suit l'entité (le palier), jamais son rang.
const SERIES: Record<string, string> = {
  free: "var(--series-1)",
  "dataiku · Luna": "var(--series-2)",
  "dataiku · Sol": "var(--series-3)",
};

const CORPORA: { value: Corpus; label: string }[] = [
  { value: "ted", label: "Talks TED" },
  { value: "ami", label: "Réunions AMI" },
];

const CORPUS_HINT: Record<Corpus, string> = {
  ted: "3 talks préparés, en anglais — le cas facile.",
  ami: "8 réunions d'ingénieurs spontanées, 2 équipes — le cas proche de Synchrone.",
};

function pct(v: number | null): string {
  return v === null ? "non mesuré" : `${(v * 100).toFixed(0)} %`;
}

function seconds(v: number | null): string {
  return v === null ? "non mesuré" : `${v.toFixed(1)} s`;
}

const MAX_CURVE_ROWS = 10;

/** Un point par score distinct (parfois des dizaines) : on en garde ~10, premier et dernier inclus. */
function sampleCurve(points: RiskCoveragePoint[]): RiskCoveragePoint[] {
  if (points.length <= MAX_CURVE_ROWS) return points;
  const step = (points.length - 1) / (MAX_CURVE_ROWS - 1);
  return Array.from({ length: MAX_CURVE_ROWS }, (_, i) => points[Math.round(i * step)]);
}

function kpiCards(k: Kpis): { label: string; value: string; hint: string }[] {
  return [
    { label: "WER", value: pct(k.wer), hint: "erreurs de transcription" },
    { label: "Recall@5", value: pct(k.recall_at_5), hint: "bon passage dans les 5 premiers" },
    { label: "Précision du moment", value: pct(k.moment_precision), hint: "bonne minute, ±30 s" },
    { label: "Faithfulness", value: pct(k.faithfulness), hint: "juge LLM — pas encore fait" },
    { label: "Hallucination", value: pct(k.hallucination_rate), hint: "juge LLM — pas encore fait" },
    { label: "Abstention correcte", value: pct(k.abstention_correct), hint: "questions sans réponse" },
    { label: "Latence p95", value: seconds(k.latency_p95_s), hint: "LLM local sur CPU" },
    {
      label: "Temps de recherche",
      hint: "à la main vs outil — pas encore chronométré",
      value: k.time_manual_min === null || k.time_tool_s === null
        ? "non mesuré" : `${k.time_manual_min} min → ${k.time_tool_s} s`,
    },
  ];
}

const EMPTY_KPIS: Kpis = {
  wer: null, recall_at_5: null, moment_precision: null, faithfulness: null,
  hallucination_rate: null, abstention_correct: null, false_abstention: null,
  latency_p95_s: null, cost_per_question_usd: null, time_manual_min: null, time_tool_s: null,
};

export default function Dashboard() {
  const [corpus, setCorpus] = useState<Corpus>("ted");
  const [kpis, setKpis] = useState<Kpis>(EMPTY_KPIS);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [riskCoverage, setRiskCoverage] = useState<RiskCoveragePoint[] | null>(null);
  const [tiers, setTiers] = useState<TierRow[]>([]);

  useEffect(() => {
    getMetrics(corpus)
      .then((m) => {
        setKpis(m.kpis);
        setSources(m.sources ?? {});
        setRiskCoverage(m.risk_coverage);
      })
      .catch(console.error);
  }, [corpus]);

  useEffect(() => {
    getTiers().then(setTiers).catch(console.error);
  }, []);

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Indicateurs</h1>
          <p className="mt-1 text-[15px] text-muted">
            Mesurés sur notre golden set — {CORPUS_HINT[corpus]}
          </p>
        </div>
        <Segmented label="Corpus" options={CORPORA} value={corpus} onChange={setCorpus} />
      </header>

      <section key={corpus} className="anim-in">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {kpiCards(kpis).map((k) => {
            const missing = k.value === "non mesuré";
            return (
              <Card key={k.label} className="p-4">
                <p className="text-sm font-medium text-ink-2">{k.label}</p>
                <p
                  className={missing
                    ? "mt-2 text-base italic text-muted"
                    : "mt-1.5 text-3xl font-semibold tracking-tight tabular-nums text-ink"}
                >
                  {k.value}
                </p>
                <p className="mt-1 text-xs text-muted">{k.hint}</p>
              </Card>
            );
          })}
        </div>
        <p className="mt-3 text-xs text-muted">
          Rapports : {Object.values(sources).join(" · ") || "aucun pour ce corpus"}
          {corpus === "ami" && !sources.agent &&
            " — l'agent n'a pas encore été évalué sur AMI (abstention, latence : non mesurés)."}
        </p>
      </section>

      <section>
        <SectionTitle hint="Chaque palier : couverture (réponses prouvées) selon le coût par 1 000 questions (échelle log). Seuls les paliers mesurés apparaissent — mesurés sur le golden set TED, quel que soit le corpus choisi plus haut.">
          Frontière coût-qualité (talks TED)
        </SectionTitle>
        <Card className="p-4">
          <TiersChart rows={tiers} />
          <table className="mt-4 w-full text-left text-sm">
            <thead className="text-muted">
              <tr>
                <th className="py-2 pr-4 font-medium">Palier</th>
                <th className="py-2 pr-4 font-medium">Modèle</th>
                <th className="py-2 pr-4 font-medium">Couverture</th>
                <th className="py-2 pr-4 font-medium">Coût / 1 000 questions</th>
              </tr>
            </thead>
            <tbody className="tabular-nums text-ink-2">
              {tiers.map((r) => (
                <tr key={`${r.profile}-${r.model}`} className="border-t border-line">
                  <td className="py-2 pr-4 text-ink">{r.profile}</td>
                  <td className="py-2 pr-4">{r.model}</td>
                  <td className="py-2 pr-4">{pct(r.coverage)}</td>
                  <td className="py-2 pr-4">{r.cost_per_1000q_usd.toFixed(2)} $</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </section>

      {riskCoverage && (
        <section>
          <SectionTitle
            hint={`Répondre si le score de recherche ≥ seuil. Risque = part des réponses données qui sont fausses. Sert à calibrer le seuil d'abstention. ${riskCoverage.length} seuils mesurés, ${Math.min(riskCoverage.length, MAX_CURVE_ROWS)} affichés.`}
          >
            Courbe risque-couverture
          </SectionTitle>
          <Card className="overflow-hidden">
            <table className="w-full text-left text-sm">
              <thead className="bg-surface-2 text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Seuil</th>
                  <th className="px-4 py-2 font-medium">Couverture</th>
                  <th className="px-4 py-2 font-medium">Risque</th>
                </tr>
              </thead>
              <tbody className="tabular-nums text-ink-2">
                {sampleCurve(riskCoverage).map((p) => (
                  <tr key={p.threshold} className="border-t border-line">
                    <td className="px-4 py-2">{p.threshold.toFixed(3)}</td>
                    <td className="px-4 py-2">{pct(p.coverage)}</td>
                    <td className="px-4 py-2">{pct(p.risk)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </section>
      )}
    </div>
  );
}

function seriesKey(r: TierRow): string {
  return r.model.includes("luna") || r.model.includes("Luna") ? "dataiku · Luna"
    : r.model.includes("sol") || r.model.includes("Sol") ? "dataiku · Sol" : "free";
}

function TiersChart({ rows }: { rows: TierRow[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);

  // Le repère SVG suit la largeur réelle : les textes gardent leur taille à 1 024 comme à 1 440 px.
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(320, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [rows.length > 0]); // le conteneur n'existe qu'une fois les paliers chargés

  if (rows.length === 0) {
    return <p className="py-8 text-center text-sm text-muted">Aucun palier mesuré.</p>;
  }
  const W = width;
  const H = 260;
  const PAD = { top: 20, right: 90, bottom: 36, left: 48 };
  const xOf = (costPer1000: number) => Math.log10(costPer1000 + 0.1);
  const xs = rows.map((r) => xOf(r.cost_per_1000q_usd));
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const scaleX = (x: number) =>
    xMax === xMin ? (PAD.left + W - PAD.right) / 2
      : PAD.left + ((x - xMin) / (xMax - xMin)) * (W - PAD.left - PAD.right);
  const scaleY = (coverage: number) => H - PAD.bottom - coverage * (H - PAD.top - PAD.bottom);
  const keys = [...new Set(rows.map(seriesKey))];

  return (
    <div ref={box} className="relative">
      {keys.length >= 2 && (
        <div className="mb-2 flex gap-4 text-xs text-ink-2">
          {keys.map((k) => (
            <span key={k} className="flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: SERIES[k] }} />
              {k}
            </span>
          ))}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img"
           aria-label="Couverture en fonction du coût par 1000 questions, échelle logarithmique">
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={g}>
            <line x1={PAD.left} x2={W - PAD.right} y1={scaleY(g)} y2={scaleY(g)}
                  stroke="var(--line)" strokeWidth={1} />
            <text x={PAD.left - 8} y={scaleY(g) + 4} fontSize={11} textAnchor="end"
                  fill="var(--muted)">
              {g * 100} %
            </text>
          </g>
        ))}
        <text x={PAD.left} y={H - 8} fontSize={11} fill="var(--muted)">
          coût / 1 000 questions (échelle log) →
        </text>
        {rows.map((r, i) => {
          const key = seriesKey(r);
          const cx = scaleX(xOf(r.cost_per_1000q_usd));
          const cy = scaleY(r.coverage);
          return (
            <g key={`${r.profile}-${r.model}`}
               onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <circle cx={cx} cy={cy} r={16} fill="transparent" />
              <circle cx={cx} cy={cy} r={6} fill={SERIES[key]} stroke="var(--surface)" strokeWidth={2} />
              <text x={cx + 11} y={cy + 4} fontSize={12} fill="var(--ink-2)">
                {key === "free" ? "free (gemma3:4b)" : key}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <div className="pointer-events-none absolute right-2 top-2 rounded-lg border border-line bg-surface
                        px-3 py-2 text-xs text-ink-2 shadow-card">
          <p className="font-medium text-ink">{rows[hover].profile} · {rows[hover].model}</p>
          <p className="tabular-nums">
            Couverture {pct(rows[hover].coverage)} · {rows[hover].cost_per_1000q_usd.toFixed(2)} $ / 1 000 q.
          </p>
        </div>
      )}
    </div>
  );
}
