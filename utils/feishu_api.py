"""
Feishu API helpers for the QR-code integration.

Responsibilities:
  - Fetch / cache a tenant access token (expires every 2 h)
  - Poll the order table for confirmed orders that need a lens code
  - Write lens_code back to the Bitable order record
"""

import time
import logging
import urllib.request
import urllib.error
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
# Poll for pending orders
# ---------------------------------------------------------------------------

def fetch_pending_orders() -> list[dict]:
    """
    Return records where 镜片码 is empty (lens code not yet assigned).
    订单状态 is not visible to the app token, so we assign lens codes to all
    new orders; actual production is gated by the manual factory export step.
    Each item: {"record_id": str, "order_id": str, "patient": str}
    """
    token = get_tenant_token()
    base = Config.FEISHU_BITABLE_APP_TOKEN
    table = Config.FEISHU_ORDER_TABLE_ID

    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}"
        f"/tables/{table}/records/search"
    )
    # Filter only on 镜片码 (visible to app token after re-adding to form).
    # 订单状态 is not visible to the app token and cannot be used as a filter.
    payload = json.dumps({
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "镜片码", "operator": "isEmpty", "value": []}
            ]
        },
        "page_size": 50
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.error("fetch_pending_orders HTTP %d: %s", e.code, e.read().decode()[:200])
        return []

    if data.get("code") != 0:
        logger.error("fetch_pending_orders failed: %s", data)
        return []

    pending = []
    for item in data.get("data", {}).get("items", []):
        fields = item.get("fields", {})
        order_id_raw = fields.get("订单编号", "")
        if isinstance(order_id_raw, list):
            order_id_raw = order_id_raw[0].get("text", "") if order_id_raw else ""
        patient_raw = fields.get("患者姓名", "")
        if isinstance(patient_raw, list):
            patient_raw = patient_raw[0].get("text", "") if patient_raw else ""
        pending.append({
            "record_id": item["record_id"],
            "order_id":  str(order_id_raw or ""),
            "patient":   str(patient_raw or ""),
        })

    logger.info("fetch_pending_orders: %d records need processing", len(pending))
    return pending


# ---------------------------------------------------------------------------
# Record update
# ---------------------------------------------------------------------------

def update_order_record(record_id: str, lens_code: str) -> None:
    """Write lens_code back to the Bitable order record."""
    token = get_tenant_token()
    url = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps"
        f"/{Config.FEISHU_BITABLE_APP_TOKEN}"
        f"/tables/{Config.FEISHU_ORDER_TABLE_ID}"
        f"/records/{record_id}"
    )
    payload = json.dumps({"fields": {"镜片码": lens_code}}).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Record update HTTP {e.code}: {body}") from e
    if data.get("code") != 0:
        raise RuntimeError(f"Record update failed: {data}")
    logger.info("Record %s updated with lens_code=%s", record_id, lens_code)
