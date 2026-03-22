"""
label_generator.py
------------------
Generates print-ready label images for the factory.

Each label contains:
  - High-resolution QR code (left side)
  - Prescription parameters: SPH/CYL for L/R eye (right side)
  - Order number and production date

Output resolution targets 300 DPI for direct label printing.
Label size: ~6cm wide × 3cm tall → at 300 DPI: 709 × 354 px
We render at 2x (1418 × 708) for sharper print quality.
"""
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qrcode
from PIL import Image, ImageDraw, ImageFont
from config import Config

# ─── Font loading ─────────────────────────────────────────────────────────────
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",            # Linux (WenQuanYi)
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",   # Noto CJK
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",                       # macOS
    "C:/Windows/Fonts/msyh.ttc",                                # Windows (微软雅黑)
]

def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


# ─── QR code (print resolution) ───────────────────────────────────────────────
def _make_print_qr(qr_code: str, px: int) -> Image.Image:
    """Generate a square QR code image of exactly px × px pixels."""
    url = f"{Config.SERVER_BASE_URL}/verify/{qr_code}"
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=1,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((px, px), Image.LANCZOS)


# ─── Label image ──────────────────────────────────────────────────────────────
# Label canvas: 1418 × 708 px (prints at ~300 DPI on a 6cm×3cm label)
LABEL_W = 1418
LABEL_H = 708
QR_SIZE  = 600   # QR occupies left portion
MARGIN   = 36
PAD      = 28    # inner padding

def generate_label_image(order: dict) -> bytes:
    """
    Creates a single print-ready label PNG for the given order.
    Returns raw PNG bytes.
    """
    img = Image.new("RGB", (LABEL_W, LABEL_H), "white")
    draw = ImageDraw.Draw(img)

    # ── Border ────────────────────────────────────────────────────────────────
    draw.rectangle([2, 2, LABEL_W - 3, LABEL_H - 3], outline="#000000", width=4)

    # ── QR code (left) ────────────────────────────────────────────────────────
    qr_img = _make_print_qr(order["qr_code"], QR_SIZE)
    qr_y   = (LABEL_H - QR_SIZE) // 2
    img.paste(qr_img, (MARGIN, qr_y))

    # ── Divider line ──────────────────────────────────────────────────────────
    div_x = MARGIN + QR_SIZE + MARGIN
    draw.line([(div_x, MARGIN * 2), (div_x, LABEL_H - MARGIN * 2)],
              fill="#cccccc", width=3)

    # ── Text block (right) ────────────────────────────────────────────────────
    tx = div_x + PAD        # text left edge
    ty = MARGIN + 16        # text top

    f_title  = _font(52)
    f_header = _font(40)
    f_value  = _font(56)
    f_small  = _font(30)

    # Order ID
    draw.text((tx, ty), f"订单号：{order['order_id']}", font=f_title, fill="#111111")
    ty += 68

    # Separator
    draw.line([(tx, ty), (LABEL_W - MARGIN, ty)], fill="#eeeeee", width=2)
    ty += 20

    # Prescription table header
    col_sph = tx + 200
    col_cyl = col_sph + 220
    draw.text((tx,       ty), "眼别",   font=f_header, fill="#666666")
    draw.text((col_sph,  ty), "球镜 SPH", font=f_header, fill="#666666")
    draw.text((col_cyl,  ty), "柱镜 CYL", font=f_header, fill="#666666")
    ty += 52

    # Left eye row
    l_sph = order.get("left_sph") or "—"
    l_cyl = order.get("left_cyl") or "—"
    draw.text((tx,       ty), "左眼 L", font=f_value, fill="#111111")
    draw.text((col_sph,  ty), l_sph,   font=f_value, fill="#0a5c2a")
    draw.text((col_cyl,  ty), l_cyl,   font=f_value, fill="#0a5c2a")
    ty += 72

    # Right eye row
    r_sph = order.get("right_sph") or "—"
    r_cyl = order.get("right_cyl") or "—"
    draw.text((tx,       ty), "右眼 R", font=f_value, fill="#111111")
    draw.text((col_sph,  ty), r_sph,   font=f_value, fill="#0a5c2a")
    draw.text((col_cyl,  ty), r_cyl,   font=f_value, fill="#0a5c2a")
    ty += 72

    # Separator
    draw.line([(tx, ty), (LABEL_W - MARGIN, ty)], fill="#eeeeee", width=2)
    ty += 16

    # Production date + notes
    meta = f"生产日期：{order.get('production_date', '')}"
    if order.get("notes"):
        meta += f"　备注：{order['notes']}"
    draw.text((tx, ty), meta, font=f_small, fill="#888888")
    ty += 44

    # Unique lens code (for traceability)
    draw.text((tx, ty), f"镜片码：{order.get('qr_code', '')}",
              font=f_small, fill="#bbbbbb")

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()


# ─── Factory ZIP ──────────────────────────────────────────────────────────────
def generate_factory_zip(orders: dict, excel_path: str) -> bytes:
    """
    Builds a ZIP for the factory containing:
      labels/ORD001.png  ← print-ready label (QR + prescription)
      qrcodes/ORD001.png ← standalone high-res QR only
      orders_with_codes.xlsx ← Excel with 镜片码 column filled in
      说明.txt           ← usage instructions
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        for order_id, order in orders.items():
            if not order.get("qr_code"):
                continue

            # 1. Combined label image
            label_png = generate_label_image(order)
            zf.writestr(f"labels/{order_id}.png", label_png)

            # 2. Standalone high-res QR code
            qr_img = _make_print_qr(order["qr_code"], 1000)
            qr_buf = io.BytesIO()
            qr_img.save(qr_buf, format="PNG", dpi=(300, 300))
            zf.writestr(f"qrcodes/{order_id}.png", qr_buf.getvalue())

        # 3. Updated Excel (with 镜片码 filled in)
        if os.path.exists(excel_path):
            with open(excel_path, "rb") as f:
                zf.writestr("orders_with_codes.xlsx", f.read())

        # 4. Plain-text instructions for the factory
        readme = _make_readme(len(orders))
        zf.writestr("说明.txt", readme.encode("utf-8"))

    return buf.getvalue()


def _make_readme(count: int) -> str:
    return f"""工厂打印包使用说明
==================

本压缩包包含 {count} 个订单的打印素材，共三类文件：

【labels/ 文件夹】—— 推荐使用
  每个文件对应一张完整镜片标签，包含：
  - 左侧：二维码（高分辨率，适合直接打印）
  - 右侧：处方参数（左右眼球镜/柱镜）、订单号、生产日期
  标签尺寸：建议打印在 6cm × 3cm 标签纸上（300 DPI）
  直接使用标签打印机打印即可，无需任何修改。

【qrcodes/ 文件夹】—— 仅二维码
  单独的高分辨率二维码图片（1000×1000px，300 DPI）
  适合导入标签设计软件（Bartender / NiceLabel 等）自行排版。

【orders_with_codes.xlsx】—— 数据源
  包含所有订单的完整数据，含唯一镜片码列。
  可导入标签打印软件的数据库，与 qrcodes/ 文件夹配合使用。

注意事项：
  - 每个镜片码全球唯一，请勿复制或重复使用
  - 镜片码与二维码一一对应，不可互换
  - 打印后请妥善保管本压缩包，以备核查
"""
