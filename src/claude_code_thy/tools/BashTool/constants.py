from __future__ import annotations

MAX_INLINE_BASH_OUTPUT = 30_000
MAX_BASH_TIMEOUT_MS = 300_000
MAX_PROGRESS_PREVIEW_LINES = 12

BASH_SEARCH_COMMANDS = {"find", "grep", "rg", "ag", "ack", "locate", "which", "whereis"}
BASH_READ_COMMANDS = {
    "cat",
    "head",
    "tail",
    "less",
    "more",
    "wc",
    "stat",
    "file",
    "strings",
    "jq",
    "awk",
    "cut",
    "sort",
    "uniq",
    "tr",
}
BASH_LIST_COMMANDS = {"ls", "tree", "du"}
BASH_SEMANTIC_NEUTRAL_COMMANDS = {"echo", "printf", "true", "false", ":"}
BASH_SILENT_COMMANDS = {
    "mv",
    "cp",
    "rm",
    "mkdir",
    "rmdir",
    "chmod",
    "chown",
    "chgrp",
    "touch",
    "ln",
    "cd",
    "export",
    "unset",
    "wait",
}

EOF_SENTINEL = object()
