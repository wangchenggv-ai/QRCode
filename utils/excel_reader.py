import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from config import Config

# Maps internal Python keys → Excel column header strings (Chinese)
COLUMN_MAP = {
    "order_id":        "订单号",
    "customer_name":   "客户姓名",
    "left_sph":        "左眼球镜",
    "left_cyl":        "左眼柱镜",
    "right_sph":       "右眼球镜",
    "right_cyl":       "右眼柱镜",
    "production_date": "生产日期",
    "notes":           "备注",
}

_cache = {"mtime": None, "data": {}}


def _get_mtime():
    try:
        return os.path.getmtime(Config.EXCEL_PATH)
    except FileNotFoundError:
        return None


def _format_optical(val) -> str:
    """Normalizes optical power values to e.g. '+1.00' or '-2.50'."""
    if val is None or str(val).strip() == "":
        return ""
    try:
        f = float(val)
        sign = "+" if f >= 0 else ""
        return f"{sign}{f:.2f}"
    except (ValueError, TypeError):
        return str(val)


def load_orders() -> dict:
    """
    Returns dict {order_id: order_dict}.
    Uses file mtime to invalidate in-memory cache automatically.
    """
    mtime = _get_mtime()
    if mtime is not None and mtime == _cache["mtime"]:
        return _cache["data"]

    if mtime is None:
        return {}

    wb = openpyxl.load_workbook(Config.EXCEL_PATH, read_only=True, data_only=True)
    ws = wb.active

    # Build column-index → internal-key mapping from header row
    headers = [cell.value for cell in next(ws.iter_rows(min_row=1, max_row=1))]
    reverse_map = {v: k for k, v in COLUMN_MAP.items()}
    col_index = {}  # internal_key → 0-based index
    for idx, header in enumerate(headers):
        if header in reverse_map:
            col_index[reverse_map[header]] = idx

    orders = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not any(row):
            continue
        order = {}
        for key, idx in col_index.items():
            val = row[idx] if idx < len(row) else None
            if key in ("left_sph", "left_cyl", "right_sph", "right_cyl"):
                order[key] = _format_optical(val)
            elif key == "production_date" and hasattr(val, "strftime"):
                order[key] = val.strftime("%Y-%m-%d")
            else:
                order[key] = str(val) if val is not None else ""
        oid = order.get("order_id", "").strip()
        if oid:
            orders[oid] = order

    wb.close()
    _cache["mtime"] = mtime
    _cache["data"] = orders
    return orders


def get_order(order_id: str) -> dict | None:
    return load_orders().get(str(order_id).strip())
