import os
import io
import functools
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for,
    request, session, send_file, flash, abort,
)
from config import Config
from utils.excel_reader import load_orders, get_order_by_qr, assign_qr_codes
from utils.qr_generator import generate_qr_png, generate_all_zip
from utils.label_generator import generate_factory_zip

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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
