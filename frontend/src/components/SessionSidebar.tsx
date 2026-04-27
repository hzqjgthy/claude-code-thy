import { useAppState } from "../lib/store";

function shorten(value: string | null | undefined, fallback: string): string {
  if (!value) {
    return fallback;
  }
  return value.length > 28 ? `${value.slice(0, 27)}…` : value;
}

export function SessionSidebar() {
  const {
    sessions,
    currentSessionId,
    createSession,
    deleteSession,
    refreshSessions,
    selectSession,
  } = useAppState();

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div>
          <h2>会话</h2>
          <p>{sessions.length} 个</p>
        </div>
        <div className="sidebar-actions">
          <button className="button-secondary" onClick={() => void refreshSessions()}>
            刷新
          </button>
          <button className="button-primary" onClick={() => void createSession()}>
            新建
          </button>
        </div>
      </div>

      <div className="session-list">
        {sessions.map((session) => (
          <div
            key={session.session_id}
            className={`session-item ${session.session_id === currentSessionId ? "session-item-active" : ""}`}
          >
            <button className="session-main" onClick={() => void selectSession(session.session_id)}>
              <div className="session-title">
                {shorten(session.title, "(untitled)")}
              </div>
              <div className="session-meta">
                {shorten(session.model, "(unset)")} · {shorten(session.provider_name, "unknown")}
              </div>
            </button>
            <button
              className="session-delete"
              onClick={() => void deleteSession(session.session_id)}
              title="删除会话"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </aside>
  );
}
