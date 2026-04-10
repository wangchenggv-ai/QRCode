"""
Feishu API helpers for the QR-code integration.

Responsibilities:
  - Fetch / cache a tenant access token (expires every 2 h)
  - Poll the order table for new orders that need a lens code
  - Detect first-time orders from an agent
  - Poll for overdue orders (>= FEISHU_OVERDUE_DAYS days old, lens code assigned)
  - Send text messages to a group chat or individual user
  - Look up a Feishu user's open_id by phone number
  - Write lens_code back to the Bitable order record
  - Query orders by order_id or phone (for agent self-service tracking)
"""

import time
import logging
import urllib.request
import urllib.error
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
# Messaging
# ---------------------------------------------------------------------------

def send_message(receive_id: str, text: str, receive_id_type: str = "chat_id") -> None:
    """Send a plain-text message to a Feishu group chat or individual user."""
    if not receive_id:
        return
    token = get_tenant_token()
    payload = json.dumps({
        "receive_id": receive_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}),
    }).encode()
    url = (
        f"https://open.feishu.cn/open-apis/im/v1/messages"
        f"?receive_id_type={receive_id_type}"
    )
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") != 0:
            logger.error("send_message failed: %s", data)
        else:
            logger.info("Message sent to %s (%s)", receive_id, receive_id_type)
    except urllib.error.HTTPError as e:
        logger.error("send_message HTTP %d: %s", e.code, e.read().decode()[:200])


def get_open_id_by_phone(phone: str) -> str | None:
    """Return the Feishu open_id for a user with the given mobile phone number."""
    if not phone:
        return None
    token = get_tenant_token()
    payload = json.dumps({"phones": [phone]}).encode()
    url = (
        "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id"
        "?user_id_type=open_id"
    )
    req = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get("code") != 0:
            return None
        for u in data.get("data", {}).get("user_list", []):
            if u.get("user_id"):
                return u["user_id"]
    except Exception as exc:
        logger.warning("get_open_id_by_phone(%s) failed: %s", phone, exc)
    return None


def notify(text: str, phone: str = "") -> None:
    """
    Send text to the configured internal group chat.
    If phone is provided and a matching Feishu user is found, also DM them.
    """
    chat_id = Config.FEISHU_NOTIFY_CHAT_ID
    if chat_id:
        send_message(chat_id, text, receive_id_type="chat_id")
    if phone:
        open_id = get_open_id_by_phone(phone)
        if open_id:
            send_message(open_id, text, receive_id_type="open_id")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(val) -> str:
    """Extract plain string from a Feishu text/select field value."""
    if isinstance(val, list) and val:
        return str(val[0].get("text", "") or val[0].get("name", ""))
    return str(val or "")


def _search(payload: dict) -> list[dict]:
    """POST to records/search and return items list."""
    token = get_tenant_token()
    base  = Config.FEISHU_BITABLE_APP_TOKEN
    table = Config.FEISHU_ORDER_TABLE_ID
    url   = (
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{base}"
        f"/tables/{table}/records/search"
    )
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.error("_search HTTP %d: %s", e.code, e.read().decode()[:200])
        return []
    if data.get("code") != 0:
        logger.error("_search failed: %s", data)
        return []
    return data.get("data", {}).get("items", [])


# ---------------------------------------------------------------------------
# Poll for pending orders (no lens code yet)
# ---------------------------------------------------------------------------

def fetch_pending_orders() -> list[dict]:
    """
    Return records where 镜片码 is empty (lens code not yet assigned).
    Each item: {"record_id", "order_id", "patient", "agent", "phone"}
    """
    items = _search({
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "镜片码", "operator": "isEmpty", "value": []}
            ]
        },
        "page_size": 50,
    })

    pending = []
    for item in items:
        f = item.get("fields", {})
        pending.append({
            "record_id": item["record_id"],
            "order_id":  _text(f.get("订单编号", "")),
            "patient":   _text(f.get("患者姓名", "")),
            "agent":     _text(f.get("代理商名称", "")),
            "phone":     _text(f.get("联系电话", "")),
        })

    logger.info("fetch_pending_orders: %d records need processing", len(pending))
    return pending


# ---------------------------------------------------------------------------
# First-order detection
# ---------------------------------------------------------------------------

def is_first_order(agent_name: str) -> bool:
    """Return True if this is the agent's only order in the table."""
    if not agent_name:
        return False
    items = _search({
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "代理商名称", "operator": "is", "value": [agent_name]}
            ]
        },
        "page_size": 2,
    })
    return len(items) == 1


# ---------------------------------------------------------------------------
# Overdue orders (lens code assigned, order date > FEISHU_OVERDUE_DAYS ago)
# ---------------------------------------------------------------------------

def fetch_overdue_orders(overdue_days: int | None = None) -> list[dict]:
    """
    Return orders where 镜片码 is assigned but 下单日期 is older than overdue_days.
    Each item: {"record_id", "order_id", "patient", "agent", "phone", "order_date_ms"}
    """
    days = overdue_days if overdue_days is not None else Config.FEISHU_OVERDUE_DAYS
    threshold_ms = str(int((time.time() - days * 86400) * 1000))

    items = _search({
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "镜片码",  "operator": "isNotEmpty", "value": []},
                {"field_name": "下单日期", "operator": "isLess",     "value": ["ExactDate", threshold_ms]},
            ]
        },
        "page_size": 50,
    })

    overdue = []
    for item in items:
        f = item.get("fields", {})
        overdue.append({
            "record_id":    item["record_id"],
            "order_id":     _text(f.get("订单编号", "")),
            "patient":      _text(f.get("患者姓名", "")),
            "agent":        _text(f.get("代理商名称", "")),
            "phone":        _text(f.get("联系电话", "")),
            "order_date_ms": f.get("下单日期", 0),
        })

    logger.info("fetch_overdue_orders: %d overdue records", len(overdue))
    return overdue


# ---------------------------------------------------------------------------
# Agent self-service: query orders by order_id or phone
# ---------------------------------------------------------------------------

def query_orders_for_agent(order_id: str = "", phone: str = "") -> list[dict]:
    """
    Return orders matching order_id (exact) or phone (exact).
    Used for the agent self-service tracking page.
    """
    if not order_id and not phone:
        return []

    conditions = []
    if order_id:
        conditions.append({"field_name": "订单编号", "operator": "is", "value": [order_id]})
    if phone:
        conditions.append({"field_name": "联系电话", "operator": "is", "value": [phone]})

    items = _search({
        "filter": {"conjunction": "or", "conditions": conditions},
        "page_size": 20,
    })

    results = []
    for item in items:
        f = item.get("fields", {})
        lens = _text(f.get("镜片码", ""))
        date_ms = f.get("下单日期", 0) or 0
        order_date = ""
        if date_ms:
            import datetime
            order_date = datetime.datetime.fromtimestamp(date_ms / 1000).strftime("%Y-%m-%d")
        results.append({
            "order_id":   _text(f.get("订单编号", "")),
            "patient":    _text(f.get("患者姓名", "")),
            "agent":      _text(f.get("代理商名称", "")),
            "product":    _text(f.get("产品型号", "")),
            "order_date": order_date,
            "lens_code":  lens,
            "status":     "已处理 · 生产中" if lens else "待处理",
        })
    return results


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
