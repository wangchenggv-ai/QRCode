import os
import io
import functools
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for,
    request, session, send_file, flash, abort,
)
from config import Config
from utils.excel_reader import load_orders, get_order
from utils.qr_generator import generate_qr_png, generate_zip

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH


# ---------------------------------------------------------------------------
# Template context
# ---------------------------------------------------------------------------
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


@app.route("/verify/<order_id>")
def verify(order_id):
    order = get_order(order_id)
    if order is None:
        return render_template("verify.html", found=False, order_id=order_id), 404
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
    flash(f"Excel 上传成功，共载入 {len(load_orders())} 条订单", "success")
    return redirect(url_for("admin_dashboard"))


# ---------------------------------------------------------------------------
# Admin: generate QR codes
# ---------------------------------------------------------------------------
@app.route("/admin/generate_qr/<order_id>")
@admin_required
def generate_single_qr(order_id):
    if get_order(order_id) is None:
        abort(404)
    png = generate_qr_png(order_id, save_to_disk=True)
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
    zip_bytes = generate_zip(list(orders.keys()))
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name="all_qrcodes.zip",
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
