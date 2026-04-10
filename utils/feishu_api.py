"""
Feishu API helpers for the QR-code integration.

Responsibilities:
  - Fetch / cache a tenant access token (expires every 2 h)
  - Upload a PNG bytes object as a Bitable attachment → returns file_token
  - Patch a Bitable record with the lens code + QR attachment
"""

import io
import time
import logging
import urllib.request
import urllib.parse
import json

from config import Config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------
_token_cache: dict = {"token": "", "expires_at": 0}


def get_tenant_token() -> str:
    """Return a valid tenant_access_token, refreshing when within 5 min of expiry."""
    if time.time() < _token_cache["expires_at"] - 300:
        return _token_cache["token"]

    payload = json.dumps({
        "app_id": Config.FEISHU_APP_ID,
        "app_secret": Config.FEISHU_APP_SECRET,
    }).encode()

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    if data.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {data}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expire", 7200)
    logger.info("Feishu token refreshed, expires in %ds", data.get("expire", 7200))
    return _token_cache["token"]


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------

def upload_qr_image(png_bytes: bytes, filename: str) -> str:
    """
    Upload PNG bytes as a Bitable file attachment.
    Returns the file_token string to embed in the record update.
    """
    token = get_tenant_token()

    # Multipart boundary
    boundary = "----FeishuQRBoundary"
    body_parts = []

    def _field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n"
        ).encode()

    body_parts.append(_field("file_name", filename))
    body_parts.append(_field("parent_type", "bitable_file"))
    body_parts.append(_field("parent_node", Config.FEISHU_BITABLE_APP_TOKEN))
    body_parts.append(_field("size", str(len(png_bytes))))

    # File part
    body_parts.append((
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: image/png\r\n\r\n"
    ).encode() + png_bytes + b"\r\n")

    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())

    if data.get("code") != 0:
        raise RuntimeError(f"File upload failed: {data}")

    file_token = data["data"]["file_token"]
    logger.info("Uploaded QR image → file_token=%s", file_token)
    return file_token


# ---------------------------------------------------------------------------
# Record update
# ---------------------------------------------------------------------------

def update_order_record(record_id: str, lens_code: str, file_token: str) -> None:
    """
    Write lens_code and QR attachment back to the Bitable order record.

    Bitable field names must match exactly what's configured in the table:
      - '镜片码'     : Text field
      - '二维码图片' : Attachment field
    """
    token = get_tenant_token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps"
        f"/{Config.FEISHU_BITABLE_APP_TOKEN}"
        f"/tables/{Config.FEISHU_ORDER_TABLE_ID}"
        f"/records/{record_id}"
    )
    payload = json.dumps({
        "fields": {
            "镜片码": lens_code,
            "二维码图片": [{"file_token": file_token}],
        }
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    if data.get("code") != 0:
        raise RuntimeError(f"Record update failed: {data}")

    logger.info("Record %s updated with lens_code=%s", record_id, lens_code)
