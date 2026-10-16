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

## Vision (1.1)

```bash
chtabs vision ask 123 "Is a sign-in form visible?" --format json
chtabs vision box 123 "the search field" --save-screenshot /tmp/tab.png --format json
chtabs vision ask --image /tmp/tab.png "Is a sign-in form visible?"
chtabs vision box --image /tmp/tab.png "the search field" --threshold 0.7
chtabs agent-help --format json
```

Vision is read-only. A tab must already be active in its own window and allowed
by the sharing policy. The CLI never focuses a window, activates a tab, clicks,
types, or navigates. Bring an inactive tab forward yourself or use `--image`.
Screenshots are sent to TypeSafe for analysis; `--save-screenshot` saves the
original PNG/JPEG bytes before image preparation.

`ask` sends one Noul question. `box` sends presence (Noul) and location (Box) in
one request. `noul >= --threshold` means `yes` (default 0.5); absent targets
produce `box: null`. Box output includes `confidence`, raw API `fractions`,
original `screenshot` pixel coordinates, `viewport` CSS coordinates, and document
`page` CSS coordinates. CSS coordinates divide screenshot pixels by the captured
device pixel ratio, then add scroll offsets for `page`. File inputs have null
viewport/page coordinates. Rectangles include x/y/width/height and all four edges.
Floating-point coordinates preserve precision. Padding is excluded and boxes are
clipped to the original image bounds.

PNG/JPEG inputs are downscaled to a maximum side of 1568 and centered on white
padding wherever a side is below 280. Separate effective x/y scales account for
integer resize rounding. The API receives multipart image bytes, model
`jev-1.14.0`, and the required image opt-in header. See the TypeSafe
[image contract](https://docs.typesafe.ai/images) and
[Box contract](https://docs.typesafe.ai/primitives/box).

The default output is human text. `--format json` emits one object; the existing
`--format table` convention auto-selects JSON when piped. `--select`, `--csv`,
`--quiet`, and `--compact` are accepted (vision already returns a single compact
result object).

Requests run through `~/.local/bin/av`; override with `CHTABS_AV`. If Agent Vault
has already supplied `HTTPS_PROXY` and `TYPESAFE_API_KEY`, requests run in-process
using the proxy environment and `SSL_CERT_FILE` (or `REQUESTS_CA_BUNDLE`). Keys
are read only inside that process, never passed on command arguments. API HTTP
errors include status and response body. Local image use needs no daemon/Chrome.

After updating, reinstall Python dependencies (`pipx install -e . --force`) and
**reload the unpacked extension** at `chrome://extensions` using its Reload button.
Restart the daemon/launchd service to pick up Python changes. The extension and
Python package should both report 1.1.0.
