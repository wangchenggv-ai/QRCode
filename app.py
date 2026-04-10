import os
import io
import hmac
import uuid
import hashlib
import logging
import functools
import threading
import time
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for,
    request, session, send_file, flash, abort, jsonify,
)
from config import Config
from utils.excel_reader import load_orders, get_order_by_qr, assign_qr_codes
from utils.qr_generator import generate_qr_png, generate_all_zip
from utils.label_generator import generate_factory_zip, generate_label_image
from utils.feishu_api import (
    fetch_pending_orders, update_order_record,
    is_first_order, fetch_overdue_orders, notify, query_orders_for_agent,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH

# Auto-create sample Excel on first run so the app works out of the box
def _init_sample_data():
    if os.path.exists(Config.EXCEL_PATH):
        return
    try:
        import openpyxl
        from datetime import date
        os.makedirs(Config.DATA_DIR, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["订单号","客户姓名","左眼球镜","左眼柱镜","右眼球镜","右眼柱镜","生产日期","备注"])
        ws.append(["ORD001","张三","+1.00","-0.75","+1.25","-0.50",date(2026,1,15),"渐进镜"])
        ws.append(["ORD002","李四","-2.50","-1.00","-2.75","-0.75",date(2026,1,20),""])
        ws.append(["ORD003","王五","0.00","-0.25","+0.25","0.00",date(2026,2,3),"单光镜"])
        wb.save(Config.EXCEL_PATH)
        assign_qr_codes()
    except Exception:
        pass

_init_sample_data()


# ---------------------------------------------------------------------------
# Background poller: process confirmed orders every 60 seconds
# ---------------------------------------------------------------------------
def _process_one(record: dict) -> None:
    record_id = record["record_id"]
    order_id  = record["order_id"] or record_id
    patient   = record["patient"]
    agent     = record.get("agent", "")
    phone     = record.get("phone", "")

    lens_code = uuid.uuid4().hex[:16].upper()
    generate_qr_png(lens_code, label=order_id, save_to_disk=True)
    update_order_record(record_id, lens_code)
    logger.info("poller processed: order=%s lens=%s", order_id, lens_code)

    # Feature 1: first-order alert
    try:
        if agent and is_first_order(agent):
            msg = (
                f"🌟 【首单提醒】\n"
                f"代理商「{agent}」刚完成首单！\n"
                f"订单号：{order_id}  患者：{patient}\n"
                f"请全链条服务团队重点跟进，把首单交付做到极致。"
            )
            notify(msg, phone=phone)
            logger.info("First-order alert sent for agent=%s order=%s", agent, order_id)
    except Exception as exc:
        logger.error("First-order check failed for %s: %s", order_id, exc)


_alerted_overdue: set = set()   # record_ids already notified this session


def _check_overdue() -> None:
    """Alert on orders older than FEISHU_OVERDUE_DAYS that haven't been notified yet."""
    try:
        for rec in fetch_overdue_orders():
            rid = rec["record_id"]
            if rid in _alerted_overdue:
                continue
            _alerted_overdue.add(rid)
            days = Config.FEISHU_OVERDUE_DAYS
            msg = (
                f"⚠️ 【超期订单提醒 · {days}天未完成】\n"
                f"订单号：{rec['order_id']}  患者：{rec['patient']}\n"
                f"代理商：{rec['agent']}  联系电话：{rec['phone']}\n"
                f"下单日期：{rec.get('order_date_ms', '')}\n"
                f"请立即跟进交付进度，并主动联系代理商告知情况。"
            )
            notify(msg, phone=rec["phone"])
            logger.info("Overdue alert sent: order=%s agent=%s", rec["order_id"], rec["agent"])
    except Exception as exc:
        logger.error("overdue check error: %s", exc)


def _poll_loop() -> None:
    # Wait for app to fully start
    time.sleep(10)
    while True:
        if Config.FEISHU_APP_ID and Config.FEISHU_BITABLE_APP_TOKEN:
            # New orders: assign lens codes
            try:
                for record in fetch_pending_orders():
                    try:
                        _process_one(record)
                    except Exception as exc:
                        logger.error("poller failed for %s: %s", record.get("record_id"), exc)
            except Exception as exc:
                logger.error("poller error: %s", exc)
            # Overdue orders: alert if needed
            _check_overdue()
        time.sleep(60)


_poller = threading.Thread(target=_poll_loop, daemon=True, name="feishu-poller")
_poller.start()


@app.context_processor
def inject_now():
    return {"now": datetime.now().strftime("%Y-%m-%d %H:%M")}


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------
def admin_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/verify/<qr_code>")
def verify(qr_code):
    order = get_order_by_qr(qr_code)
    if order is None:
        return render_template("verify.html", found=False, qr_code=qr_code), 404
    return render_template("verify.html", found=True, order=order)


# ---------------------------------------------------------------------------
# Agent self-service order tracking
# ---------------------------------------------------------------------------
@app.route("/track", methods=["GET", "POST"])
def track_order():
    orders = []
    searched = False
    query_val = ""
    if request.method == "POST":
        query_val = request.form.get("query", "").strip()
        searched = True
        if query_val:
            # Try as order_id; if it looks like a phone number also search by phone
            is_phone = query_val.lstrip("+").isdigit() and len(query_val) >= 8
            orders = query_orders_for_agent(
                order_id="" if is_phone else query_val,
                phone=query_val if is_phone else "",
            )
    return render_template("track.html", orders=orders, searched=searched, query=query_val)


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form.get("password") == Config.ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        flash("密码错误", "error")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_dashboard():
    orders = load_orders()
    return render_template("admin.html", orders=orders)


# ---------------------------------------------------------------------------
# Admin: load sample data
# ---------------------------------------------------------------------------
@app.route("/admin/load-sample", methods=["POST"])
@admin_required
def admin_load_sample():
    import openpyxl
    from datetime import date
    os.makedirs(Config.DATA_DIR, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["订单号", "客户姓名", "左眼球镜", "左眼柱镜", "右眼球镜", "右眼柱镜", "生产日期", "备注"])
    ws.append(["ORD001", "张三", "+1.00", "-0.75", "+1.25", "-0.50", date(2026, 1, 15), "渐进镜"])
    ws.append(["ORD002", "李四", "-2.50", "-1.00", "-2.75", "-0.75", date(2026, 1, 20), ""])
    ws.append(["ORD003", "王五", "0.00", "-0.25", "+0.25", "0.00", date(2026, 2, 3), "单光镜"])
    ws.append(["ORD004", "赵六", "-1.25", "-0.50", "-1.00", "-0.25", date(2026, 2, 10), ""])
    ws.append(["ORD005", "陈七", "+2.00", "0.00", "+1.75", "-0.25", date(2026, 3, 1), "双光镜"])
    wb.save(Config.EXCEL_PATH)
    assign_qr_codes()
    orders = load_orders()
    flash(f"示例数据已加载，共 {len(orders)} 条订单", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Admin: upload Excel
# ---------------------------------------------------------------------------
@app.route("/admin/upload", methods=["POST"])
@admin_required
def admin_upload():
    f = request.files.get("excel_file")
    if not f or not f.filename:
        flash("请选择文件", "error")
        return redirect(url_for("admin_dashboard"))

    ext = f.filename.rsplit(".", 1)[-1].lower()
    if ext not in Config.ALLOWED_EXTENSIONS:
        flash("只支持 .xlsx 或 .xls 文件", "error")
        return redirect(url_for("admin_dashboard"))

    os.makedirs(Config.DATA_DIR, exist_ok=True)
    f.save(Config.EXCEL_PATH)

    # Auto-assign unique codes to any new orders that lack one
    new_codes = assign_qr_codes()
    orders = load_orders()
    msg = f"上传成功，共 {len(orders)} 条订单"
    if new_codes:
        msg += f"，为 {new_codes} 条新订单生成了镜片码"
    flash(msg, "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Admin: generate QR codes
# ---------------------------------------------------------------------------
@app.route("/admin/print_label/<order_id>")
@admin_required
def print_label(order_id):
    orders = load_orders()
    order = orders.get(order_id)
    if order is None or not order.get("qr_code"):
        abort(404)
    png = generate_label_image(order)
    return send_file(
        io.BytesIO(png),
        mimetype="image/png",
        as_attachment=True,
        download_name=f"label_{order_id}.png",
    )


@app.route("/admin/generate_qr/<order_id>")
@admin_required
def generate_single_qr(order_id):
    orders = load_orders()
    order = orders.get(order_id)
    if order is None or not order.get("qr_code"):
        abort(404)
    png = generate_qr_png(order["qr_code"], label=order_id, save_to_disk=True)
    return send_file(
        io.BytesIO(png),
        mimetype="image/png",
        as_attachment=True,
        download_name=f"{order_id}.png",
    )


@app.route("/admin/generate_qr_all")
@admin_required
def generate_all_qr():
    orders = load_orders()
    if not orders:
        flash("没有订单数据，请先上传 Excel", "error")
        return redirect(url_for("admin_dashboard"))
    zip_bytes = generate_all_zip(orders)
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name="all_qrcodes.zip",
    )


# ---------------------------------------------------------------------------
# Admin: factory export package
# ---------------------------------------------------------------------------
@app.route("/admin/factory_export")
@admin_required
def factory_export():
    # Ensure all orders have a QR code assigned before exporting
    assign_qr_codes()
    orders = load_orders()
    if not orders:
        flash("没有订单数据，请先上传 Excel", "error")
        return redirect(url_for("admin_dashboard"))
    zip_bytes = generate_factory_zip(orders, Config.EXCEL_PATH)
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name="factory_package.zip",
    )


# ---------------------------------------------------------------------------
# Feishu webhook: order confirmed → generate QR → write back to Bitable
# ---------------------------------------------------------------------------
#
# Feishu automation setup (飞书多维表格 → 自动化):
#   Trigger : 订单状态 field changes to "已确认"
#   Action  : Send HTTP request
#     Method : POST
#     URL    : https://<your-domain>/api/feishu/order_confirmed
#     Headers: Content-Type: application/json
#              X-Webhook-Secret: <FEISHU_WEBHOOK_SECRET>
#     Body   : {
#                "record_id": "{{record_id}}",
#                "order_id":  "{{订单号}}",
#                "patient":   "{{患者姓名}}"
#              }
#
# On success the endpoint:
#   1. Generates a unique 16-char hex lens code (镜片码)
#   2. Renders a QR code PNG pointing to /verify/<lens_code>
#   3. Uploads the PNG to Feishu Drive → gets file_token
#   4. PATCHes the Bitable record:  镜片码 = lens_code, 二维码图片 = [file_token]
#   5. Returns {"ok": true, "lens_code": "..."}

@app.route("/api/feishu/order_confirmed", methods=["POST"])
def feishu_order_confirmed():
    # 1. Verify shared secret
    secret = request.headers.get("X-Webhook-Secret", "")
    expected = Config.FEISHU_WEBHOOK_SECRET
    if not hmac.compare_digest(secret, expected):
        logger.warning("Webhook rejected: bad secret")
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    # 2. Parse body
    body = request.get_json(silent=True) or {}
    record_id = body.get("record_id", "").strip()
    order_id  = body.get("order_id", "").strip()
    patient   = body.get("patient", "").strip()

    if not record_id or not order_id:
        return jsonify({"ok": False, "error": "record_id and order_id required"}), 400

    try:
        # 3. Generate unique lens code
        lens_code = uuid.uuid4().hex[:16].upper()

        # 4. Generate QR PNG and save to disk (for production export)
        generate_qr_png(lens_code, label=order_id, save_to_disk=True)

        # 5. Write lens_code back to the Bitable record
        update_order_record(record_id, lens_code)

        logger.info("order_confirmed ok: order=%s lens=%s record=%s",
                    order_id, lens_code, record_id)
        return jsonify({"ok": True, "lens_code": lens_code, "order_id": order_id})

    except Exception as exc:
        logger.exception("order_confirmed failed for order=%s", order_id)
        return jsonify({"ok": False, "error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
