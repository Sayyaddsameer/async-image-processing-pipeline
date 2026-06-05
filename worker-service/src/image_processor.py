import io
from PIL import Image, ImageDraw, ImageFont


THUMBNAIL_SIZE = (150, 150)
WATERMARK_TEXT = "PropelHQ"


def process_image(raw_image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(raw_image_bytes)).convert("RGBA")
    img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    img = _apply_watermark(img)
    output = io.BytesIO()
    img.convert("RGB").save(output, format="PNG")
    return output.getvalue()


def _apply_watermark(img: Image.Image) -> Image.Image:
    draw = ImageDraw.Draw(img)

    font_size = max(10, img.width // 10)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (IOError, OSError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    margin = 5
    x = img.width - text_width - margin
    y = img.height - text_height - margin

    draw.text((x + 1, y + 1), WATERMARK_TEXT, font=font, fill=(0, 0, 0, 128))
    draw.text((x, y), WATERMARK_TEXT, font=font, fill=(255, 255, 255, 200))

    return img
