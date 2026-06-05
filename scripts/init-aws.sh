#!/bin/bash
# scripts/init-aws.sh
# Initializes LocalStack with S3 buckets and SQS queues.
# All resource names are driven by environment variables with safe defaults.
set -e

ENDPOINT="${AWS_ENDPOINT_URL:-http://localhost:4566}"
REGION="${AWS_REGION:-us-east-1}"
RAW_BUCKET="${S3_BUCKET_RAW:-raw-images-localdev}"
PROCESSED_BUCKET="${S3_BUCKET_PROCESSED:-processed-images-localdev}"
MAIN_QUEUE="${SQS_MAIN_QUEUE:-image-processing-queue-localdev}"
DLQ="${SQS_DLQ:-image-processing-dlq-localdev}"

AWS_CMD="aws --endpoint-url=$ENDPOINT --region=$REGION"

echo "Waiting for LocalStack to be ready..."
until curl -s "$ENDPOINT/_localstack/health" | grep -q '"s3"'; do
  sleep 1
done
echo "LocalStack is ready."

# ── S3 Buckets ────────────────────────────────────────────────────
$AWS_CMD s3 mb s3://$RAW_BUCKET       2>/dev/null || echo "$RAW_BUCKET already exists"
$AWS_CMD s3 mb s3://$PROCESSED_BUCKET 2>/dev/null || echo "$PROCESSED_BUCKET already exists"

# ── Dead-Letter Queue (must exist before main queue references it) ─
$AWS_CMD sqs create-queue \
  --queue-name "$DLQ" \
  --attributes '{"MessageRetentionPeriod":"1209600"}' \
  2>/dev/null || echo "$DLQ already exists"

# ── Fetch DLQ ARN ─────────────────────────────────────────────────
DLQ_ARN=$($AWS_CMD sqs get-queue-attributes \
  --queue-url "$ENDPOINT/000000000000/$DLQ" \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)

echo "DLQ ARN: $DLQ_ARN"

# ── Main Processing Queue with Redrive Policy ─────────────────────
# maxReceiveCount=3: after 3 failed attempts, message moves to DLQ
$AWS_CMD sqs create-queue \
  --queue-name "$MAIN_QUEUE" \
  --attributes "{
    \"VisibilityTimeout\": \"60\",
    \"MessageRetentionPeriod\": \"86400\",
    \"RedrivePolicy\": \"{\\\"deadLetterTargetArn\\\":\\\"$DLQ_ARN\\\",\\\"maxReceiveCount\\\":\\\"3\\\"}\"
  }" \
  2>/dev/null || echo "$MAIN_QUEUE already exists"

echo ""
echo "AWS resources initialized successfully."
echo "  Buckets : $RAW_BUCKET, $PROCESSED_BUCKET"
echo "  Queue   : $MAIN_QUEUE"
echo "  DLQ     : $DLQ"
