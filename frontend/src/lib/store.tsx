import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  createSession as createSessionApi,
  deleteSession as deleteSessionApi,
  getRuntimeInfo,
  getSessionMcp,
  getSessionSkills,
  getSessionTasks,
  getSessionTools,
  getTranscript,
  listSessions,
  streamChat,
  streamResolvePendingPermission,
  type ChatSSEEvent,
} from "./api";
import type {
  McpSnapshotDTO,
  MessageDTO,
  PendingPermissionDTO,
  RuntimeInfoDTO,
  SSEAssistantDeltaEventDTO,
  SessionDetailDTO,
  SessionSummaryDTO,
  SkillsSnapshotDTO,
  SSEToolEventDTO,
  TaskDTO,
  ToolsSnapshotDTO,
} from "./types";

type RightTab = "tools" | "skills" | "mcp" | "tasks";

interface AppState {
  runtimeInfo: RuntimeInfoDTO | null;
  sessions: SessionSummaryDTO[];
  currentSessionId: string | null;
  currentSession: SessionDetailDTO | null;
  messages: MessageDTO[];
  pendingPermission: PendingPermissionDTO | null;
  isStreaming: boolean;
  isResolvingPermission: boolean;
  liveAssistantText: string;
  liveToolEvents: SSEToolEventDTO[];
  rightTab: RightTab;
  tools: ToolsSnapshotDTO | null;
  skills: SkillsSnapshotDTO | null;
  mcp: McpSnapshotDTO | null;
  tasks: TaskDTO[];
  errorText: string;
  setRightTab: (tab: RightTab) => void;
  refreshSessions: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  createSession: () => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  sendMessage: (prompt: string) => Promise<void>;
  resolvePendingPermission: (approved: boolean) => Promise<void>;
  refreshPanels: (sessionId?: string) => Promise<void>;
  clearError: () => void;
}

const AppContext = createContext<AppState | null>(null);

function buildLocalAssistantMessage(text: string, index: number): MessageDTO {
  const timestamp = new Date().toISOString();
  return {
    message_id: `local-error-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    index,
    role: "assistant",
    kind: "assistant_text",
    text,
    created_at: timestamp,
    content_blocks: [],
    raw_metadata: {},
    tool_calls: [],
    tool_result: null,
    permission_request: null,
    task_notification: null,
  };
}


function buildLocalUserMessage(text: string, index: number): MessageDTO {
  const timestamp = new Date().toISOString();
  return {
    message_id: `local-user-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    index,
    role: "user",
    kind: "user",
    text,
    created_at: timestamp,
    content_blocks: [],
    raw_metadata: { optimistic: true },
    tool_calls: [],
    tool_result: null,
    permission_request: null,
    task_notification: null,
  };
}


