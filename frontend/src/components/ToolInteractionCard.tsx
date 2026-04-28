import { useMemo, useState } from "react";

import type { ToolInteractionRenderItem } from "../lib/chatItems";

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

function buildSummary(item: ToolInteractionRenderItem): string {
  const total = item.calls.length;
  const success = item.calls.filter((entry) => entry.result?.tool_result?.ok === true).length;
  const failed = item.calls.filter((entry) => entry.result?.tool_result?.ok === false).length;
  const pending = total - success - failed;

  if (total === 1) {
    const entry = item.calls[0];
    const name = entry.result?.tool_result?.display_name || entry.call.name;
    const summary = entry.result?.tool_result?.summary || "等待工具结果";
    const status = entry.result
      ? (entry.result.tool_result?.ok === false ? "失败" : "成功")
      : "执行中";
    return `${name} · ${status} · ${summary}`.trim();
  }

  const parts = [`工具调用 ${total} 项`];
  if (success > 0) {
    parts.push(`${success} 成功`);
  }
  if (failed > 0) {
    parts.push(`${failed} 失败`);
  }
  if (pending > 0) {
    parts.push(`${pending} 执行中`);
  }
  return parts.join(" · ");
}

export function ToolInteractionCard({ item }: { item: ToolInteractionRenderItem }) {
  const [expanded, setExpanded] = useState(false);

  const summary = useMemo(() => buildSummary(item), [item]);

  return (
    <div className="message-row">
      <div className="message-bubble message-bubble-tool_interaction">
        <button
          type="button"
          className="tool-interaction-summary"
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
        >
          <span className="tool-interaction-summary-text">{summary}</span>
          <span className="tool-interaction-summary-meta">
            <span>{expanded ? "收起" : "展开"}</span>
            <span>{formatTime(item.assistantMessage.created_at)}</span>
          </span>
        </button>

        {expanded ? (
          <div className="tool-interaction-body">
            {item.calls.map((entry) => (
              <div key={entry.call.call_id} className="tool-interaction-entry">
                <div className="tool-interaction-entry-header">
                  <strong>{entry.result?.tool_result?.display_name || entry.call.name}</strong>
                  <span>
                    {entry.result
                      ? (entry.result.tool_result?.ok === false ? "失败" : "成功")
                      : "执行中"}
                  </span>
                </div>

                <div className="tool-interaction-block">
                  <div className="tool-interaction-label">调用体</div>
                  <pre>{JSON.stringify(entry.call.input, null, 2)}</pre>
                </div>

                {entry.result?.tool_result ? (
                  <div className="tool-interaction-block">
                    <div className="tool-interaction-label">结果</div>
                    <div className="tool-interaction-result-summary">
                      {entry.result.tool_result.summary}
                    </div>
                    {entry.result.tool_result.preview ? (
                      <pre>{entry.result.tool_result.preview}</pre>
                    ) : entry.result.tool_result.output ? (
                      <pre>{entry.result.tool_result.output}</pre>
                    ) : null}
                  </div>
                ) : (
                  <div className="tool-interaction-block">
                    <div className="tool-interaction-label">结果</div>
                    <div className="live-placeholder">等待工具结果…</div>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
