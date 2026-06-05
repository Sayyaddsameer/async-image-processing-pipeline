# Architecture — Async Image Processing Pipeline

## Overview

The system is split into two services that communicate through SQS and S3 only. The API handles HTTP requests and publishing messages. The worker handles consuming those messages and processing images. Neither service calls the other directly.

LocalStack runs alongside them in Docker and emulates S3 and SQS locally, so the whole stack works without touching a real AWS account.

## How it flows

```
Client
  |
  | POST /images/upload
  v
API Service (FastAPI)
  |- validate file type and extension
  |- generate UUID (image_id)
  |- upload raw file to raw-images-<your-id> S3 bucket
  |- publish { image_id, s3_key_raw } to SQS queue
  |- return 202 Accepted
  
SQS: image-processing-queue-<your-id>
  |  VisibilityTimeout=60s, MaxReceiveCount=3
  |  Redrive -> image-processing-dlq-<your-id>
  |
  | long-poll (WaitTimeSeconds=20)
  v
Worker Service
  |- check if {image_id}_thumbnail.png already exists in processed bucket (idempotency)
  |- download raw image from raw-images-<your-id>
  |- resize to max 150x150 (preserves aspect ratio)
  |- draw "PropelHQ" watermark in bottom-right corner
  |- upload result to processed-images-<your-id> as {image_id}_thumbnail.png
  |- delete message from SQS (only on success)

Client
  |
  | GET /images/processed/{image_id}
  v
API Service
  |- head_object on processed-images-<your-id> bucket
  |- if not found: return 404
  |- if found: generate pre-signed URL (expires in 1 hour)
  |- return URL in JSON response
```

## S3 Buckets

| Bucket                          | Purpose                         | Key format                    |
|---------------------------------|---------------------------------|-------------------------------|
| `raw-images-<your-id>`          | Stores original uploaded files  | `original/{image_id}.{ext}`   |
| `processed-images-<your-id>`    | Stores processed thumbnails     | `{image_id}_thumbnail.png`    |

## SQS Message Schema

```json
{
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "s3_key_raw": "original/550e8400-e29b-41d4-a716-446655440000.jpg"
}
```

## Key Decisions

**Why return 202 and not process inline?**
Image processing is slow and unpredictable in duration. Processing it inside the request handler would block the client, risk timeouts, and doesn't scale well. The SQS queue acts as a buffer — the API offloads the work and returns immediately.

**Idempotency**
SQS delivers messages at least once, meaning the same message can arrive more than once (rare but possible). Before doing any work, the worker checks whether a thumbnail already exists in S3. If it does, it skips processing and deletes the message. This prevents duplicate work without needing a database.

**Why delete the message only on success?**
If processing fails (download error, Pillow crash, upload error), the message stays visible after `VisibilityTimeout` and SQS redelivers it. After 3 failed attempts, it goes to the DLQ. Deleting the message early would silently drop it.

**Exponential backoff**
Transient errors (S3 throttling, brief network issues) are retried with increasing delays: 1s, 2s, 4s. After `max_retries`, the exception propagates and SQS handles redelivery.

**Pre-signed URLs**
The processed bucket is private. Instead of proxying the download through the API, it generates a time-limited S3 pre-signed URL so the client fetches the file directly from S3.

**LocalStack**
The AWS SDK is pointed at `http://localstack:4566` via `AWS_ENDPOINT_URL`. Remove that variable when deploying to real AWS and it connects to the actual AWS endpoints automatically.

## Error Handling

| Scenario                   | API returns               | Worker does                              |
|----------------------------|---------------------------|------------------------------------------|
| Invalid MIME type          | 400                       | —                                        |
| Invalid file extension     | 400                       | —                                        |
| S3 upload fails            | 500                       | —                                        |
| SQS publish fails          | 500                       | —                                        |
| Thumbnail not ready yet    | 404                       | Still being processed                    |
| Worker download error      | —                         | Retry with backoff, then DLQ after 3x   |
| Pillow processing error    | —                         | Retry with backoff, then DLQ after 3x   |
| Duplicate SQS delivery     | —                         | Skip (idempotency check), delete message |

## Scaling Notes

- Multiple worker containers can run in parallel — SQS visibility timeout prevents two workers from processing the same message at the same time.
- `SQS_MAX_MESSAGES=10` lets each worker process up to 10 messages per poll cycle.
- Long-polling (`WaitTimeSeconds=20`) keeps the worker idle efficiently when the queue is empty instead of hammering SQS with empty receives.
