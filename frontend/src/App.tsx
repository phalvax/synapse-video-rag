import { useEffect, useState } from "react";
import { listVideos } from "./api/client";
import ChatSearch from "./components/ChatSearch";
import Dashboard from "./components/Dashboard";
import Layout, { type Screen } from "./components/Layout";
import MissionView from "./components/MissionView";
import UploadView from "./components/UploadView";
import VideoPlayer, { type SeekTarget } from "./components/VideoPlayer";
import type { Video } from "./types";

export default function App() {
  const [screen, setScreen] = useState<Screen>("recherche");
  const [videos, setVideos] = useState<Video[]>([]);
  const [activeVideoId, setActiveVideoId] = useState<string>("");
  const [seek, setSeek] = useState<SeekTarget | null>(null);
  const [missionFocus, setMissionFocus] = useState<string | undefined>(undefined);
  const [onlyThisVideo, setOnlyThisVideo] = useState(false);

  function refreshVideos() {
    listVideos()
      .then((vs) => {
        setVideos(vs);
        setActiveVideoId((cur) => cur || vs[0]?.video_id || "");
      })
      .catch(console.error);
  }

  useEffect(refreshVideos, []);

  function openAt(videoId: string, startS: number, page?: number | null) {
    setActiveVideoId(videoId);
    setSeek({ videoId, startS, page: page ?? null, at: Date.now() });
    setScreen("recherche");
  }

  const activeVideo = videos.find((v) => v.video_id === activeVideoId);

  return (
    <Layout active={screen} onChange={setScreen}>
      {screen === "recherche" && (
        <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
          <ChatSearch
            videos={videos}
            onCitationClick={openAt}
            scopeVideoId={onlyThisVideo ? activeVideoId : undefined}
            onOpenMission={(m) => {
              setMissionFocus(m);
              setScreen("missions");
            }}
          />
          <div className="xl:sticky xl:top-8">
            <VideoPlayer
              videos={videos}
              video={activeVideo}
              seek={seek}
              onSelect={(id) => {
                setActiveVideoId(id);
                setSeek(null);
              }}
              onlyThisVideo={onlyThisVideo}
              onOnlyThisVideoChange={setOnlyThisVideo}
            />
          </div>
        </div>
      )}
      {screen === "missions" && (
        <MissionView videos={videos} onOpen={openAt} initialMission={missionFocus} />
      )}
      {screen === "upload" && <UploadView videos={videos} onDone={refreshVideos} />}
      {screen === "dashboard" && <Dashboard />}
    </Layout>
  );
}
