#!/usr/bin/env bash
# 스택 출력값으로 mcp.json 을 만들어 ./mcp.json 에 저장하고 화면에 보여준다.
# AuthMode=COGNITO 이면 새 토큰(24시간)을 발급해 넣는다. 토큰이 만료되면 다시 실행한다.
#   ./scripts/mcp-json.sh [--stack meeting-room-mcp] [--region us-east-1]
set -euo pipefail
cd "$(dirname "$0")/.."

STACK=meeting-room-mcp
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --stack) STACK="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

out() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

GATEWAY_URL="$(out GatewayUrl)"
AUTH_MODE="$(out AuthMode)"
PAGE_URL="$(out RoomsPageUrl)"
NAME="${STACK%-mcp}"

if [ "$AUTH_MODE" = "COGNITO" ]; then
  POOL_ID="$(out UserPoolId)"
  CLIENT_ID="$(out ClientId)"
  TOKEN_URL="$(out TokenUrl)"
  SCOPE="$(out Scope)"
  SECRET="$(aws cognito-idp describe-user-pool-client --region "$REGION" \
    --user-pool-id "$POOL_ID" --client-id "$CLIENT_ID" --query UserPoolClient.ClientSecret --output text)"
  TOKEN="$(curl -s -X POST "$TOKEN_URL" -u "${CLIENT_ID}:${SECRET}" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    -d "grant_type=client_credentials&scope=${SCOPE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
fi

python3 - "$NAME" "$GATEWAY_URL" "${TOKEN:-}" > mcp.json <<'EOF'
import json, sys
name, url, token = sys.argv[1], sys.argv[2], sys.argv[3]
server = {"type": "http", "url": url}
if token:
    server["headers"] = {"Authorization": f"Bearer {token}"}
print(json.dumps({"mcpServers": {name: server}}, indent=2))
EOF
chmod 600 mcp.json

echo
echo "=== mcp.json (Quick Desktop: Settings > Capabilities > + Create > MCP server > Remote > Paste JSON) ==="
cat mcp.json
echo
if [ "$AUTH_MODE" = "COGNITO" ]; then
  echo "token expires in 24h. run ./scripts/mcp-json.sh again to refresh."
fi
echo "room status page: ${PAGE_URL}"