function mergeIncomingMessage(previous: MessageDTO[], incoming: MessageDTO): MessageDTO[] {
  if (
    incoming.role === "user"
    && previous.length > 0
    && previous[previous.length - 1].role === "user"
    && previous[previous.length - 1].text === incoming.text
    && previous[previous.length - 1].raw_metadata?.optimistic
  ) {
    return [...previous.slice(0, -1), incoming];
  }
  return [...previous, incoming];
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [runtimeInfo, setRuntimeInfo] = useState<RuntimeInfoDTO | null>(null);
  const [sessions, setSessions] = useState<SessionSummaryDTO[]>([]);
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [currentSession, setCurrentSession] = useState<SessionDetailDTO | null>(null);
  const [messages, setMessages] = useState<MessageDTO[]>([]);
  const [pendingPermission, setPendingPermission] = useState<PendingPermissionDTO | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [isResolvingPermission, setIsResolvingPermission] = useState(false);
  const [liveAssistantText, setLiveAssistantText] = useState("");
  const [liveToolEvents, setLiveToolEvents] = useState<SSEToolEventDTO[]>([]);
  const [rightTab, setRightTab] = useState<RightTab>("tools");
  const [tools, setTools] = useState<ToolsSnapshotDTO | null>(null);
  const [skills, setSkills] = useState<SkillsSnapshotDTO | null>(null);
  const [mcp, setMcp] = useState<McpSnapshotDTO | null>(null);
  const [tasks, setTasks] = useState<TaskDTO[]>([]);
  const [errorText, setErrorText] = useState("");
  const bootstrappedRef = useRef(false);

  const clearError = useCallback(() => setErrorText(""), []);

  const refreshPanels = useCallback(async (sessionId?: string) => {
    const targetSessionId = sessionId || currentSessionId;
    if (!targetSessionId) {
      return;
    }
    const [toolsResult, skillsResult, mcpResult, tasksResult] = await Promise.allSettled([
      getSessionTools(targetSessionId),
      getSessionSkills(targetSessionId),
      getSessionMcp(targetSessionId),
      getSessionTasks(targetSessionId),
    ]);

    if (toolsResult.status === "fulfilled") {
      setTools(toolsResult.value);
    }
    if (skillsResult.status === "fulfilled") {
      setSkills(skillsResult.value);
    }
    if (mcpResult.status === "fulfilled") {
      setMcp(mcpResult.value);
    }
    if (tasksResult.status === "fulfilled") {
      setTasks(tasksResult.value);
    }
  }, [currentSessionId]);

  const hydrateSession = useCallback(async (sessionId: string) => {
    const [transcript] = await Promise.all([getTranscript(sessionId), refreshPanels(sessionId)]);
    setCurrentSessionId(sessionId);
    setCurrentSession(transcript.session);
    setMessages(transcript.messages);
    setPendingPermission(transcript.session.pending_permission ?? null);
    setLiveAssistantText("");
    setLiveToolEvents([]);
  }, [refreshPanels]);

  const refreshSessions = useCallback(async () => {
    const nextSessions = await listSessions();
    setSessions(nextSessions);
    if (!currentSessionId && nextSessions.length > 0) {
      await hydrateSession(nextSessions[0].session_id);
    }
  }, [currentSessionId, hydrateSession]);

  const createSession = useCallback(async () => {
    const created = await createSessionApi(runtimeInfo?.workspace_root, runtimeInfo?.model);
    await refreshSessions();
    await hydrateSession(created.session_id);
  }, [hydrateSession, refreshSessions, runtimeInfo]);

  const deleteSession = useCallback(async (sessionId: string) => {
    await deleteSessionApi(sessionId);
    const nextSessions = await listSessions();
    setSessions(nextSessions);
    if (currentSessionId === sessionId) {
      if (nextSessions.length > 0) {
        await hydrateSession(nextSessions[0].session_id);
      } else {
        setCurrentSessionId(null);
        setCurrentSession(null);
        setMessages([]);
        setPendingPermission(null);
        setTools(null);
        setSkills(null);
        setMcp(null);
        setTasks([]);
      }
    }
  }, [currentSessionId, hydrateSession]);

  const selectSession = useCallback(async (sessionId: string) => {
    await hydrateSession(sessionId);
  }, [hydrateSession]);

  const consumeTurnStream = useCallback(async (
    events: AsyncIterable<ChatSSEEvent>,
    {
      errorPrefix,
      onError,
    }: {
      errorPrefix: string;
      onError?: () => void;
    },
  ) => {
    for await (const event of events) {
      if (event.event === "tool_event") {
        setLiveToolEvents((prev) => [...prev, event.data as SSEToolEventDTO]);
        continue;
      }
      if (event.event === "assistant_delta") {
        const delta = (event.data as SSEAssistantDeltaEventDTO).text || "";
        if (delta) {
          setLiveAssistantText((prev) => prev + delta);
        }
        continue;
      }
      if (event.event === "message") {
        const message = (event.data as { message: MessageDTO }).message;
        setMessages((prev) => mergeIncomingMessage(prev, message));
        if (message.role === "assistant") {
          setLiveAssistantText("");
        }
        continue;
      }
      if (event.event === "done") {
        const turn = (event.data as { turn: { session: SessionDetailDTO; pending_permission?: PendingPermissionDTO | null } }).turn;
        setCurrentSession(turn.session);
        setPendingPermission(turn.pending_permission ?? null);
        setLiveAssistantText("");
        setLiveToolEvents([]);
        await refreshPanels(turn.session.session_id);
        await refreshSessions();
        return;
      }
      if (event.event === "error") {
        const error = (event.data as { error: string }).error || "Unknown error";
        setMessages((prev) => [...prev, buildLocalAssistantMessage(`${errorPrefix}：${error}`, prev.length)]);
        setErrorText(error);
        setLiveAssistantText("");
        setLiveToolEvents([]);
        onError?.();
        return;
      }
    }
  }, [refreshPanels, refreshSessions]);

  const sendMessage = useCallback(async (prompt: string) => {
    const trimmed = prompt.trim();
    if (!trimmed || !currentSessionId || isStreaming || isResolvingPermission) {
      return;
    }

    clearError();
    setIsStreaming(true);
    setPendingPermission(null);
    setMessages((prev) => [...prev, buildLocalUserMessage(trimmed, prev.length)]);
    setLiveAssistantText("");
    setLiveToolEvents([]);

    try {
      await consumeTurnStream(streamChat(currentSessionId, trimmed), { errorPrefix: "API 调用失败" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setMessages((prev) => [...prev, buildLocalAssistantMessage(`连接失败：${message}`, prev.length)]);
      setErrorText(message);
      setLiveAssistantText("");
      setLiveToolEvents([]);
    } finally {
      setIsStreaming(false);
    }
  }, [
    clearError,
    currentSessionId,
    isResolvingPermission,
    isStreaming,
    refreshPanels,
    refreshSessions,
  ]);

  const resolvePendingPermission = useCallback(async (approved: boolean) => {
    if (!currentSessionId || !pendingPermission || isResolvingPermission) {
      return;
    }
    const pendingSnapshot = pendingPermission;
    clearError();
    setIsResolvingPermission(true);
    setIsStreaming(true);
    try {
      setPendingPermission(null);
      setCurrentSession((prev) => (
        prev
          ? {
              ...prev,
              pending_permission: null,
            }
          : prev
      ));
      setLiveAssistantText("");
      setLiveToolEvents([]);
      await consumeTurnStream(streamResolvePendingPermission(currentSessionId, approved), {
        errorPrefix: "权限处理失败",
        onError: () => {
          setPendingPermission(pendingSnapshot);
          setCurrentSession((prev) => (
            prev
              ? {
                  ...prev,
                  pending_permission: pendingSnapshot,
                }
              : prev
          ));
        },
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setPendingPermission(pendingSnapshot);
      setCurrentSession((prev) => (
        prev
          ? {
              ...prev,
              pending_permission: pendingSnapshot,
            }
          : prev
      ));
      setErrorText(message);
      setMessages((prev) => [...prev, buildLocalAssistantMessage(`权限处理失败：${message}`, prev.length)]);
    } finally {
      setIsStreaming(false);
      setIsResolvingPermission(false);
    }
  }, [
    clearError,
    consumeTurnStream,
    currentSessionId,
    isResolvingPermission,
    pendingPermission,
  ]);

  useEffect(() => {
    if (bootstrappedRef.current) {
      return;
    }
    bootstrappedRef.current = true;

    (async () => {
      try {
        const info = await getRuntimeInfo();
        setRuntimeInfo(info);
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setErrorText(message);
      }

      try {
        const existingSessions = await listSessions();
        setSessions(existingSessions);
        if (existingSessions.length > 0) {
          await hydrateSession(existingSessions[0].session_id);
        } else {
          const created = await createSessionApi();
          setSessions([
            {
              session_id: created.session_id,
              title: created.title,
              cwd: created.cwd,
              model: created.model,
              provider_name: created.provider_name,
              updated_at: created.updated_at,
            },
          ]);
          await hydrateSession(created.session_id);
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        setErrorText(message);
      }
    })();
  }, [hydrateSession]);

  const value = useMemo<AppState>(() => ({
    runtimeInfo,
    sessions,
    currentSessionId,
    currentSession,
    messages,
    pendingPermission,
    isStreaming,
    isResolvingPermission,
    liveAssistantText,
    liveToolEvents,
    rightTab,
    tools,
    skills,
    mcp,
    tasks,
    errorText,
    setRightTab,
    refreshSessions,
    selectSession,
    createSession,
    deleteSession,
    sendMessage,
    resolvePendingPermission,
    refreshPanels,
    clearError,
  }), [
    runtimeInfo,
    sessions,
    currentSessionId,
    currentSession,
    messages,
    pendingPermission,
    isStreaming,
    isResolvingPermission,
    liveAssistantText,
    liveToolEvents,
    rightTab,
    tools,
    skills,
    mcp,
    tasks,
    errorText,
    refreshSessions,
    selectSession,
    createSession,
    deleteSession,
    sendMessage,
    resolvePendingPermission,
    refreshPanels,
    clearError,
  ]);

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useAppState(): AppState {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error("useAppState must be used inside AppProvider");
  }
  return context;
}
