import json
import pytest
from unittest.mock import patch
from botocore.exceptions import ClientError

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from worker import process_message

FAKE_IMAGE_ID = "550e8400-e29b-41d4-a716-446655440000"
FAKE_S3_KEY = f"original/{FAKE_IMAGE_ID}.jpg"
FAKE_RECEIPT_HANDLE = "receipt-handle-abc123"

VALID_MESSAGE = {
    "MessageId": "msg-001",
    "ReceiptHandle": FAKE_RECEIPT_HANDLE,
    "Body": json.dumps({"image_id": FAKE_IMAGE_ID, "s3_key_raw": FAKE_S3_KEY}),
}


def make_client_error(code="404"):
    return ClientError({"Error": {"Code": code, "Message": "Error"}}, "operation")


@patch("worker.sqs_client")
@patch("worker.s3_client")
@patch("worker.process_image")
def test_process_message_success(mock_process, mock_s3, mock_sqs):
    # S3 head_object raises 404 (not yet processed — proceed normally)
    mock_s3.head_object.side_effect = make_client_error("404")
    mock_s3.download_fileobj.return_value = None

    def fake_download(bucket, key, buf):
        buf.write(b"fake-image-bytes")
    mock_s3.download_fileobj.side_effect = fake_download

    mock_process.return_value = b"processed-bytes"
    mock_s3.upload_fileobj.return_value = None
    mock_sqs.delete_message.return_value = {}

    process_message(VALID_MESSAGE)

    mock_process.assert_called_once_with(b"fake-image-bytes")
    mock_s3.upload_fileobj.assert_called_once()
    mock_sqs.delete_message.assert_called_once()
    _, call_kwargs = mock_sqs.delete_message.call_args
    assert call_kwargs["ReceiptHandle"] == FAKE_RECEIPT_HANDLE


@patch("worker.sqs_client")
@patch("worker.s3_client")
@patch("worker.process_image")
def test_process_message_idempotent_skip(mock_process, mock_s3, mock_sqs):
    # head_object succeeds → already processed
    mock_s3.head_object.return_value = {"ContentType": "image/png"}
    mock_sqs.delete_message.return_value = {}

    process_message(VALID_MESSAGE)

    mock_process.assert_not_called()
    mock_s3.upload_fileobj.assert_not_called()
    mock_sqs.delete_message.assert_called_once()


@patch("worker.sqs_client")
@patch("worker.s3_client")
def test_process_message_invalid_body_no_crash(mock_s3, mock_sqs):
    bad_message = {
        "MessageId": "bad-msg",
        "ReceiptHandle": "rh",
        "Body": json.dumps({"something": "wrong"}),
    }
    # Should return without raising
    process_message(bad_message)
    mock_s3.head_object.assert_not_called()


@patch("worker.sqs_client")
@patch("worker.s3_client")
@patch("worker.process_image")
def test_process_message_download_failure_raises(mock_process, mock_s3, mock_sqs):
    mock_s3.head_object.side_effect = make_client_error("404")
    mock_s3.download_fileobj.side_effect = make_client_error("500")

    with pytest.raises(ClientError):
        process_message(VALID_MESSAGE)

    mock_sqs.delete_message.assert_not_called()


@patch("worker.sqs_client")
@patch("worker.s3_client")
@patch("worker.process_image")
def test_message_not_deleted_on_processing_failure(mock_process, mock_s3, mock_sqs):
    mock_s3.head_object.side_effect = make_client_error("404")

    def fake_download(bucket, key, buf):
        buf.write(b"image-bytes")
    mock_s3.download_fileobj.side_effect = fake_download

    mock_process.side_effect = Exception("Pillow error")

    with pytest.raises(Exception):
        process_message(VALID_MESSAGE)

    mock_sqs.delete_message.assert_not_called()
