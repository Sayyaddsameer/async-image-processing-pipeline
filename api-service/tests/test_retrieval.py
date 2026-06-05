from unittest.mock import patch
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from app import app

client = TestClient(app)

FAKE_IMAGE_ID = "550e8400-e29b-41d4-a716-446655440000"


@patch("app.s3_client")
def test_get_processed_image_found(mock_s3):
    mock_s3.head_object.return_value = {"ContentType": "image/png"}
    mock_s3.generate_presigned_url.return_value = "https://s3.example.com/signed-url"

    response = client.get(f"/images/processed/{FAKE_IMAGE_ID}")

    assert response.status_code == 200
    data = response.json()
    assert data["image_id"] == FAKE_IMAGE_ID
    assert "processed_image_url" in data
    assert data["processed_image_url"] == "https://s3.example.com/signed-url"
    assert "expires_in_seconds" in data


@patch("app.s3_client")
def test_get_processed_image_not_found_returns_404(mock_s3):
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "head_object"
    )

    response = client.get(f"/images/processed/{FAKE_IMAGE_ID}")

    assert response.status_code == 404
    assert FAKE_IMAGE_ID in response.json()["detail"]


@patch("app.s3_client")
def test_get_processed_image_s3_error_returns_500(mock_s3):
    mock_s3.head_object.side_effect = ClientError(
        {"Error": {"Code": "403", "Message": "Forbidden"}}, "head_object"
    )

    response = client.get(f"/images/processed/{FAKE_IMAGE_ID}")
    assert response.status_code == 500


@patch("app.s3_client")
def test_get_processed_presigned_url_failure_returns_500(mock_s3):
    mock_s3.head_object.return_value = {}
    mock_s3.generate_presigned_url.side_effect = ClientError(
        {"Error": {"Code": "500", "Message": "Error"}}, "generate_presigned_url"
    )

    response = client.get(f"/images/processed/{FAKE_IMAGE_ID}")
    assert response.status_code == 500


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
