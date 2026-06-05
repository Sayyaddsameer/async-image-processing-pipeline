import io
from unittest.mock import patch
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from app import app

client = TestClient(app)


def make_image_file(filename="test.jpg", content_type="image/jpeg"):
    return ("image", (filename, io.BytesIO(b"fake-image-data"), content_type))


# ── Upload endpoint tests ─────────────────────────────────────────────────────

@patch("app.sqs_client")
@patch("app.s3_client")
def test_upload_success_returns_202(mock_s3, mock_sqs):
    mock_s3.upload_fileobj.return_value = None
    mock_sqs.send_message.return_value = {"MessageId": "test-msg-id"}

    response = client.post(
        "/images/upload",
        files=[make_image_file("photo.jpg", "image/jpeg")],
    )

    assert response.status_code == 202
    data = response.json()
    assert "image_id" in data
    assert "status_url" in data
    assert data["status_url"].startswith("/images/processed/")


@patch("app.sqs_client")
@patch("app.s3_client")
def test_upload_returns_unique_image_ids(mock_s3, mock_sqs):
    mock_s3.upload_fileobj.return_value = None
    mock_sqs.send_message.return_value = {"MessageId": "test-msg-id"}

    r1 = client.post("/images/upload", files=[make_image_file()])
    r2 = client.post("/images/upload", files=[make_image_file()])

    assert r1.json()["image_id"] != r2.json()["image_id"]


def test_upload_no_file_returns_400():
    response = client.post("/images/upload")
    assert response.status_code == 422  # FastAPI validation error for missing field


def test_upload_invalid_mime_type_returns_400():
    response = client.post(
        "/images/upload",
        files=[("image", ("file.pdf", io.BytesIO(b"pdf-data"), "application/pdf"))],
    )
    assert response.status_code == 400
    assert "Invalid file type" in response.json()["detail"]


def test_upload_invalid_extension_returns_400():
    response = client.post(
        "/images/upload",
        files=[("image", ("file.bmp", io.BytesIO(b"bmp-data"), "image/jpeg"))],
    )
    assert response.status_code == 400


@patch("app.sqs_client")
@patch("app.s3_client")
def test_upload_s3_failure_returns_500(mock_s3, mock_sqs):
    from botocore.exceptions import ClientError
    mock_s3.upload_fileobj.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Internal Error"}}, "upload_fileobj"
    )

    response = client.post("/images/upload", files=[make_image_file()])
    assert response.status_code == 500


@patch("app.sqs_client")
@patch("app.s3_client")
def test_upload_sqs_failure_returns_500(mock_s3, mock_sqs):
    from botocore.exceptions import ClientError
    mock_s3.upload_fileobj.return_value = None
    mock_sqs.send_message.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "SQS Error"}}, "send_message"
    )

    response = client.post("/images/upload", files=[make_image_file()])
    assert response.status_code == 500


@patch("app.sqs_client")
@patch("app.s3_client")
def test_upload_png_accepted(mock_s3, mock_sqs):
    mock_s3.upload_fileobj.return_value = None
    mock_sqs.send_message.return_value = {"MessageId": "msg-id"}

    response = client.post(
        "/images/upload",
        files=[("image", ("image.png", io.BytesIO(b"png-data"), "image/png"))],
    )
    assert response.status_code == 202
