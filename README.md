# Async Image Processing Pipeline

A backend service that handles image uploads asynchronously. When a user uploads an image, the API stores it in S3, sends a message to SQS, and immediately returns a 202. A separate worker picks up the message, resizes the image to 150x150, adds a watermark, and saves the processed version to another S3 bucket. The API and worker only talk through S3 and SQS — no direct coupling.

For local development, LocalStack simulates both S3 and SQS so you don't need a real AWS account.

## Project Structure

```
async-image-processing-pipeline/
├── api-service/
│   ├── Dockerfile
│   ├── src/
│   │   ├── app.py              # FastAPI endpoints
│   │   ├── config.py           # Settings loaded from env vars
│   │   └── requirements.txt
│   └── tests/
│       ├── __init__.py
│       ├── test_upload.py
│       └── test_retrieval.py
├── worker-service/
│   ├── Dockerfile
│   ├── src/
│   │   ├── worker.py           # SQS polling loop
│   │   ├── image_processor.py  # Resize + watermark logic
│   │   ├── config.py
│   │   └── requirements.txt
│   └── tests/
│       ├── __init__.py
│       ├── test_image_processor.py
│       └── test_worker.py
├── scripts/
│   └── init-aws.sh
├── .env.example
├── docker-compose.yml
├── ARCHITECTURE.md
└── README.md
```

## Requirements

- Docker Desktop (running)
- Git

## Setup

**1. Clone the repo and create your .env file**

```bash
git clone <your-repo-url>
cd async-image-processing-pipeline
cp .env.example .env
```

Open `.env` and replace every `<your-id>` with a unique identifier — your GitHub username works fine.

**2. Start everything**

```bash
docker-compose up --build
```

This starts LocalStack, creates the S3 buckets and SQS queues, then starts the API and worker. The first build takes a couple of minutes.

**3. Check the API is up**

```bash
curl http://localhost:5000/health
```

Expected: `{"status":"healthy","service":"api"}`

## API

### Upload an image

```bash
curl -X POST http://localhost:5000/images/upload \
  -F "image=@/path/to/photo.jpg"
```

Returns 202 immediately:

```json
{
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Image upload accepted. Processing has been queued.",
  "status_url": "/images/processed/550e8400-e29b-41d4-a716-446655440000"
}
```

If you upload something that isn't an image:

```json
{
  "detail": "Invalid file type 'application/pdf'. Allowed: ['image/gif', 'image/jpeg', 'image/png', 'image/webp']"
}
```

### Get the processed image

Wait a few seconds after uploading, then:

```bash
curl http://localhost:5000/images/processed/550e8400-e29b-41d4-a716-446655440000
```

If ready (200):

```json
{
  "image_id": "550e8400-e29b-41d4-a716-446655440000",
  "processed_image_url": "http://localhost:4566/processed-images-<your-id>/..._thumbnail.png?...",
  "expires_in_seconds": 3600
}
```

If the worker hasn't finished yet (404):

```json
{
  "detail": "Processed image not found for '550e8400...'. Processing may still be in progress."
}
```

### Accepted formats

| Format | MIME Type   | Extension    |
|--------|-------------|--------------|
| JPEG   | image/jpeg  | .jpg, .jpeg  |
| PNG    | image/png   | .png         |
| GIF    | image/gif   | .gif         |
| WebP   | image/webp  | .webp        |

## Running Tests

```bash
# API tests
docker-compose exec api pytest tests/ -v

# Worker tests
docker-compose exec worker pytest tests/ -v
```

## AWS Resources

These are created automatically when you run `docker-compose up`:

| Resource                          | Default Name                          |
|-----------------------------------|---------------------------------------|
| S3 bucket (raw uploads)           | `raw-images-<your-id>`                |
| S3 bucket (processed thumbnails)  | `processed-images-<your-id>`          |
| SQS queue                         | `image-processing-queue-<your-id>`    |
| SQS dead-letter queue             | `image-processing-dlq-<your-id>`      |

Messages that fail processing 3 times are moved to the DLQ automatically.

## Environment Variables

See `.env.example` for the full list. The main ones:

| Variable                       | Default                          | Description                                   |
|--------------------------------|----------------------------------|-----------------------------------------------|
| `AWS_REGION`                   | `us-east-1`                      | AWS region                                    |
| `AWS_ACCESS_KEY_ID`            | `test`                           | Use `test` for LocalStack                     |
| `AWS_SECRET_ACCESS_KEY`        | `test`                           | Use `test` for LocalStack                     |
| `AWS_ENDPOINT_URL`             | `http://localstack:4566`         | Points the AWS SDK at LocalStack              |
| `S3_BUCKET_RAW`                | `raw-images-localdev`            | Bucket for original uploads                   |
| `S3_BUCKET_PROCESSED`          | `processed-images-localdev`      | Bucket for processed thumbnails               |
| `SQS_MAIN_QUEUE`               | `image-processing-queue-localdev`| Queue name (used by aws-init)                 |
| `SQS_DLQ`                      | `image-processing-dlq-localdev`  | DLQ name (used by aws-init)                   |
| `SQS_QUEUE_URL`                | _(LocalStack URL)_               | Full queue URL used by API and worker         |
| `PRESIGNED_URL_EXPIRY_SECONDS` | `3600`                           | How long the download link is valid           |
| `SQS_WAIT_TIME_SECONDS`        | `20`                             | Long-poll duration                            |
| `SQS_MAX_MESSAGES`             | `10`                             | Messages fetched per poll                     |
| `SQS_VISIBILITY_TIMEOUT`       | `60`                             | Seconds a message is hidden after receive     |
| `MAX_RETRIES`                  | `3`                              | Retry attempts for S3/SQS errors             |
| `RETRY_BASE_DELAY`             | `1.0`                            | Base delay for exponential backoff (seconds)  |

## Stopping

```bash
docker-compose down       # stop containers
docker-compose down -v    # stop containers and delete volumes (resets LocalStack)
```

## Common Issues

**LocalStack not ready** — give it 20-30 seconds after startup before hitting the API.

**404 on processed image** — the worker is probably still processing. Wait a few seconds and try again.

**Port 5000 taken** — change the port mapping in `docker-compose.yml` to something like `"5001:5000"`.
