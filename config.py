import os

class Config:
    # Security
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production-use-random-hex")

    # Paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = os.path.join(BASE_DIR, "data")
    EXCEL_PATH = os.path.join(DATA_DIR, "orders.xlsx")
    QR_DIR = os.path.join(BASE_DIR, "static", "qrcodes")

    # Server — set SERVER_BASE_URL to your public domain in production
    SERVER_BASE_URL = os.environ.get("SERVER_BASE_URL", "http://192.168.1.29:5000")

    # QR code appearance
    QR_BOX_SIZE = 10   # pixels per QR module
    QR_BORDER = 4      # quiet-zone modules

    # Upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    ALLOWED_EXTENSIONS = {"xlsx", "xls"}

    # Feishu integration
    FEISHU_APP_ID     = os.environ.get("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
    # Shared secret between Feishu automation webhook and this server
    FEISHU_WEBHOOK_SECRET = os.environ.get("FEISHU_WEBHOOK_SECRET", "change-me")
    # Bitable where orders live
    FEISHU_BITABLE_APP_TOKEN = os.environ.get("FEISHU_BITABLE_APP_TOKEN", "")
    FEISHU_ORDER_TABLE_ID    = os.environ.get("FEISHU_ORDER_TABLE_ID", "")
    # Notifications: internal group chat ID for alerts (oc_xxxxxxxx)
    FEISHU_NOTIFY_CHAT_ID = os.environ.get("FEISHU_NOTIFY_CHAT_ID", "")
    # Orders older than this many days trigger an overdue alert
    FEISHU_OVERDUE_DAYS = int(os.environ.get("FEISHU_OVERDUE_DAYS", "8"))
