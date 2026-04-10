# Lens QR Code Traceability System (镜片溯源二维码验证系统)

## Project Location

`C:\Users\wangc\QRCode\`

## What It Does

A Flask web application for **eyeglass lens anti-counterfeiting and traceability**. It generates unique QR codes for each lens order, provides a public verification page for end users, and exports print-ready label packages for the factory.

### Core Workflow

1. **Upload** an Excel file with lens orders (order ID, customer, L/R eye SPH/CYL, production date, notes)
2. **Auto-assign** a unique 16-character hex code (镜片码) to each order
3. **Generate QR codes** that link to `{server}/verify/{code}` for public verification
4. **Export factory package** — a ZIP containing:
   - `labels/` — print-ready labels (QR + prescription info, 300 DPI, 6cm x 3cm)
   - `qrcodes/` — standalone high-res QR images (1000x1000px)
   - `orders_with_codes.xlsx` — Excel with 镜片码 column filled in
   - `说明.txt` — factory usage instructions

### User-Facing Features

- **Public verification page** (`/verify/<code>`) — scan QR code to see order details and confirm authenticity, styled with GAUSH|CLEAR branding
- **Admin dashboard** (`/admin`) — password-protected, upload Excel, view all orders, generate QR codes individually or in bulk, export factory package
- **Sample data** — auto-generates on first run for out-of-box demo

## File Structure

```
app.py                  # Flask application (routes, auth, file handling)
config.py               # Configuration (passwords, paths, QR settings)
requirements.txt        # Python dependencies
Dockerfile              # Production container with Chinese font support
docker-compose.yml      # One-command deployment

utils/
  excel_reader.py       # Excel parsing, QR code assignment, caching by mtime
  qr_generator.py       # QR code image generation (with label text)
  label_generator.py    # Print-ready factory labels (QR + prescription table)

templates/
  base.html             # Base template with flash messages
  index.html            # Public landing page
  verify.html           # Public verification result page
  admin.html            # Admin dashboard
  admin_login.html      # Admin login form

static/
  css/style.css         # Full responsive styling
  qrcodes/              # Generated QR code PNGs

data/
  orders.xlsx           # Current order data (uploaded or sample)
```

## Tech Stack

- **Backend:** Python 3.11+ / Flask 3.0
- **Excel:** openpyxl
- **QR Code:** qrcode + Pillow (PIL)
- **Production:** Gunicorn + Docker
- **Fonts:** WenQuanYi Zen Hei (for Chinese text on labels)

## Configuration

| Setting | Default | Env Var |
|---------|---------|---------|
| Admin password | `admin123` | `ADMIN_PASSWORD` |
| Server base URL | `http://192.168.1.29:5000` | `SERVER_BASE_URL` |
| Secret key | (hardcoded) | `SECRET_KEY` |
| Max upload size | 16 MB | — |

## Quick Start

### Local

```bash
cd QRCode
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

### Docker

```bash
docker compose up -d
# Open http://localhost:5000
```

## Git History

| Commit | Description |
|--------|-------------|
| `037c149` | Initial lens traceability QR verification system |
| `00222d9` | Use unique random 镜片码 instead of guessable order IDs |
| `8055271` | Add factory print package export (labels + QR + Excel) |
| `3021d19` | Update sample orders.xlsx with auto-generated 镜片码 |
| `e862510` | Add Docker support (Dockerfile + docker-compose.yml) |
| `dfb5d06` | Auto-generate sample data on first startup |
| `962012e` | Show "load sample data" button when order list is empty |
| `8422ac3` | Apply GAUSH\|CLEAR brand styling (dark blue-purple gradient) |

## Security Notes

- Admin password and secret key should be changed via environment variables in production
- QR codes use ERROR_CORRECT_H (30% recovery) for physical print durability
- Each 镜片码 is a random UUID-based hex string — not guessable from order ID
