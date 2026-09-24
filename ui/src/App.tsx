import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api, type Action, type Deck, type Project, type WorkspaceCatalog } from "./api";
import { humanError } from "./errors";
import { DeckScreen } from "./deck/DeckScreen";
import { SessionSummary } from "./deck/SessionSummary";
import { ProjectScreen, type OtherSession } from "./project/ProjectScreen";

type Screen = "project" | "deck" | "completion";

export function App() {
  const queryClient = useQueryClient();
  const [screen, setScreen] = useState<Screen>("project");
  const [completionSessionId, setCompletionSessionId] = useState<string | null>(null);
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api<WorkspaceCatalog>("/api/workspaces"),
    retry: false,
  });
  const selectedWorkspaceId = workspaces.data?.selected_id;
  const project = useQuery({
    queryKey: ["project", selectedWorkspaceId],
    queryFn: () => api<Project>("/api/project"),
    enabled: selectedWorkspaceId !== undefined,
    refetchInterval: screen === "project" ? 4_000 : false,
  });
  // `abar listen` のQuick Listenは受信箱に載らない。起動時と受信箱へ戻るたびに進行中のSessionを確かめる。
  // (/api/deck/active は音声tokenを発行するため、ポーリングはしない。)
  const activeDeck = useQuery({
    queryKey: ["deck", "active", selectedWorkspaceId],
    queryFn: () => api<Deck>("/api/deck/active"),
    enabled: selectedWorkspaceId !== undefined,
    staleTime: Infinity,
    retry: false,
  });
  const otherSession: OtherSession | null = (() => {
    const deck = activeDeck.data;
    if (!deck?.session_id || !deck.status || !project.data) return null;
    if (project.data.sessions.some((item) => item.project_session_id === deck.session_id)) return null;
    return { sessionId: deck.session_id, status: deck.status };
  })();
  const routedRef = useRef(false);
  useEffect(() => {
    if (routedRef.current || !activeDeck.isFetched || !project.data) return;
    routedRef.current = true;
    if (otherSession?.status === "active") setScreen((current) => current === "project" ? "deck" : current);
  }, [activeDeck.isFetched, otherSession?.status, project.data]);
  const selectWorkspace = useMutation({
    mutationFn: (workspaceId: string) => api<Action>(`/api/workspaces/${workspaceId}/select`, { method: "POST" }),
    onSuccess: async () => {
      setScreen("project");
      setCompletionSessionId(null);
      await queryClient.invalidateQueries();
    },
  });

  if (workspaces.isError || project.isError) {
    const error = workspaces.error ?? project.error;
    return <ErrorState title="ABARを開けません" message={error ? humanError(error) : undefined} retry={() => { void workspaces.refetch(); void project.refetch(); }} />;
  }

  if (!workspaces.data || !project.data) return <main className="centered">状態を読み込んでいます…</main>;

  const refresh = async () => {
    await Promise.all([project.refetch(), activeDeck.refetch()]);
  };
  return (
    <div className="app-shell">
      {screen === "project" && (
        <ProjectScreen
          project={project.data}
          otherSession={otherSession}
          workspaces={workspaces.data}
          switchingWorkspace={selectWorkspace.isPending}
          onSelectWorkspace={(workspaceId) => selectWorkspace.mutate(workspaceId)}
          onOpenDeck={() => setScreen("deck")}
          onOpenCompletion={(sessionId) => {
            setCompletionSessionId(sessionId);
            setScreen("completion");
          }}
          onChanged={() => void refresh()}
        />
      )}
      {screen === "deck" && (
        <DeckScreen
          onBack={() => {
            setScreen("project");
            void refresh();
          }}
        />
      )}
      {screen === "completion" && completionSessionId && (
        <SessionSummary
          sessionId={completionSessionId}
          onBack={() => {
            setCompletionSessionId(null);
            setScreen("project");
            void refresh();
          }}
        />
      )}
    </div>
  );
}

function ErrorState({ title, message, retry }: { title: string; message?: string | undefined; retry: () => unknown }) {
  return (
    <main className="centered error-panel">
      <h1>{title}</h1>
      <p>{message ?? "不明なエラー"}</p>
      <button type="button" className="secondary-action" onClick={() => void retry()}>再試行</button>
    </main>
  );
}
