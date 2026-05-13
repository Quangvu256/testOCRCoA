"""
ocr_extractor.py — OCR + Extraction gộp trong 1 API call [P2 Cost]
Gemini Flash multimodal: PDF bytes → structured JSON trực tiếp.
Không cần bước trung gian OCR → Markdown → Parse.
"""
import json
import re
import os
from datetime import datetime
from typing import Optional

from google import genai
from google.genai import types

# ── Thêm parent dir vào path để import config ────────────
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import OCR_MODEL, VERTEX_PROJECT, VERTEX_LOCATION, CREDENTIAL_PATH
from models import CoARecord, DeliveryRecord


# ── Prompt tối ưu token [P2] ─────────────────────────────
COA_SYSTEM_PROMPT = """You are a document data extractor. Extract raw material info from this Certificate of Analysis (CoA) PDF.

Return a JSON array. Each element = 1 raw material found in the document.
```json
[
  {
    "ten_nguyen_lieu": "Product name / Material name",
    "so_lo": "Lot/Batch number",
    "ngay_san_xuat": "DD/MM/YYYY or null",
    "han_su_dung": "DD/MM/YYYY or null"
  }
]
```

Rules:
- Convert ALL dates to DD/MM/YYYY format
- If a date is missing, use null
- If multiple products on different pages, return array with multiple objects
- Return ONLY the JSON array, no extra text
- Product name should be the full commercial/chemical name as written"""

DELIVERY_SYSTEM_PROMPT = """You are a document data extractor. Extract delivery info from this delivery document (Biên bản giao hàng / Hóa đơn).

Return a JSON array. Each element = 1 material in the delivery:
```json
[
  {
    "ten_nguyen_lieu": "Material name as written",
    "so_luong_kg": 25.0,
    "so_pack": 2
  }
]
```

Rules:
- so_luong_kg = weight in kg (number or null)
- so_pack = number of packages/drums/bags (number or null)
- Return ONLY the JSON array, no extra text"""


def _get_client() -> genai.Client:
    """Tạo Gemini client qua Enterprise mode (Gemini 3.1 Flash Lite).
    Ref: Google documentation — enterprise=True, location='global'.
    """
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIAL_PATH
    client = genai.Client(
        enterprise=True,
        project=VERTEX_PROJECT,
        location=VERTEX_LOCATION,  # 'global' per documentation
    )
    return client


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse nhiều date format → datetime object.
    Hỗ trợ: DD/MM/YYYY, YYYY-MM-DD, DD-Mon-YYYY, DD.MM.YYYY, MM/DD/YYYY
    """
    if not date_str or date_str.strip().lower() == "null":
        return None

    date_str = date_str.strip()

    # Thử nhiều format phổ biến
    formats = [
        "%d/%m/%Y",      # DD/MM/YYYY
        "%Y-%m-%d",      # YYYY-MM-DD
        "%d-%m-%Y",      # DD-MM-YYYY
        "%d.%m.%Y",      # DD.MM.YYYY
        "%d-%b-%Y",      # DD-Mon-YYYY (e.g. 15-Jan-2024)
        "%d %b %Y",      # DD Mon YYYY
        "%d %B %Y",      # DD Month YYYY
        "%Y/%m/%d",      # YYYY/MM/DD
        "%m/%d/%Y",      # MM/DD/YYYY (fallback)
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    # Regex fallback cho trường hợp lạ
    # Tìm pattern số ngày/tháng/năm
    match = re.search(r'(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})', date_str)
    if match:
        d, m, y = int(match.group(1)), int(match.group(2)), int(match.group(3))
        try:
            return datetime(y, m, d)
        except ValueError:
            try:
                return datetime(y, d, m)  # swap day/month
            except ValueError:
                pass

    return None


def _extract_json_from_response(text: str) -> list:
    """Trích xuất JSON array từ response (có thể chứa markdown fence)."""
    # Bỏ markdown code fence nếu có
    text = text.strip()
    if text.startswith("```"):
        # Bỏ dòng đầu (```json) và dòng cuối (```)
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return [result]
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        # Thử tìm JSON array trong text
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return []


def extract_coa(pdf_bytes: bytes) -> list[CoARecord]:
    """
    PDF bytes (CoA) → list[CoARecord]
    1 API call multimodal: Gemini đọc PDF trực tiếp + extract structured data.
    """
    client = _get_client()

    # Tạo Part từ PDF bytes
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    response = client.models.generate_content(
        model=OCR_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    pdf_part,
                    types.Part.from_text(text=COA_SYSTEM_PROMPT),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.1,  # Low temp cho extraction chính xác
            max_output_tokens=4096,
        ),
    )

    raw_items = _extract_json_from_response(response.text)

    records = []
    for item in raw_items:
        records.append(CoARecord(
            ten_nguyen_lieu=item.get("ten_nguyen_lieu", "").strip(),
            so_lo=str(item.get("so_lo", "")).strip(),
            ngay_san_xuat=_parse_date(item.get("ngay_san_xuat")),
            han_su_dung=_parse_date(item.get("han_su_dung")),
        ))

    return records


def extract_delivery(pdf_bytes: bytes) -> list[DeliveryRecord]:
    """
    PDF bytes (Biên bản đơn hàng) → list[DeliveryRecord]
    1 API call multimodal.
    """
    client = _get_client()

    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    response = client.models.generate_content(
        model=OCR_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    pdf_part,
                    types.Part.from_text(text=DELIVERY_SYSTEM_PROMPT),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=4096,
        ),
    )

    raw_items = _extract_json_from_response(response.text)

    records = []
    for item in raw_items:
        # Parse số lượng — có thể là string hoặc number
        so_luong = item.get("so_luong_kg")
        if isinstance(so_luong, str):
            try:
                so_luong = float(so_luong.replace(",", "."))
            except (ValueError, AttributeError):
                so_luong = None

        so_pack = item.get("so_pack")
        if isinstance(so_pack, str):
            try:
                so_pack = int(float(so_pack))
            except (ValueError, AttributeError):
                so_pack = None

        records.append(DeliveryRecord(
            ten_nguyen_lieu=item.get("ten_nguyen_lieu", "").strip(),
            so_luong_kg=float(so_luong) if so_luong is not None else None,
            so_pack=int(so_pack) if so_pack is not None else None,
        ))

    return records
