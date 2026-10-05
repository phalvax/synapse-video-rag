import type { Video } from "./types";

export function fmtTs(seconds: number): string {
  const s = Math.floor(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
    : `${m}:${String(sec).padStart(2, "0")}`;
}

const AMI = /^ami_(es\d{4})([a-z])$/i;
const AUDIO_EXT = /\.(wav|mp3|m4a|flac|ogg|opus|aac|wma)$/i;

/** Titre lisible : « Réunion 1 · ES2002 » plutôt que « ami_es2002a » ; pour un talk
 * (« joshua prager wisdom from… ») : « Joshua Prager — Wisdom from… ». */
export function prettyTitle(video: Pick<Video, "video_id" | "title">): string {
  // Un titre saisi dans le formulaire d'import prime toujours : il est affiché tel quel.
  const fromFileName = slug(video.title) === video.video_id;
  if (!fromFileName) return video.title.trim();
  const ami = AMI.exec(video.video_id);
  if (ami) {
    const n = ami[2].toLowerCase().charCodeAt(0) - 96;
    return `Réunion ${n} · ${ami[1].toUpperCase()}`;
  }
  const words = video.title.trim().split(/\s+/);
  const cap = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);
  // « Prénom Nom — sujet » seulement pour un titre déduit du nom de fichier (talk TED).
  if (words.length >= 5 && !/\d/.test(video.title)) {
    return `${cap(words[0])} ${cap(words[1])} — ${cap(words.slice(2).join(" "))}`;
  }
  return cap(video.title.trim());
}

function slug(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

/** Où ouvrir : « p. 3 » pour un document, « 7:30 » pour un enregistrement. */
export function fmtLoc(loc: { start_s: number; page?: number | null }): string {
  return loc.page ? `p. ${loc.page}` : fmtTs(loc.start_s);
}

/** Document ou image : l'axe est la page (visionneuse), pas le temps (lecteur). */
export function isDocument(video: Pick<Video, "kind"> | undefined): boolean {
  return video?.kind === "document" || video?.kind === "image";
}

export function isImage(video: Pick<Video, "kind"> | undefined): boolean {
  return video?.kind === "image";
}

/** Nature d'un extrait, affichée à côté de la preuve. */
export const NATURE: Record<string, string> = {
  ocr: "lu dans l'image",
  visual: "description IA — à vérifier sur l'image",
};

/** Titre lisible depuis un identifiant (repli : l'identifiant). */
export function titleOf(videoId: string, videos: Video[]): string {
  const v = videos.find((x) => x.video_id === videoId);
  return v ? prettyTitle(v) : videoId;
}

/** Fichier audio seul (nos talks TED et réunions AMI sont des .wav) → lecteur audio. */
export function isAudioOnly(video: Video): boolean {
  return video.source_uri.split(";").every((p) => AUDIO_EXT.test(p));
}
