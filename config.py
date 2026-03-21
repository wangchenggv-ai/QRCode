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
    SERVER_BASE_URL = os.environ.get("SERVER_BASE_URL", "http://localhost:5000")

    # QR code appearance
    QR_BOX_SIZE = 10   # pixels per QR module
    QR_BORDER = 4      # quiet-zone modules

    # Upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    ALLOWED_EXTENSIONS = {"xlsx", "xls"}
