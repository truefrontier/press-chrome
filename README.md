# Press Chrome

Agent-native **read-only** Chrome tabs for Grok bots on Kevin’s M4 MacBook.

- CLI: **`chtabs`** (package `press-chrome`)
- MV3 extension (Load Unpacked) shares tabs over **localhost + Bearer token + WebSocket**
- **No** `chrome.debugger`, CDP, or OpenClaw-style write surface

```
Grok bot --Shell(machineId)--> chtabs
  → 127.0.0.1:18793 + Bearer
  ← WebSocket from MV3 extension
```

## Trust model

Default: **`shared_plus_active`**

| Visible to agents | Condition |
|-------------------|-----------|
| Shared tabs | Toolbar icon Share (badge = count) |
| Active tab | Included without Share |
| Other tabs | Hidden unless Shared |

Options also support `shared_only` and `all_tabs_meta` (titles/URLs only for all tabs; body extract still follows Share/active policy for `read`).

## Quick install

See **[docs/INSTALL.md](docs/INSTALL.md)** for full steps. Summary:

```bash
cd ~/Sites/truefrontier/press-chrome
pipx install -e .
chtabs init
# prefer launchd (see docs/INSTALL.md) — or:
chtabs serve
```

Chrome (**Default** profile, `kirchner.kevin@gmail.com`):

1. `chrome://extensions` → Developer mode → **Load unpacked**
2. Select `/Users/kk/Sites/truefrontier/press-chrome/extension`
3. Options → paste token from `chtabs init` → Save
4. Click toolbar icon to Share a tab

## Commands

```
chtabs init
chtabs serve
chtabs status
chtabs list
chtabs show <id>
chtabs read <id>
chtabs active
chtabs history [--limit N] [--query Q]
```

Agent UX flags (Press CLI pattern): `--format table|json`, `--compact`, `--select`, `-q`, `--csv`

Exit codes: `0` ok, `2` usage, `3` not found, `4` not connected/auth, `5` runtime

## History (v1)

`chtabs history` is included via `chrome.history` over the same WebSocket + token. Requires the extension **history** permission (declared in `manifest.json`).

## Security notes

- Token + config: `~/.press-chrome/{token,config.json}` mode **0600**
- Daemon binds **127.0.0.1:18793** only (not OpenClaw’s 18792)
- Extension → daemon WebSocket only (CLI never speaks to Chrome directly)
- **No debugger** — see OpenClaw Browser Relay for the opposite (write-capable) design
- Future click/type/navigate: blocked until **Jev-before-write** — [docs/FUTURE_ACTIONS.md](docs/FUTURE_ACTIONS.md)

## Layout

```
press_chrome/     Python package (CLI + daemon)
extension/        MV3 Load Unpacked root
docs/INSTALL.md   Load Unpacked + profile notes
docs/FUTURE_ACTIONS.md
tests/
```

## Dev smoke (no Chrome required)

```bash
pipx install -e .
chtabs init
# terminal A:
chtabs serve
# terminal B:
chtabs status --format json   # extension_connected may be false until Load Unpacked
python -m pytest tests/ -q
```

## License

MIT
