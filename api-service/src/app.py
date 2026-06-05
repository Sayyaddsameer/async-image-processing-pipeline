import json
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

import boto3
import structlog
from botocore.exceptions import ClientError
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from config import settings

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
logger = structlog.get_logger("api")

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

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_startup", message="API service starting")
    yield
    logger.info("api_shutdown", message="API service stopping")


app = FastAPI(
    title="Async Image Processing API",
    description="Event-driven image upload and processing pipeline.",
    version="1.0.0",
    lifespan=lifespan,
)


def validate_image_file(file: UploadFile) -> str:
    if file.content_type not in ALLOWED_MIME_TYPES:
        logger.warning("invalid_mime_type", content_type=file.content_type, filename=file.filename)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type '{file.content_type}'. Allowed: {sorted(ALLOWED_MIME_TYPES)}",
        )
    if not file.filename or "." not in file.filename:
        raise HTTPException(status_code=400, detail="Filename must include an extension.")
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid extension '.{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )
    return ext


@app.post("/images/upload", status_code=202)
async def upload_image(image: Annotated[UploadFile, File(description="Image file (JPEG, PNG, GIF, WebP)")]):
    ext = validate_image_file(image)

    image_id = str(uuid.uuid4())
    s3_key_raw = f"original/{image_id}.{ext}"

    logger.info("upload_started", image_id=image_id, s3_key=s3_key_raw, filename=image.filename)

    try:
        s3_client.upload_fileobj(image.file, settings.s3_bucket_raw, s3_key_raw)
        logger.info("s3_upload_success", image_id=image_id, bucket=settings.s3_bucket_raw)
    except ClientError as e:
        logger.error("s3_upload_failed", image_id=image_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to store image.")

    sqs_message = {"image_id": image_id, "s3_key_raw": s3_key_raw}

    try:
        response = sqs_client.send_message(
            QueueUrl=settings.sqs_queue_url,
            MessageBody=json.dumps(sqs_message),
        )
        logger.info("sqs_message_sent", image_id=image_id, message_id=response.get("MessageId"))
    except ClientError as e:
        logger.error("sqs_send_failed", image_id=image_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to queue image for processing.")

    return JSONResponse(
        status_code=202,
        content={
            "image_id": image_id,
            "message": "Image upload accepted. Processing has been queued.",
            "status_url": f"/images/processed/{image_id}",
        },
    )


@app.get("/images/processed/{image_id}")
async def get_processed_image(image_id: str):
    s3_key_processed = f"{image_id}_thumbnail.png"

    try:
        s3_client.head_object(Bucket=settings.s3_bucket_processed, Key=s3_key_processed)
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchKey"):
            logger.info("processed_image_not_found", image_id=image_id)
            raise HTTPException(
                status_code=404,
                detail=f"Processed image not found for '{image_id}'. Processing may still be in progress.",
            )
        logger.error("s3_head_object_failed", image_id=image_id, error=str(e))
        raise HTTPException(status_code=500, detail="Error checking image status.")

    try:
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_processed, "Key": s3_key_processed},
            ExpiresIn=settings.presigned_url_expiry_seconds,
        )
        logger.info("presigned_url_generated", image_id=image_id)
    except ClientError as e:
        logger.error("presigned_url_failed", image_id=image_id, error=str(e))
        raise HTTPException(status_code=500, detail="Failed to generate download URL.")

    return {
        "image_id": image_id,
        "processed_image_url": presigned_url,
        "expires_in_seconds": settings.presigned_url_expiry_seconds,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "api"}
