"""Exercise the real MV3 screenshot handler with a fake read-only Chrome API."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_extension_screenshot_policy():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for extension behavior test')
    source = Path('extension/background.js').read_text().split('// Kick off')[0]
    harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const listener = { addListener() {} };
let active = true, trust = 'shared_plus_active', shared = [], captures = 0, changed = false;
const calls = [];
const chrome = {
 runtime: {onInstalled: listener, onStartup: listener},
 alarms: {onAlarm: listener},
 storage: {onChanged: listener, local: {get: async () => ({trust, sharedTabIds: shared})}},
 action: {onClicked: listener},
 tabs: {
   onRemoved: listener,
   get: async id => ({id, windowId: 3, active}),
   query: async query => { assert.deepEqual(JSON.parse(JSON.stringify(query)), {active:true, windowId:3}); return [{id: active ? 7 : 8}]; },
   captureVisibleTab: async (windowId, options) => {
     assert.equal(windowId, 3); assert.equal(options.format, 'png'); captures++;
     if (changed) active = false;
     return 'data:image/png;base64,AAAA';
   }
 },
 scripting: {executeScript: async args => {
   assert.equal(args.target.tabId, 7);
   assert.ok(!args.files);
   return [{result: {devicePixelRatio:2, innerWidth:800, innerHeight:600, scrollX:0, scrollY:100}}];
 }}
};
const context = vm.createContext({chrome, console, setTimeout, clearTimeout});
vm.runInContext(SOURCE, context);
(async () => {
 let result = await context.screenshotTab('r', 7);
 assert.equal(result.ok, true); assert.equal(result.devicePixelRatio, 2); assert.equal(captures, 1);
 active = false; shared = [7];
 result = await context.screenshotTab('r', 7);
 assert.equal(result.error, 'tab not visible; bring it to front yourself or use --image');
 assert.equal(captures, 1);
 active = true; trust = 'shared_only'; shared = [];
 result = await context.screenshotTab('r', 7);
 assert.equal(result.error, 'not_shared'); assert.equal(captures, 1);
 trust = 'shared_plus_active'; changed = true;
 result = await context.screenshotTab('r', 7);
 assert.equal(result.ok, false); assert.equal(captures, 2);
})().catch(err => { console.error(err); process.exitCode = 1; });
'''
    import json
    script = 'const SOURCE = '+json.dumps(source)+';\n'+harness
    result = subprocess.run([node, '-e', script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
