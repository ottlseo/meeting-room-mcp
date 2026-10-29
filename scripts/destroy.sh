#!/usr/bin/env bash
# 스택과 배포용 버킷을 지운다.
#   ./scripts/destroy.sh [--prefix meeting-room] [--region us-east-1]
set -euo pipefail
cd "$(dirname "$0")/.."

PREFIX=meeting-room
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

STACK="${PREFIX}-mcp"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${PREFIX}-cfn-${ACCOUNT}-${REGION}"

echo "deleting stack ${STACK} (${REGION})... CloudFront 때문에 몇 분 걸립니다"
aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK"

if aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null 2>&1; then
  aws s3 rm "s3://${BUCKET}" --recursive --region "$REGION" >/dev/null
  aws s3api delete-bucket --bucket "$BUCKET" --region "$REGION"
fi
rm -f mcp.json
echo "done"
