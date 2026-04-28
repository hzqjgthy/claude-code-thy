import type {
  ChatTurnDTO,
  McpSnapshotDTO,
  PendingPermissionDTO,
  RuntimeInfoDTO,
  SSEAssistantDeltaEventDTO,
  SSEDoneEventDTO,
  SSEErrorEventDTO,
  SSEMessageEventDTO,
  SSEToolEventDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  SessionTranscriptDTO,
  SkillDTO,
  SkillsSnapshotDTO,
  TaskDTO,
  ToolDTO,
  ToolsSnapshotDTO,
} from "./types";

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ||
  `http://${window.location.hostname || "127.0.0.1"}:8002/api`;

async function readJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function getRuntimeInfo(): Promise<RuntimeInfoDTO> {
  return readJson<RuntimeInfoDTO>(`${API_BASE}/runtime`);
}

export async function listSessions(): Promise<SessionSummaryDTO[]> {
  return readJson<SessionSummaryDTO[]>(`${API_BASE}/sessions`);
}

export async function createSession(cwd?: string, model?: string): Promise<SessionDetailDTO> {
  return readJson<SessionDetailDTO>(`${API_BASE}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cwd, model }),
  });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await readJson(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
  });
}

export async function getSession(sessionId: string): Promise<SessionDetailDTO> {
  return readJson<SessionDetailDTO>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}`);
}

export async function getTranscript(sessionId: string): Promise<SessionTranscriptDTO> {
  return readJson<SessionTranscriptDTO>(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/messages`
  );
}

export async function getPendingPermission(
  sessionId: string
): Promise<PendingPermissionDTO | null> {
  return readJson<PendingPermissionDTO | null>(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/pending-permission`
  );
}

export async function resolvePendingPermission(
  sessionId: string,
  approved: boolean
): Promise<ChatTurnDTO> {
  return readJson<ChatTurnDTO>(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/pending-permission/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    }
  );
}

export async function getSessionTasks(sessionId: string): Promise<TaskDTO[]> {
  return readJson<TaskDTO[]>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/tasks`);
}

export async function getSessionTools(sessionId: string): Promise<ToolsSnapshotDTO> {
  return readJson<ToolsSnapshotDTO>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/tools`);
}

export async function getSessionSkills(sessionId: string): Promise<SkillsSnapshotDTO> {
  return readJson<SkillsSnapshotDTO>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/skills`);
}

export async function getSessionMcp(sessionId: string): Promise<McpSnapshotDTO> {
  return readJson<McpSnapshotDTO>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/mcp`);
}

export type ChatSSEEvent =
  | { event: "tool_event"; data: SSEToolEventDTO }
  | { event: "assistant_delta"; data: SSEAssistantDeltaEventDTO }
  | { event: "message"; data: SSEMessageEventDTO }
  | { event: "done"; data: SSEDoneEventDTO }
  | { event: "error"; data: SSEErrorEventDTO };

async function* streamSse(url: string, init: RequestInit): AsyncGenerator<ChatSSEEvent> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error("No response body");
  }
  const decoder = new TextDecoder();
  let buffer = "";
  let currentEvent = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n");
    buffer = chunks.pop() || "";

    for (const line of chunks) {
      if (line.startsWith("event:")) {
        currentEvent = line.slice(6).trim();
        continue;
      }
      if (line.startsWith("data:")) {
        const raw = line.slice(5).trim();
        if (!raw) {
          continue;
        }
        const data = JSON.parse(raw) as
          | SSEToolEventDTO
          | SSEAssistantDeltaEventDTO
          | SSEMessageEventDTO
          | SSEDoneEventDTO
          | SSEErrorEventDTO;
        yield { event: currentEvent as ChatSSEEvent["event"], data } as ChatSSEEvent;
        continue;
      }
      if (line === "") {
        currentEvent = "message";
      }
    }
  }
}

export async function* streamChat(
  sessionId: string,
  prompt: string
): AsyncGenerator<ChatSSEEvent> {
  yield* streamSse(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      prompt,
      stream: true,
    }),
  });
}

export async function* streamResolvePendingPermission(
  sessionId: string,
  approved: boolean
): AsyncGenerator<ChatSSEEvent> {
  yield* streamSse(
    `${API_BASE}/sessions/${encodeURIComponent(sessionId)}/pending-permission/resolve?stream=true`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved }),
    }
  );
}
