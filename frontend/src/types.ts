// Miroir de src/kb/schemas.py (CONTRAT COMMUN) — ne pas diverger sans accord de l'équipe.

export interface Video {
  video_id: string;
  title: string;
  source_uri: string;
  duration_s: number;
  date: string | null;
  author: string | null;
  client: string | null;
  mission: string | null;
  language: string | null;
  /** Saisis dans le formulaire d'import (absents pour les anciennes vidéos). */
  description?: string | null;
  contact?: string | null;
  /** « video », « audio », « document » (PDF), « image » ; absent = ancien média. */
  kind?: string | null;
}

export interface Citation {
  chunk_id: string;
  video_id: string;
  start_s: number;
  quote: string;
  verified: boolean;
  /** Documents : la page à ouvrir (au lieu d'une seconde). */
  page?: number | null;
  /** « ocr » : texte lu dans une image ; « visual » : description GÉNÉRÉE d'une image. */
  modality?: string | null;
}

export interface Answer {
  answer: string | null;
  not_found: boolean;
  confidence: number;
  citations: Citation[];
  /** Passages proches renvoyés quand l'agent s'abstient (transcript exact, pas une preuve). */
  leads?: Lead[];
  /** Pourquoi l'agent s'est abstenu. */
  note?: string;
  /** Question réellement cherchée (traduite dans la langue du corpus). */
  search_query?: string | null;
  /** Rempli quand la question a été routée vers le point mission (L3). */
  mission?: string | null;
  /** Modèle qui a réellement répondu (preuve que la sélection de modèle a joué). */
  model?: string | null;
}

export interface Lead {
  video_id: string;
  start_s: number;
  text: string;
  score: number | null;
  page?: number | null;
  modality?: string | null;
}

export interface Segment {
  video_id: string;
  seg_id: number;
  start_s: number;
  end_s: number;
  text: string;
  speaker: string | null;
  avg_logprob: number | null;
  page?: number | null;
  modality?: string | null;
}

export interface FicheREX {
  fiche_id: string;
  video_id: string;
  problem: string;
  solution: string | null;
  technologies: string[];
  client: string | null;
  author: string | null;
  start_s: number;
  end_s: number;
  evidence_quote: string;
}

export type Mode = "synthese" | "strict";
export type Profile = "free" | "dataiku" | "market";

export interface AskRequest {
  question: string;
  mode: Mode;
  filters: Record<string, string> | null;
  /** Omis : le backend prend le profil par défaut (le sélecteur de palier a été retiré du front). */
  profile?: Profile;
}

export interface Job {
  id: string;
  status: "queued" | "transcribing" | "indexing" | "done" | "failed" | "duplicate";
  video_id: string | null;
  error: string | null;
  /** Quasi-doublon : enregistrement qui contient déjà ce contenu, et part commune (0 à 1). */
  duplicate_of?: string | null;
  similarity?: number | null;
  created_at: number;
  updated_at: number;
}

export interface Kpis {
  wer: number | null;
  recall_at_5: number | null;
  moment_precision: number | null;
  faithfulness: number | null;
  hallucination_rate: number | null;
  abstention_correct: number | null;
  false_abstention: number | null;
  latency_p95_s: number | null;
  cost_per_question_usd: number | null;
  time_manual_min: number | null;
  time_tool_s: number | null;
}

export interface RiskCoveragePoint {
  threshold: number;
  coverage: number;
  risk: number;
}

export interface TierRow {
  profile: string;
  model: string;
  n: number;
  coverage: number;
  moment_hit: number;
  avg_cost_usd: number;
  cost_per_1000q_usd: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
}

// --- Point mission (L3) : GET /missions, GET /missions/{m}/recap ---------------------------

export type PointKind = "decision" | "progress" | "issue" | "next_step" | "info";

export interface Evidence {
  video_id: string;
  start_s: number;
  /** Extrait EXACT du transcript. */
  quote: string;
  page?: number | null;
}

export interface RecapPoint {
  kind: PointKind;
  /** Formulé par le LLM ; la preuve est `evidence`. */
  text: string;
  evidence: Evidence;
}

export interface VideoRecap {
  video_id: string;
  title: string;
  subject: string;
  summary: string;
  participants: string[];
  key_points: RecapPoint[];
  dropped_points: number;
}

export interface MissionRecap {
  mission: string;
  videos: VideoRecap[];
  subject: string;
  status: string;
  decisions: RecapPoint[];
  open_issues: RecapPoint[];
  next_steps: RecapPoint[];
  model: string;
  generated_at: string;
}

export interface MissionInfo {
  mission: string;
  video_ids: string[];
  recap_available: boolean;
  generated_at: string | null;
}

/** Formulaire d'import : contexte saisi par l'humain (tous les champs sont facultatifs). */
export interface UploadMeta {
  title?: string;
  author?: string;
  date?: string; // AAAA-MM-JJ
  mission?: string;
  contact?: string;
  description?: string;
  language?: "auto" | "fr" | "en" | "de" | "es" | "it";
}
