import io
import json
import time

import boto3
import structlog
from botocore.exceptions import ClientError

from config import settings
from image_processor import process_image

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger("worker")

s3_client = boto3.client(
    "s3",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    endpoint_url=settings.aws_endpoint_url,
)

sqs_client = boto3.client(
    "sqs",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    endpoint_url=settings.aws_endpoint_url,
)


def _with_exponential_backoff(func, *args, max_retries: int = None, base_delay: float = None, **kwargs):
    max_retries = max_retries or settings.max_retries
    base_delay = base_delay or settings.retry_base_delay

    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except ClientError as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "transient_error_retry",
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e),
            )
            time.sleep(delay)


def _download_raw_image(s3_key: str) -> bytes:
    buffer = io.BytesIO()
    _with_exponential_backoff(
        s3_client.download_fileobj,
        settings.s3_bucket_raw,
        s3_key,
        buffer,
    )
    return buffer.getvalue()


def _upload_processed_image(image_id: str, image_bytes: bytes) -> str:
    s3_key = f"{image_id}_thumbnail.png"
    _with_exponential_backoff(
        s3_client.upload_fileobj,
        io.BytesIO(image_bytes),
        settings.s3_bucket_processed,
        s3_key,
        ExtraArgs={"ContentType": "image/png"},
    )
    return s3_key


def _delete_message(receipt_handle: str):
    _with_exponential_backoff(
        sqs_client.delete_message,
        QueueUrl=settings.sqs_queue_url,
        ReceiptHandle=receipt_handle,
    )


def process_message(message: dict):
    receipt_handle = message["ReceiptHandle"]
    body = json.loads(message["Body"])

    image_id = body.get("image_id")
    s3_key_raw = body.get("s3_key_raw")

    if not image_id or not s3_key_raw:
        logger.error("invalid_message_body", body=body)
        return

    logger.info("processing_started", image_id=image_id, s3_key_raw=s3_key_raw)

    # Idempotency: check if already processed
    processed_key = f"{image_id}_thumbnail.png"
    try:
        s3_client.head_object(Bucket=settings.s3_bucket_processed, Key=processed_key)
        logger.info("already_processed_skipping", image_id=image_id)
        _delete_message(receipt_handle)
        return
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchKey"):
            raise

    # Download raw image
    try:
        raw_bytes = _download_raw_image(s3_key_raw)
        logger.info("raw_image_downloaded", image_id=image_id, size_bytes=len(raw_bytes))
    except ClientError as e:
        logger.error("download_failed", image_id=image_id, error=str(e))
        raise

    # Process image
    try:
        processed_bytes = process_image(raw_bytes)
        logger.info("image_processed", image_id=image_id, output_size_bytes=len(processed_bytes))
    except Exception as e:
        logger.error("processing_failed", image_id=image_id, error=str(e))
        raise

    # Upload processed image
    try:
        s3_key_out = _upload_processed_image(image_id, processed_bytes)
        logger.info("processed_image_uploaded", image_id=image_id, s3_key=s3_key_out)
    except ClientError as e:
        logger.error("upload_failed", image_id=image_id, error=str(e))
        raise

    # Delete the SQS message ONLY after successful processing
    _delete_message(receipt_handle)
    logger.info("message_deleted", image_id=image_id)
    logger.info("processing_complete", image_id=image_id)


def run():
    logger.info("worker_started", queue=settings.sqs_queue_url)

    while True:
        try:
            response = sqs_client.receive_message(
                QueueUrl=settings.sqs_queue_url,
                MaxNumberOfMessages=settings.sqs_max_messages,
                WaitTimeSeconds=settings.sqs_wait_time_seconds,  # Long-polling
                VisibilityTimeout=settings.sqs_visibility_timeout,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )
        except ClientError as e:
            logger.error("sqs_receive_failed", error=str(e))
            time.sleep(settings.retry_base_delay * 2)
            continue

        messages = response.get("Messages", [])
        if not messages:
            logger.debug("queue_empty_waiting")
            continue

        logger.info("messages_received", count=len(messages))

        for message in messages:
            try:
                process_message(message)
            except Exception as e:
                logger.error(
                    "message_processing_failed_will_retry",
                    message_id=message.get("MessageId"),
                    error=str(e),
                )


if __name__ == "__main__":
    run()
