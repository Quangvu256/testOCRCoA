"""
ocr_extractor.py — OCR + Extraction gộp trong 1 API call [P2 Cost]
Gemini Flash multimodal: PDF bytes → structured JSON trực tiếp.
Không cần bước trung gian OCR → Markdown → Parse.
"""
import json
import re
import os
import calendar
import unicodedata
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
    "han_su_dung": "DD/MM/YYYY or null",
    "ten_cong_ty": "Company/manufacturer/supplier name or null",
    "ti_trong": "Specific gravity / ty trong value with unit/range or null",
    "ti_le": "Ratio / percentage / assay/concentration value with unit/range or null",
    "trong_luong_rieng": "Density / trong luong rieng value with unit/range or null"
  }
]
```

Rules:
- Convert ALL dates to DD/MM/YYYY format
- If expiry/HSD is written as shelf life from manufacturing/production date, calculate han_su_dung from ngay_san_xuat.
- Handle English and Vietnamese shelf-life phrases, e.g. "2 years from manufacturing date", "shelf life: 24 months", "2 nam ke tu ngay san xuat", "2 năm kể từ ngày sản xuất".
- If a date is missing, use null
- If company/measurement fields are missing, use null
- Keep ti_trong, ti_le, trong_luong_rieng as raw text including units, %, range, or comparator signs
- ten_cong_ty may be supplier, manufacturer, seller, or company name printed on the CoA
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
    "so_pack": 2,
    "ten_cong_ty": "Company/supplier/seller name or null",
    "ti_trong": "Specific gravity / ty trong value with unit/range or null",
    "ti_le": "Ratio / percentage / concentration value with unit/range or null",
    "trong_luong_rieng": "Density / trong luong rieng value with unit/range or null"
  }
]
```

Rules:
- so_luong_kg = weight in kg (number or null)
- so_pack = number of packages/drums/bags (number or null)
- If company/measurement fields are missing, use null
- Keep ti_trong, ti_le, trong_luong_rieng as raw text including units, %, range, or comparator signs
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
    if not date_str:
        return None

    date_str = str(date_str).strip()
    if date_str.lower() == "null":
        return None

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


def _strip_accents(text: str) -> str:
    """Remove accents for bilingual shelf-life phrase matching."""
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _add_months(date_value: datetime, months: int) -> datetime:
    """Add calendar months, clamping day to the target month's last day."""
    month_index = date_value.month - 1 + months
    year = date_value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(date_value.day, calendar.monthrange(year, month)[1])
    return date_value.replace(year=year, month=month, day=day)


def _add_years(date_value: datetime, years: int) -> datetime:
    """Add calendar years, handling leap-day dates."""
    try:
        return date_value.replace(year=date_value.year + years)
    except ValueError:
        return date_value.replace(year=date_value.year + years, month=2, day=28)


def _extract_duration(text: str) -> tuple[float, str] | None:
    """Extract shelf-life duration from English/Vietnamese text."""
    text_norm = _strip_accents(text.lower())
    text_norm = re.sub(r"[\(\)\[\]:;,_]", " ", text_norm)
    text_norm = re.sub(r"\s+", " ", text_norm).strip()

    number_match = re.search(
        r"\b(\d+(?:[\.,]\d+)?)\s*(years?|yrs?|year|months?|mos?|month|nam|thang)\b",
        text_norm,
    )
    if number_match:
        amount = float(number_match.group(1).replace(",", "."))
        return amount, number_match.group(2)

    word_numbers = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "mot": 1,
        "một": 1,
        "hai": 2,
        "ba": 3,
        "bon": 4,
        "bốn": 4,
        "nam": 5,
        "năm": 5,
        "sau": 6,
        "sáu": 6,
        "bay": 7,
        "bảy": 7,
        "tam": 8,
        "tám": 8,
        "chin": 9,
        "chín": 9,
        "muoi": 10,
        "mười": 10,
    }
    unit_pattern = r"(years?|yrs?|year|months?|mos?|month|nam|thang)"
    for word, amount in word_numbers.items():
        word_norm = _strip_accents(word.lower())
        match = re.search(rf"\b{re.escape(word_norm)}\s+{unit_pattern}\b", text_norm)
        if match:
            return float(amount), match.group(1)

    return None


def _parse_expiry_date(expiry_value, manufacturing_date: Optional[datetime]) -> Optional[datetime]:
    """Parse direct expiry date or infer it from shelf-life text + manufacturing date."""
    direct_date = _parse_date(expiry_value)
    if direct_date:
        return direct_date

    if not expiry_value or not manufacturing_date:
        return None

    duration = _extract_duration(str(expiry_value))
    if not duration:
        return None

    amount, unit = duration
    if unit in {"year", "years", "yr", "yrs", "nam"}:
        if amount.is_integer():
            return _add_years(manufacturing_date, int(amount))
        return _add_months(manufacturing_date, int(round(amount * 12)))

    if unit in {"month", "months", "mo", "mos", "thang"}:
        return _add_months(manufacturing_date, int(round(amount)))

    return None


def _clean_optional_text(value) -> Optional[str]:
    """Normalize optional OCR text fields while preserving units/ranges."""
    if value is None:
        return None

    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "na", "-"}:
        return None
    return text


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
        ngay_san_xuat = _parse_date(item.get("ngay_san_xuat"))
        records.append(CoARecord(
            ten_nguyen_lieu=str(item.get("ten_nguyen_lieu") or "").strip(),
            so_lo=str(item.get("so_lo") or "").strip(),
            ngay_san_xuat=ngay_san_xuat,
            han_su_dung=_parse_expiry_date(item.get("han_su_dung"), ngay_san_xuat),
            ten_cong_ty=_clean_optional_text(item.get("ten_cong_ty")),
            ti_trong=_clean_optional_text(item.get("ti_trong")),
            ti_le=_clean_optional_text(item.get("ti_le")),
            trong_luong_rieng=_clean_optional_text(item.get("trong_luong_rieng")),
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
            ten_nguyen_lieu=str(item.get("ten_nguyen_lieu") or "").strip(),
            so_luong_kg=float(so_luong) if so_luong is not None else None,
            so_pack=int(so_pack) if so_pack is not None else None,
            ten_cong_ty=_clean_optional_text(item.get("ten_cong_ty")),
            ti_trong=_clean_optional_text(item.get("ti_trong")),
            ti_le=_clean_optional_text(item.get("ti_le")),
            trong_luong_rieng=_clean_optional_text(item.get("trong_luong_rieng")),
        ))

    return records
