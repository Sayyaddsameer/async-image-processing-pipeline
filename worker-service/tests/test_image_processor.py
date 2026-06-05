import io
import pytest
from PIL import Image

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from image_processor import process_image, THUMBNAIL_SIZE, WATERMARK_TEXT


def make_test_image(width=400, height=300, color=(100, 150, 200)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_output_is_valid_png():
    raw = make_test_image()
    result = process_image(raw)
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_output_fits_within_150x150():
    raw = make_test_image(800, 600)
    result = process_image(raw)
    img = Image.open(io.BytesIO(result))
    assert img.width <= 150
    assert img.height <= 150


def test_aspect_ratio_preserved_landscape():
    raw = make_test_image(400, 200)  # 2:1 ratio
    result = process_image(raw)
    img = Image.open(io.BytesIO(result))
    actual_ratio = img.width / img.height
    assert abs(actual_ratio - 2.0) < 0.05


def test_aspect_ratio_preserved_portrait():
    raw = make_test_image(200, 400)  # 1:2 ratio
    result = process_image(raw)
    img = Image.open(io.BytesIO(result))
    actual_ratio = img.width / img.height
    assert abs(actual_ratio - 0.5) < 0.05


def test_small_image_not_upscaled():
    raw = make_test_image(50, 50)
    result = process_image(raw)
    img = Image.open(io.BytesIO(result))
    assert img.width <= 150 and img.height <= 150


def test_square_image_becomes_150x150():
    raw = make_test_image(600, 600)
    result = process_image(raw)
    img = Image.open(io.BytesIO(result))
    assert img.width == 150
    assert img.height == 150


def test_output_is_non_empty():
    raw = make_test_image()
    result = process_image(raw)
    assert len(result) > 0


def test_process_png_input():
    img = Image.new("RGB", (300, 300), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = process_image(buf.getvalue())
    out = Image.open(io.BytesIO(result))
    assert out.format == "PNG"
