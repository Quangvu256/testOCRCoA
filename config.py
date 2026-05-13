"""
config.py — Centralized configuration [P0 Safety]
Tách credentials ra khỏi code, load từ .env
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env từ thư mục project
load_dotenv(Path(__file__).parent / ".env")

# ── Database ──────────────────────────────────────────────
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),  # [FACT] docker-compose default 5432
    "database": os.getenv("DB_NAME", "pif_db"),
    "user": os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD", "adminpassword"),
}

# ── Vertex AI / Gemini ────────────────────────────────────
VERTEX_PROJECT = os.getenv("VERTEX_PROJECT", "your-project-id")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "global")  # [FACT] enterprise mode uses 'global'
CREDENTIAL_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    str(Path(__file__).parent / "credentials.json"),
)

# Model — Gemini 3.1 Flash Lite GA (doc: 2026-05-07)
# https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/gemini
OCR_MODEL = "gemini-3.1-flash-lite"

# ── Matching ──────────────────────────────────────────────
FUZZY_THRESHOLD = float(os.getenv("FUZZY_THRESHOLD", "0.4"))  # [FACT] ngưỡng keyword overlap

# ── Excel ─────────────────────────────────────────────────
EXPIRY_WARNING_DAYS = int(os.getenv("EXPIRY_WARNING_DAYS", "90"))  # Ngưỡng cảnh báo HSD (ngày)
