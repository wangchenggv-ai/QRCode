import os
import io
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qrcode
from PIL import Image, ImageDraw
from config import Config


def _make_qr_image(order_id: str) -> Image.Image:
    url = f"{Config.SERVER_BASE_URL}/verify/{order_id}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # 30% recovery for printed lenses
        box_size=Config.QR_BOX_SIZE,
        border=Config.QR_BORDER,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def generate_qr_png(order_id: str, save_to_disk: bool = True) -> bytes:
    """
    Generates a QR code PNG for order_id, annotated with the order ID text.
    Saves to static/qrcodes/<order_id>.png if save_to_disk is True.
    Always returns raw PNG bytes.
    """
    img = _make_qr_image(order_id)

    # Add order_id label below the QR for print identification
    label_height = 32
    annotated = Image.new("RGB", (img.width, img.height + label_height), "white")
    annotated.paste(img, (0, 0))
    draw = ImageDraw.Draw(annotated)
    draw.text(
        (img.width // 2, img.height + 6),
        order_id,
        fill="black",
        anchor="mt",
    )

    buf = io.BytesIO()
    annotated.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    if save_to_disk:
        os.makedirs(Config.QR_DIR, exist_ok=True)
        path = os.path.join(Config.QR_DIR, f"{order_id}.png")
        with open(path, "wb") as f:
            f.write(png_bytes)

    return png_bytes


def generate_zip(order_ids: list) -> bytes:
    """Returns ZIP bytes containing one PNG per order_id."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for oid in order_ids:
            png = generate_qr_png(oid, save_to_disk=True)
            zf.writestr(f"{oid}.png", png)
    return buf.getvalue()
