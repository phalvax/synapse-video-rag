import { useEffect, useRef, useState } from "react";
import { getSegments } from "../api/client";
import type { Segment, Video } from "../types";
import { NATURE, fmtTs, isAudioOnly, isDocument, isImage, prettyTitle } from "../utils";
import { Card, Icon } from "./ui";

export interface SeekTarget {
  videoId: string;
  startS: number;
  /** Documents : la page à ouvrir. */
  page?: number | null;
  /** Horodatage du clic : recliquer la même preuve relance quand même la lecture. */
  at: number;
}

interface Props {
  videos: Video[];
  video: Video | undefined;
  seek: SeekTarget | null;
  onSelect: (videoId: string) => void;
  onlyThisVideo: boolean;
  onOnlyThisVideoChange: (v: boolean) => void;
}

export default function VideoPlayer({
  videos,
  video,
  seek,
  onSelect,
  onlyThisVideo,
  onOnlyThisVideoChange,
}: Props) {
  const media = useRef<HTMLMediaElement | null>(null);
  const list = useRef<HTMLOListElement>(null);
  const [activeS, setActiveS] = useState(0);
  const [page, setPage] = useState(1);
  const [transcript, setTranscript] = useState<Segment[]>([]);
  const doc = isDocument(video);

  useEffect(() => {
    if (!seek || !video || seek.videoId !== video.video_id) return;
    setActiveS(seek.startS);
    if (seek.page) {
      setPage(seek.page); // document : la visionneuse s'ouvre à la page citée
      return;
    }
    const m = media.current;
    if (!m) return;
    const go = () => {
      m.currentTime = seek.startS;
      m.play().catch(() => {}); // lecture auto refusée par le navigateur : l'utilisateur clique ▶
    };
    if (m.readyState >= 1) go();
    else m.addEventListener("loadedmetadata", go, { once: true });
  }, [seek, video]);

  useEffect(() => {
    if (!video) return;
    setTranscript([]);
    if (!seek || seek.videoId !== video.video_id) setPage(1);
    getSegments(video.video_id).then(setTranscript).catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- recharger seulement au changement de vidéo
  }, [video]);

  const activeIndex = doc
    ? activeDocIndex(transcript, page, activeS)
    : transcript.findIndex((s) => activeS >= s.start_s && activeS < s.end_s);

  // Le transcript suit la lecture (comme des sous-titres), sans faire défiler la page.
  useEffect(() => {
    const box = list.current;
    const item = box?.children[activeIndex] as HTMLElement | undefined;
    if (!box || !item) return;
    const top = item.offsetTop; // la liste est `relative` : position déjà relative à elle
    if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - item.offsetHeight) {
      box.scrollTo({ top: top - box.clientHeight / 3, behavior: "smooth" });
    }
  }, [activeIndex]);

  const bind = (el: HTMLMediaElement | null) => {
    media.current = el;
  };
  const onTime = (e: React.SyntheticEvent<HTMLMediaElement>) =>
    setActiveS(e.currentTarget.currentTime);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3 border-b border-line px-4 py-3">
        <label htmlFor="video-select" className="sr-only">Vidéo affichée</label>
        <select
          id="video-select"
          value={video?.video_id ?? ""}
          onChange={(e) => onSelect(e.target.value)}
          className="min-w-0 flex-1 truncate rounded-lg border border-line bg-surface px-3 py-2 text-sm
                     font-medium text-ink focus:border-accent focus:outline-none"
        >
          {videos.map((v) => (
            <option key={v.video_id} value={v.video_id}>
              {prettyTitle(v)}
            </option>
          ))}
        </select>
      </div>

      {!video ? (
        <p className="px-4 py-16 text-center text-sm text-muted">
          Cliquez une preuve, ou choisissez une vidéo, pour l'ouvrir ici.
        </p>
      ) : (
        <>
          {isImage(video) ? (
            <div className="flex max-h-[460px] justify-center overflow-auto bg-surface-2 p-3">
              <img
                src={`/api/videos/${video.video_id}/media`}
                alt={prettyTitle(video)}
                className="max-w-full rounded-md border border-line bg-white object-contain"
              />
            </div>
          ) : doc ? (
            <div className="bg-surface-2">
              {/* key = page : le lecteur PDF du navigateur ne suit pas un simple changement d'ancre */}
              <iframe
                key={`${video.video_id}-${page}`}
                title={prettyTitle(video)}
                src={`/api/videos/${video.video_id}/media#page=${page}&view=FitH`}
                className="h-[460px] w-full border-0 bg-white"
              />
            </div>
          ) : isAudioOnly(video) ? (
            <div className="bg-surface-2 px-4 py-5">
              <div className="mb-3 flex items-center gap-3 text-ink-2">
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-accent-soft text-accent">
                  <Icon.wave />
                </span>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink">{prettyTitle(video)}</p>
                  <p className="text-xs text-muted">
                    Enregistrement audio · {fmtTs(video.duration_s)}
                  </p>
                </div>
              </div>
              <audio
                ref={bind}
                src={`/api/videos/${video.video_id}/media`}
                controls
                preload="metadata"
                className="w-full"
                onTimeUpdate={onTime}
              />
            </div>
          ) : (
            <video
              ref={bind}
              src={`/api/videos/${video.video_id}/media`}
              controls
              preload="metadata"
              className="aspect-video w-full bg-black"
              onTimeUpdate={onTime}
            />
          )}

          <VideoMeta video={video} />

          <div className="flex items-center justify-between gap-3 border-y border-line px-4 py-2.5">
            <label className="flex cursor-pointer items-center gap-2 text-sm text-ink-2">
              <input
                type="checkbox"
                checked={onlyThisVideo}
                onChange={(e) => onOnlyThisVideoChange(e.target.checked)}
                className="h-4 w-4 accent-[var(--accent)]"
              />
              Chercher seulement {doc ? "dans ce document" : "dans cette vidéo"}
            </label>
            <span className="font-mono text-xs tabular-nums text-muted">
              {doc
                ? `p. ${page} / ${Math.max(1, ...transcript.map((t) => t.page ?? 1))}`
                : `${fmtTs(activeS)} / ${fmtTs(video.duration_s)}`}
            </span>
          </div>

          <ol ref={list} className="relative max-h-[420px] overflow-y-auto px-2 py-2">
            {transcript.length === 0 && (
              <li className="px-3 py-6 text-center text-sm text-muted">
                {doc ? "Texte non disponible (document pas encore extrait)."
                     : "Transcript non disponible (vidéo pas encore transcrite)."}
              </li>
            )}
            {transcript.map((seg, i) => (
              <li key={seg.seg_id}>
                <button
                  type="button"
                  onClick={() => {
                    setActiveS(seg.start_s);
                    if (doc) setPage(seg.page ?? 1);
                    else if (media.current) media.current.currentTime = seg.start_s;
                  }}
                  className={`flex w-full gap-3 rounded-lg px-3 py-1.5 text-left text-sm leading-relaxed transition-colors ${
                    i === activeIndex
                      ? "bg-accent-soft text-ink"
                      : "text-ink-2 hover:bg-surface-2"
                  }`}
                >
                  <span
                    className={`shrink-0 pt-0.5 font-mono text-xs tabular-nums ${
                      i === activeIndex ? "text-accent" : "text-muted"
                    }`}
                  >
                    {doc ? `p. ${seg.page ?? 1}` : fmtTs(seg.start_s)}
                  </span>
                  <span>
                    {seg.modality && (
                      <span className={`mr-1.5 rounded px-1 py-0.5 text-[11px] ${
                        seg.modality === "visual" ? "bg-warn-soft text-warn" : "bg-surface-2 text-ink-2"
                      }`}>
                        {NATURE[seg.modality] ?? seg.modality}
                      </span>
                    )}
                    {seg.text}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </Card>
  );
}

/** Contexte saisi à l'import (mission, date, auteur, contact, description), s'il existe. */
function VideoMeta({ video }: { video: Video }) {
  const chips = [
    video.mission && `Mission ${video.mission}`,
    video.date && new Date(video.date).toLocaleDateString("fr-FR"),
    video.author,
  ].filter(Boolean) as string[];
  if (!chips.length && !video.description && !video.contact) return null;
  return (
    <div className="border-t border-line px-4 py-3 text-sm">
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <span key={c} className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-ink-2">{c}</span>
          ))}
        </div>
      )}
      {video.description && <p className="mt-2 leading-relaxed text-ink-2">{video.description}</p>}
      {video.contact && <p className="mt-1 text-xs text-muted">Contact : {video.contact}</p>}
    </div>
  );
}

/** Document : l'unité citée (position ≥ activeS sur la page affichée), sinon la 1re de la page. */
function activeDocIndex(units: Segment[], page: number, activeS: number): number {
  const onPage = (s: Segment) => (s.page ?? 1) === page;
  const cited = units.findIndex((s) => onPage(s) && s.start_s >= activeS - 1e-6);
  return cited >= 0 ? cited : units.findIndex(onPage);
}
