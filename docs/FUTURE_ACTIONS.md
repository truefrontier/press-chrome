# Future actions (not in v1)

Press Chrome v1 is **read-only**. These commands are intentionally **not** shipped:

- `click`
- `type` / fill
- `navigate` / goto
- any form submit or DOM mutation driven by agents

## Jev-before-write (required before shipping)

Before any write/action tool is added:

1. **Jev / TypeSafe gate** — classify the target element / intent with confidence floor ≥ 0.9 (same spirit as Walkie Reader / Unclutter).
2. **Explicit human Share** still required for non-active tabs.
3. **No `chrome.debugger`** unless a future product decision explicitly supersedes this (OpenClaw-style CDP is out of scope for Press Chrome).
4. Document risk pages (banking, auth) and keep Pause + Unshare as kill switches.

Until then, the daemon rejects write-like RPC types with `write_actions_blocked`.
