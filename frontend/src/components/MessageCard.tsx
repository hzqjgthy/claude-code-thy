import type { MessageDTO } from "../lib/types";

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function renderToolResult(message: MessageDTO) {
  if (!message.tool_result) {
    return null;
  }
  return (
    <div className={`tool-result-card ${message.tool_result.ok ? "" : "tool-result-error"}`}>
      <div className="tool-result-header">
        <strong>{message.tool_result.display_name}</strong>
        <span>{message.tool_result.summary}</span>
      </div>
      {message.tool_result.preview ? <pre>{message.tool_result.preview}</pre> : null}
      {!message.tool_result.preview && message.tool_result.output ? (
        <pre>{message.tool_result.output}</pre>
      ) : null}
    </div>
  );
}

export function MessageCard({ message }: { message: MessageDTO }) {
  if (message.kind === "user") {
    const optimistic = Boolean(message.raw_metadata?.optimistic);
    return (
      <div className="message-row message-row-user">
        <div className={`message-bubble message-bubble-user ${optimistic ? "message-bubble-pending" : ""}`}>
          <div>{message.text}</div>
          <div className="message-time">{optimistic ? "发送中…" : formatTime(message.created_at)}</div>
        </div>
      </div>
    );
  }

  const showMessageText = message.kind !== "tool_result" && message.kind !== "tool_error";

  return (
    <div className="message-row">
      <div className={`message-bubble message-bubble-${message.kind}`}>
        {showMessageText && message.text ? <div className="message-text">{message.text}</div> : null}
        {renderToolResult(message)}
        <div className="message-time">{formatTime(message.created_at)}</div>
      </div>
    </div>
  );
}
