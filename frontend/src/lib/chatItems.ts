import type { MessageDTO, ToolCallDTO } from "./types";

export interface ToolInteractionCall {
  call: ToolCallDTO;
  result?: MessageDTO;
}

export interface ToolInteractionRenderItem {
  type: "tool_interaction";
  key: string;
  assistantMessage: MessageDTO;
  calls: ToolInteractionCall[];
}

export interface MessageRenderItem {
  type: "message";
  key: string;
  message: MessageDTO;
}

export type ChatRenderItem = MessageRenderItem | ToolInteractionRenderItem;

function hasVisibleText(message: MessageDTO): boolean {
  return message.text.trim().length > 0;
}

export function buildChatRenderItems(messages: MessageDTO[]): ChatRenderItem[] {
  const items: ChatRenderItem[] = [];
  const consumedToolMessageIds = new Set<string>();

  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (consumedToolMessageIds.has(message.message_id)) {
      continue;
    }

    if (message.role === "assistant" && message.tool_calls.length > 0) {
      if (hasVisibleText(message)) {
        items.push({
          type: "message",
          key: `${message.message_id}:text`,
          message,
        });
      }

      const calls: ToolInteractionCall[] = message.tool_calls.map((call) => ({ call }));
      const callIdToIndex = new Map<string, number>();
      calls.forEach((entry, callIndex) => {
        callIdToIndex.set(entry.call.call_id, callIndex);
      });

      let lookahead = index + 1;
      while (lookahead < messages.length) {
        const candidate = messages[lookahead];
        if (candidate.role !== "tool") {
          break;
        }
        if (consumedToolMessageIds.has(candidate.message_id)) {
          lookahead += 1;
          continue;
        }

        const toolUseId = candidate.tool_result?.tool_use_id || null;
        if (toolUseId && callIdToIndex.has(toolUseId)) {
          const matchedIndex = callIdToIndex.get(toolUseId);
          if (matchedIndex !== undefined && !calls[matchedIndex].result) {
            calls[matchedIndex].result = candidate;
            consumedToolMessageIds.add(candidate.message_id);
            lookahead += 1;
            continue;
          }
        }

        if (!toolUseId && calls.length === 1 && !calls[0].result) {
          calls[0].result = candidate;
          consumedToolMessageIds.add(candidate.message_id);
          lookahead += 1;
          continue;
        }

        break;
      }

      items.push({
        type: "tool_interaction",
        key: `${message.message_id}:tools`,
        assistantMessage: message,
        calls,
      });
      continue;
    }

    items.push({
      type: "message",
      key: message.message_id,
      message,
    });
  }

  return items;
}
