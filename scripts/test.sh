#!/usr/bin/env bash
# mcp.json 의 서버로 tools/list 와 list_rooms 를 불러 본다.
#   ./scripts/test.sh
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f mcp.json ] || { echo "mcp.json 이 없습니다. ./scripts/mcp-json.sh 를 먼저 실행하세요." >&2; exit 1; }

python3 - <<'EOF'
import json, urllib.request

cfg = json.load(open("mcp.json"))
name, server = next(iter(cfg["mcpServers"].items()))
headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
           **server.get("headers", {})}

def rpc(method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}).encode()
    with urllib.request.urlopen(urllib.request.Request(server["url"], data=body, headers=headers), timeout=60) as r:
        text = r.read().decode()
    if not text.lstrip().startswith("{"):
        text = [l[5:] for l in text.splitlines() if l.startswith("data:")][-1]
    return json.loads(text)

tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
print(f"[{name}] tools:", ", ".join(tools))
rooms = json.loads(rpc("tools/call", {"name": "rooms___list_rooms", "arguments": {}})["result"]["content"][0]["text"])
print(f"[{name}] list_rooms: {len(rooms)} rooms ({', '.join(r['name'] for r in rooms[:3])} ...)")
EOF
