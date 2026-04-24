from __future__ import annotations

from typing import Any


SNAPSHOT_SCRIPT = r"""
() => {
  const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const isVisible = (el) => {
    if (!(el instanceof HTMLElement)) return false;
    const style = window.getComputedStyle(el);
    if (!style || style.visibility === "hidden" || style.display === "none") return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const interactiveSelector = [
    "a",
    "button",
    "input",
    "textarea",
    "select",
    "summary",
    "[role='button']",
    "[role='link']",
    "[onclick]",
    "[tabindex]",
  ].join(",");

  const interactive = Array.from(document.querySelectorAll(interactiveSelector));
  const refs = [];
  let index = 1;
  for (const el of interactive) {
    if (!(el instanceof HTMLElement)) continue;
    if (!isVisible(el)) continue;
    const ref = `e${index++}`;
    el.setAttribute("data-cct-ref", ref);
    const text = normalize(
      el.innerText ||
      el.getAttribute("aria-label") ||
      el.getAttribute("placeholder") ||
      el.getAttribute("title") ||
      ((el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) ? el.value : "") ||
      ""
    );
    refs.push({
      ref,
      tag: normalize(el.tagName.toLowerCase()),
      role: normalize(el.getAttribute("role")),
      type: normalize(el.getAttribute("type")),
      text: text.slice(0, 200),
      href: normalize(el.getAttribute("href")),
      disabled: Boolean(el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true"),
    });
  }

  return {
    title: normalize(document.title),
    url: String(window.location.href || ""),
    refs,
    bodyText: String(document.body ? document.body.innerText || "" : ""),
  };
}
"""


def build_snapshot_text(snapshot: dict[str, Any], *, max_chars: int) -> str:
    """把页面快照结果渲染成适合模型消费的文本。"""
    title = str(snapshot.get("title", "")).strip() or "(untitled)"
    url = str(snapshot.get("url", "")).strip() or "(unknown)"
    refs = snapshot.get("refs") if isinstance(snapshot.get("refs"), list) else []
    body_text = str(snapshot.get("bodyText", "")).strip()

    lines = [
        f"Page Title: {title}",
        f"Page URL: {url}",
        "",
        "Interactive Elements:",
    ]

    if not refs:
        lines.append("(none)")
    else:
        for item in refs:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref", "")).strip()
            tag = str(item.get("tag", "")).strip()
            role = str(item.get("role", "")).strip()
            input_type = str(item.get("type", "")).strip()
            text = str(item.get("text", "")).strip()
            href = str(item.get("href", "")).strip()
            disabled = bool(item.get("disabled", False))

            parts = [f"[{ref}]", tag or "element"]
            if role:
                parts.append(f"role={role}")
            if input_type:
                parts.append(f"type={input_type}")
            if disabled:
                parts.append("disabled")
            if text:
                parts.append(f'text="{text}"')
            if href:
                parts.append(f"href={href}")
            lines.append(" - " + " ".join(parts))

    if body_text:
        lines.extend(
            [
                "",
                "Body Text:",
                body_text,
            ]
        )

    rendered = "\n".join(lines).strip()
    if len(rendered) <= max_chars:
        return rendered
    truncated = rendered[: max(0, max_chars - 16)].rstrip()
    return f"{truncated}\n...[truncated]"
