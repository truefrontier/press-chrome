# Press Chrome — install (M4 MacBook)

## Chrome profile

Load the extension in Kevin’s **daily / Default** profile:

- Profile directory: `Default`
- Account: `kirchner.kevin@gmail.com`

Do **not** install into Kate (`Profile 4`) or nextnow (`Profile 7`) unless intentional.

## Steps

### 1. Install CLI

```bash
cd ~/Projects/PROJ-press-chrome
pipx install -e .
# ensures ~/.local/bin/chtabs  (PATH should already include this)
```

### 2. Init token + config

```bash
chtabs init
# writes ~/.press-chrome/{token,config.json} mode 0600
# prints token — copy it
```

### 3. Start daemon

```bash
chtabs serve
# listens on 127.0.0.1:18793 (HTTP + ws://127.0.0.1:18793/ws)
# leave this running
```

### 4. Load Unpacked (human once)

1. Open Google Chrome in the **Default** profile.
2. Go to `chrome://extensions`
3. Enable **Developer mode**
4. **Load unpacked** → select exactly:

```
/Users/kk/Projects/PROJ-press-chrome/extension
```

5. Pin **Press Chrome**.
6. Extension → **Options** → paste token from step 2 → **Save**.
7. Grant **history** if Chrome prompts (needed for `chtabs history`).

### 5. Share a tab + smoke

1. Open any article page.
2. Click the Press Chrome toolbar icon (badge shows shared count).
3. From a terminal (or agent Shell on M4):

```bash
chtabs status --format json
chtabs list --format json
chtabs active --format json
chtabs history --limit 5 --format json
```

## Permissions

| Permission | Why |
|------------|-----|
| `tabs` | list / show shared + active tabs |
| `scripting` | inject readability extract for `read` / `active` |
| `storage` | token, trust mode, shared tab ids |
| `alarms` | MV3 service worker reconnect keepalive |
| `history` | `chtabs history` via `chrome.history` |

## Notes

- **No** `chrome.debugger` / CDP / OpenClaw relay.
- Port **18793** avoids OpenClaw’s 18792.
- Pause agent access from Options if needed.

## Auto-start (launchd)

Preferred over tmux/pm2 on macOS. Runs at login and restarts if it dies.

```bash
# plist lives in the repo and is installed to LaunchAgents:
cp ~/Projects/PROJ-press-chrome/launchd/com.truefrontier.chtabs.plist \
  ~/Library/LaunchAgents/com.truefrontier.chtabs.plist

launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.truefrontier.chtabs.plist
# or after edits:
launchctl kickstart -k "gui/$(id -u)/com.truefrontier.chtabs"
```

Logs: `~/.press-chrome/logs/serve.{out,err}.log`

Stop / disable:
```bash
launchctl bootout "gui/$(id -u)/com.truefrontier.chtabs"
```

Do **not** also run `chtabs serve` in tmux while the LaunchAgent is loaded (port conflict).
