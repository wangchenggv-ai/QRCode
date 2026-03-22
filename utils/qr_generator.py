import os
import io
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qrcode
from PIL import Image, ImageDraw
from config import Config


def _make_qr_image(qr_code: str) -> Image.Image:
    url = f"{Config.SERVER_BASE_URL}/verify/{qr_code}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # 30% recovery for physical print
        box_size=Config.QR_BOX_SIZE,
        border=Config.QR_BORDER,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def generate_qr_png(qr_code: str, label: str = "", save_to_disk: bool = True) -> bytes:
    """
    Generates a QR code PNG for the given unique lens code.
    label: text printed below the QR (e.g. order ID) for print identification.
    Returns raw PNG bytes; optionally saves to static/qrcodes/<qr_code>.png.
    """
    img = _make_qr_image(qr_code)

    label_height = 36
    annotated = Image.new("RGB", (img.width, img.height + label_height), "white")
    annotated.paste(img, (0, 0))
    draw = ImageDraw.Draw(annotated)
    draw.text(
        (img.width // 2, img.height + 6),
        label if label else qr_code,
        fill="black",
        anchor="mt",
    )

    buf = io.BytesIO()
    annotated.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    if save_to_disk:
        os.makedirs(Config.QR_DIR, exist_ok=True)
        path = os.path.join(Config.QR_DIR, f"{qr_code}.png")
        with open(path, "wb") as f:
            f.write(png_bytes)

    return png_bytes


def generate_all_zip(orders: dict) -> bytes:
    """Returns a ZIP containing one QR code PNG per order."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for order_id, order in orders.items():
            qr_code = order.get("qr_code", "")
            if not qr_code:
                continue
            png = generate_qr_png(qr_code, label=order_id, save_to_disk=True)
            zf.writestr(f"{order_id}.png", png)
    return buf.getvalue()
