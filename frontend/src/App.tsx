import { AppProvider, useAppState } from "./lib/store";
import { ChatPanel } from "./components/ChatPanel";
import { PermissionModal } from "./components/PermissionModal";
import { RightPanel } from "./components/RightPanel";
import { SessionSidebar } from "./components/SessionSidebar";

function Shell() {
  const { runtimeInfo, currentSession, errorText, clearError } = useAppState();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <div className="brand-title">
            {runtimeInfo?.app_name || "claude-code-thy"} Web UI
          </div>
          <div className="brand-subtitle">
            {runtimeInfo?.provider_name || "provider"} · {runtimeInfo?.model || "(unset)"}
          </div>
        </div>
        <div className="app-header-right">
          <div>{currentSession?.cwd || runtimeInfo?.workspace_root || "-"}</div>
        </div>
      </header>

      {errorText ? (
        <div className="error-banner">
          <span>{errorText}</span>
          <button onClick={clearError}>关闭</button>
        </div>
      ) : null}

      <div className="app-main">
        <SessionSidebar />
        <ChatPanel />
        <RightPanel />
      </div>

      <PermissionModal />
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
