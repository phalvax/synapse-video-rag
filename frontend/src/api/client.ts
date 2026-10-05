// Couche d'accès à l'API. FE-2 : branché sur le vrai backend FastAPI (Phase 6,
// src/kb/api/app.py), via le proxy Vite /api -> http://localhost:8000 (vite.config.ts).
// Les signatures n'ont pas changé depuis la version "mocks d'abord" (FE-1) : les composants
// n'ont rien à savoir du transport.
import type {
  AskRequest, Answer, FicheREX, Job, Kpis, MissionInfo, MissionRecap, RiskCoveragePoint, Segment,
  TierRow, UploadMeta, Video,
} from "../types";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: init?.body && !(init.body instanceof FormData)
      ? { "Content-Type": "application/json" }
      : undefined,
    ...init,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(detail?.detail ?? `${res.status} ${res.statusText} — ${path}`);
  }
  return res.json();
}

export async function listVideos(): Promise<Video[]> {
  return api<Video[]>("/videos");
}

export async function getVideo(videoId: string): Promise<Video | undefined> {
  try {
    return await api<Video>(`/videos/${encodeURIComponent(videoId)}`);
  } catch {
    return undefined;
  }
}

export async function getFiches(videoId?: string): Promise<FicheREX[]> {
  return videoId
    ? api<FicheREX[]>(`/videos/${encodeURIComponent(videoId)}/fiches`)
    : api<FicheREX[]>("/fiches");
}

export async function ask(req: AskRequest): Promise<Answer> {
  return api<Answer>("/ask", { method: "POST", body: JSON.stringify(req) });
}

/** Golden set sur lequel lire les indicateurs : talks TED (défaut) ou réunions AMI. */
export type Corpus = "ted" | "ami";

interface MetricsResponse {
  kpis: Kpis;
  sources: Record<string, string>;
  risk_coverage: RiskCoveragePoint[] | null;
  corpus?: Corpus;
}

export async function getMetrics(corpus: Corpus = "ted"): Promise<MetricsResponse> {
  return api<MetricsResponse>(`/metrics?corpus=${corpus}`);
}

export async function getSegments(videoId: string): Promise<Segment[]> {
  return api<Segment[]>(`/videos/${encodeURIComponent(videoId)}/segments`);
}

export async function getTiers(): Promise<TierRow[]> {
  const { rows } = await api<{ rows: TierRow[]; missing: string[] }>("/tiers");
  return rows;
}

export async function uploadVideo(
  file: File,
  onProgress: (pct: number) => void,
  meta: UploadMeta = {}
): Promise<{ job_id: string; video_id: string }> {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(meta)) if (v) form.append(k, v);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText));
      else {
        // 409 doublon / nom pris, 415 format, 422 formulaire : le message du serveur est explicite.
        let detail = `${xhr.status} ${xhr.statusText}`;
        try {
          detail = JSON.parse(xhr.responseText).detail ?? detail;
        } catch {
          // réponse non JSON : on garde le statut HTTP
        }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("Échec de l'envoi (réseau)"));
    xhr.open("POST", "/api/videos");
    xhr.send(form);
  });
}

export async function getJobStatus(jobId: string): Promise<Job> {
  return api<Job>(`/jobs/${encodeURIComponent(jobId)}`);
}

export async function listMissions(): Promise<MissionInfo[]> {
  return api<MissionInfo[]>("/missions");
}

export async function getMissionRecap(mission: string): Promise<MissionRecap> {
  return api<MissionRecap>(`/missions/${encodeURIComponent(mission)}/recap`);
}
