import { useAppState } from "../lib/store";

export function PermissionModal() {
  const { pendingPermission, resolvePendingPermission, isResolvingPermission } = useAppState();

  if (!pendingPermission) {
    return null;
  }

  const { request } = pendingPermission;

  return (
    <div className="modal-backdrop">
      <div className="modal-card">
        <div className="modal-title">权限确认</div>
        <div className="modal-subtitle">
          {request.tool_name} 请求访问 {request.target}
        </div>
        <pre className="modal-block">{request.value}</pre>
        {request.reason ? <div className="modal-reason">{request.reason}</div> : null}
        <pre className="modal-block modal-block-small">{request.prompt_text}</pre>
        <div className="modal-actions">
          <button
            className="button-secondary"
            disabled={isResolvingPermission}
            onClick={() => void resolvePendingPermission(false)}
          >
            拒绝
          </button>
          <button
            className="button-primary"
            disabled={isResolvingPermission}
            onClick={() => void resolvePendingPermission(true)}
          >
            {isResolvingPermission ? "处理中…" : "允许"}
          </button>
        </div>
      </div>
    </div>
  );
}
