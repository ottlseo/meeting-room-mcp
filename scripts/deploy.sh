#!/usr/bin/env bash
# CloudFormation 스택을 배포하고 mcp.json 을 만든다.
#   ./scripts/deploy.sh [--prefix meeting-room] [--auth COGNITO|NONE] [--region us-east-1]
set -euo pipefail
cd "$(dirname "$0")/.."

PREFIX=meeting-room
AUTH=COGNITO
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || true)}"
REGION="${REGION:-us-east-1}"

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2 ;;
    --auth) AUTH="$(echo "$2" | tr '[:lower:]' '[:upper:]')"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

STACK="${PREFIX}-mcp"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${PREFIX}-cfn-${ACCOUNT}-${REGION}"

echo "account=${ACCOUNT} region=${REGION} stack=${STACK} auth=${AUTH}"

# Lambda 코드를 올릴 배포용 버킷 (없으면 만든다)
if ! aws s3api head-bucket --bucket "$BUCKET" --region "$REGION" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  aws s3api put-public-access-block --bucket "$BUCKET" --region "$REGION" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  echo "created artifact bucket: ${BUCKET}"
fi

mkdir -p .build
aws cloudformation package --region "$REGION" \
  --template-file template.yaml --s3-bucket "$BUCKET" --s3-prefix "$STACK" \
  --output-template-file .build/packaged.yaml >/dev/null

aws cloudformation deploy --region "$REGION" \
  --template-file .build/packaged.yaml --stack-name "$STACK" \
  --capabilities CAPABILITY_IAM --no-fail-on-empty-changeset \
  --parameter-overrides Prefix="$PREFIX" AuthMode="$AUTH"

"$(dirname "$0")/mcp-json.sh" --stack "$STACK" --region "$REGION"
