import { Composer } from "./Composer";
import { MessageCard } from "./MessageCard";
import { useAppState } from "../lib/store";

export function ChatPanel() {
  const {
    currentSession,
    messages,
    liveAssistantText,
    isStreaming,
    liveToolEvents,
  } = useAppState();

  return (
    <section className="chat-panel">
      <header className="panel-header">
        <div>
          <h1>{currentSession?.title || "新会话"}</h1>
          <p>
            {currentSession?.model || "(unset)"} · {currentSession?.provider_name || "unknown"}
          </p>
        </div>
        <div className="panel-header-side">
          <span>{currentSession?.message_count ?? 0} 条消息</span>
        </div>
      </header>

      <div className="chat-scroll">
        {messages.map((message) => (
          <MessageCard key={message.message_id} message={message} />
        ))}

        {liveAssistantText ? (
          <div className="message-row">
            <div className="message-bubble message-bubble-assistant_text">
              <div className="message-text">{liveAssistantText}</div>
              <div className="message-time">生成中…</div>
            </div>
          </div>
        ) : null}

        {isStreaming ? (
          <div className="message-row">
            <div className="message-bubble message-bubble-live">
              <div className="live-title">本轮执行中</div>
              {liveToolEvents.length ? (
                <ul className="live-events">
                  {liveToolEvents.map((event, index) => (
                    <li key={`${event.tool_name}-${event.phase}-${index}`}>
                      <strong>{event.tool_name}</strong>
                      <span>{event.phase}</span>
                      <div>{event.summary}</div>
                      {event.detail ? <pre>{event.detail}</pre> : null}
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="live-placeholder">等待模型或工具事件…</div>
              )}
            </div>
          </div>
        ) : null}
      </div>

      <Composer />
    </section>
  );
}
