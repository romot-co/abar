import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Action, type Project, type WorkspaceCatalog } from "./api";
import { humanError } from "./errors";
import { DeckScreen } from "./deck/DeckScreen";
import { SessionSummary } from "./deck/SessionSummary";
import { ProjectScreen } from "./project/ProjectScreen";

type Screen = "project" | "deck" | "completion";

export function App() {
  const queryClient = useQueryClient();
  const [screen, setScreen] = useState<Screen>("project");
  const [completionSessionId, setCompletionSessionId] = useState<string | null>(null);
  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => api<WorkspaceCatalog>("/api/workspaces"),
  });
  const selectedWorkspaceId = workspaces.data?.selected_id;
  const project = useQuery({
    queryKey: ["project", selectedWorkspaceId],
    queryFn: () => api<Project>("/api/project"),
    enabled: selectedWorkspaceId !== undefined,
    refetchInterval: screen === "project" ? 4_000 : false,
  });
  const selectWorkspace = useMutation({
    mutationFn: (workspaceId: string) => api<Action>(`/api/workspaces/${workspaceId}/select`, { method: "POST" }),
    onSuccess: async () => {
      setScreen("project");
      setCompletionSessionId(null);
      await queryClient.invalidateQueries();
    },
  });

  if (workspaces.isPending || project.isPending) return <main className="centered">状態を読み込んでいます…</main>;
  if (workspaces.isError || project.isError || !workspaces.data || !project.data) {
    const error = workspaces.error ?? project.error;
    return <ErrorState title="ABARを開けません" message={error ? humanError(error) : undefined} retry={() => { void workspaces.refetch(); void project.refetch(); }} />;
  }

  const refresh = async () => {
    await project.refetch();
  };
  return (
    <div className="app-shell">
      {screen === "project" && (
        <ProjectScreen
          project={project.data}
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
