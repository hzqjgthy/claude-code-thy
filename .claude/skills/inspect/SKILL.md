---
description: Inspect the target using a forked agent
arguments:
  - target
context: fork
allowed-tools:
  - read
  - glob
  - grep
effort: medium
---
Inspect ${target} and return a concise summary.
