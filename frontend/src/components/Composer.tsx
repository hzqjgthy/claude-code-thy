import { FormEvent, KeyboardEvent, useState } from "react";

import { useAppState } from "../lib/store";

export function Composer() {
  const { sendMessage, isStreaming, isResolvingPermission, currentSessionId } = useAppState();
  const [value, setValue] = useState("");

  const disabled = !currentSessionId || isStreaming || isResolvingPermission;

  function submitValue() {
    const prompt = value.trim();
    if (!prompt) {
      return;
    }
    setValue("");
    void sendMessage(prompt);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submitValue();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) {
      return;
    }
    if (event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    submitValue();
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <textarea
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={disabled ? "当前不可输入" : "输入消息或 slash 命令…"}
        rows={3}
        disabled={disabled}
      />
      <div className="composer-actions">
        <span className="composer-hint">
          {isStreaming ? "正在等待本轮完成…" : "Enter 发送，Shift+Enter 换行"}
        </span>
        <button type="submit" disabled={disabled || !value.trim()}>
          发送
        </button>
      </div>
    </form>
  );
}
