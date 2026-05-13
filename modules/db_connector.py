"""
db_connector.py — Database integration + 5-step matching pipeline
- Connection pool + cache [P2 Cost]
- Reuse normalize_name() từ add_accounting_name.py [P1 Fact]
- Step 5: AI matching via Gemini 3.1 Flash Lite [NEW]
- Alias table auto-learn
"""
import json
import re
import os
import sys
from typing import Optional

import psycopg2
from psycopg2 import sql

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_CONFIG, FUZZY_THRESHOLD, OCR_MODEL, VERTEX_PROJECT, VERTEX_LOCATION, CREDENTIAL_PATH
from models import MaterialMatch


# ── Normalize — reuse logic đã proven từ add_accounting_name.py ──
def normalize_name(name: str) -> str:
    """Chuẩn hóa tên để so sánh: viết thường, bỏ dấu cách thừa, bỏ ký tự đặc biệt.
    [FACT] Logic này đã hoạt động tốt với 255 records trong add_accounting_name.py.
    """
    if not name:
        return ""
    text = name.lower().strip()
    # Bỏ các ký tự đặc biệt, giữ lại chữ cái, số và khoảng trắng (bao gồm tiếng Việt)
    text = re.sub(
        r'[^a-z0-9\sàáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ]',
        '', text
    )
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _keyword_overlap_score(name_a: str, name_b: str) -> float:
    """Tính score dựa trên từ khóa chung.
    [FACT] Reuse logic từ add_accounting_name.py (line 120-136).
    """
    words_a = set(normalize_name(name_a).split())
    words_b = set(normalize_name(name_b).split())

    if not words_a or not words_b:
        return 0.0

    # Chỉ đếm từ có ý nghĩa (> 2 ký tự)
    significant_common = {w for w in (words_a & words_b) if len(w) > 2}

    if not significant_common:
        return 0.0

    return len(significant_common) / max(len(words_a), len(words_b))


# ── AI Matching via Gemini ────────────────────────────────
def _ai_match_material(ocr_name: str, candidates: list[dict]) -> Optional[dict]:
    """[Step 5] Dùng Gemini 3.1 Flash Lite để so sánh ngữ nghĩa.
    Gửi tên OCR + danh sách ứng viên → AI chọn match tốt nhất.
    
    Xử lý: tên thương mại vs tên hóa học, viết tắt, ngôn ngữ khác nhau,
    tên nhà cung cấp khác nhau cho cùng 1 nguyên liệu.
    
    Returns: dict {"ma_hc": ..., "confidence": float} hoặc None
    """
    from google import genai
    from google.genai import types

    # Giới hạn 30 candidates để tiết kiệm token [P2 Cost]
    candidate_lines = []
    for i, c in enumerate(candidates[:30]):
        candidate_lines.append(
            f'{i+1}. [{c["ma_hc"]}] "{c["ten_nguyen_lieu"]}" (kế toán: "{c["ten_ke_toan"]}")'
        )
    candidates_text = "\n".join(candidate_lines)

    prompt = f"""Bạn là chuyên gia hóa mỹ phẩm. So sánh tên nguyên liệu OCR với danh sách DB.

**Tên OCR:** "{ocr_name}"

**Danh sách DB:**
{candidates_text}

Hãy chọn nguyên liệu match tốt nhất. Lưu ý:
- Cùng 1 chất có thể có nhiều tên thương mại khác nhau (ví dụ: Texapon = SLS = SLES)
- Tên OCR có thể bị sai chính tả do scan
- Cân nhắc cả tên hóa học, tên thương mại, và tên kế toán
- Nếu KHÔNG có nguyên liệu nào phù hợp, trả về null

Trả về JSON (KHÔNG có text khác):
{{"index": <số thứ tự 1-based hoặc null>, "confidence": <0.0-1.0>, "reason": "lý do ngắn"}}"""

    try:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIAL_PATH
        client = genai.Client(
            enterprise=True,
            project=VERTEX_PROJECT,
            location=VERTEX_LOCATION,
        )

        response = client.models.generate_content(
            model=OCR_MODEL,
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=256),
        )

        # Parse response
        text = response.text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        result = json.loads(text)
        idx = result.get("index")
        confidence = float(result.get("confidence", 0))

        if idx is not None and 1 <= idx <= len(candidates) and confidence >= 0.6:
            matched_candidate = candidates[idx - 1]
            return {
                "ma_hc": matched_candidate["ma_hc"],
                "ten_nguyen_lieu": matched_candidate["ten_nguyen_lieu"],
                "ten_ke_toan": matched_candidate["ten_ke_toan"],
                "confidence": confidence,
                "reason": result.get("reason", ""),
            }
    except Exception:
        pass  # AI match thất bại → fallback manual

    return None


class DBConnector:
    """Singleton-like DB connector với cache [P2 Cost].
    Load toàn bộ raw_materials + aliases vào memory 1 lần → tránh query liên tục.
    """

    def __init__(self):
        self._conn: Optional[psycopg2.extensions.connection] = None
        self._materials_cache: list[dict] = []
        self._alias_cache: dict[str, MaterialMatch] = {}  # normalized_ocr_name → match
        self._is_loaded = False

    # ── Connection ────────────────────────────────────────

    def get_connection(self) -> psycopg2.extensions.connection:
        """Lấy hoặc tạo mới connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(**DB_CONFIG)
        return self._conn

    def check_health(self) -> tuple[bool, str]:
        """Kiểm tra kết nối DB. Trả về (ok, message)."""
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM raw_materials")
                count = cur.fetchone()[0]
            return True, f"✅ Kết nối DB thành công ({count} nguyên liệu)"
        except Exception as e:
            return False, f"❌ Lỗi kết nối DB: {e}"

    # ── Cache loading ─────────────────────────────────────

    def load_cache(self):
        """Load toàn bộ raw_materials + aliases vào memory. Gọi 1 lần khi startup."""
        conn = self.get_connection()
        with conn.cursor() as cur:
            # Load materials
            cur.execute("SELECT ma_hc, ten_nguyen_lieu, chuc_nang, ten_ke_toan FROM raw_materials")
            self._materials_cache = [
                {
                    "ma_hc": row[0] or "",
                    "ten_nguyen_lieu": row[1] or "",
                    "chuc_nang": row[2] or "",
                    "ten_ke_toan": row[3] or "",
                }
                for row in cur.fetchall()
            ]

            # Load aliases (nếu table tồn tại)
            try:
                cur.execute("SELECT ocr_name, matched_ma_hc, matched_ten_nl, confidence FROM material_aliases")
                for row in cur.fetchall():
                    ocr_name_norm = normalize_name(row[0])
                    # Tìm ten_ke_toan từ materials cache
                    ten_ke_toan = ""
                    for mat in self._materials_cache:
                        if mat["ma_hc"].upper() == (row[1] or "").upper():
                            ten_ke_toan = mat["ten_ke_toan"]
                            break
                    self._alias_cache[ocr_name_norm] = MaterialMatch(
                        ma_hc=row[1] or "",
                        ten_nguyen_lieu_db=row[2] or "",
                        ten_ke_toan=ten_ke_toan,
                        confidence=row[3] or "alias",
                        score=1.0,
                    )
            except psycopg2.errors.UndefinedTable:
                conn.rollback()  # Table chưa tồn tại — OK, sẽ tạo sau

        self._is_loaded = True

    def get_all_materials(self) -> list[dict]:
        """Trả về toàn bộ materials từ cache."""
        if not self._is_loaded:
            self.load_cache()
        return self._materials_cache

    # ── 5-step matching pipeline ──────────────────────────

    def lookup(self, ocr_name: str, use_ai: bool = True) -> Optional[MaterialMatch]:
        """
        5-step matching: Exact → Normalized → Alias → Keyword overlap → AI (Gemini).
        use_ai=True sẽ gọi Gemini khi 4 bước đầu thất bại.
        """
        if not self._is_loaded:
            self.load_cache()

        if not ocr_name or not ocr_name.strip():
            return None

        ocr_norm = normalize_name(ocr_name)

        # ── Step 1: Exact match ──
        for mat in self._materials_cache:
            if mat["ten_nguyen_lieu"].strip() == ocr_name.strip():
                return MaterialMatch(
                    ma_hc=mat["ma_hc"],
                    ten_nguyen_lieu_db=mat["ten_nguyen_lieu"],
                    ten_ke_toan=mat["ten_ke_toan"],
                    confidence="exact",
                    score=1.0,
                )

        # ── Step 2: Normalized match ──
        for mat in self._materials_cache:
            if normalize_name(mat["ten_nguyen_lieu"]) == ocr_norm:
                return MaterialMatch(
                    ma_hc=mat["ma_hc"],
                    ten_nguyen_lieu_db=mat["ten_nguyen_lieu"],
                    ten_ke_toan=mat["ten_ke_toan"],
                    confidence="normalized",
                    score=1.0,
                )

        # ── Step 3: Alias table match ──
        if ocr_norm in self._alias_cache:
            alias = self._alias_cache[ocr_norm]
            return MaterialMatch(
                ma_hc=alias.ma_hc,
                ten_nguyen_lieu_db=alias.ten_nguyen_lieu_db,
                ten_ke_toan=alias.ten_ke_toan,
                confidence="alias",
                score=1.0,
            )

        # ── Step 4: Keyword overlap (fuzzy) ──
        best_match = None
        best_score = 0.0

        for mat in self._materials_cache:
            # So sánh với cả tên NL và tên kế toán
            for candidate_name in [mat["ten_nguyen_lieu"], mat["ten_ke_toan"]]:
                score = _keyword_overlap_score(ocr_name, candidate_name)
                if score > best_score and score >= FUZZY_THRESHOLD:
                    best_score = score
                    best_match = MaterialMatch(
                        ma_hc=mat["ma_hc"],
                        ten_nguyen_lieu_db=mat["ten_nguyen_lieu"],
                        ten_ke_toan=mat["ten_ke_toan"],
                        confidence="fuzzy",
                        score=score,
                    )

        if best_match:
            return best_match

        # ── Step 5: AI matching (Gemini 3.1 Flash Lite) ──
        if use_ai:
            ai_result = _ai_match_material(ocr_name, self._materials_cache)
            if ai_result:
                return MaterialMatch(
                    ma_hc=ai_result["ma_hc"],
                    ten_nguyen_lieu_db=ai_result["ten_nguyen_lieu"],
                    ten_ke_toan=ai_result["ten_ke_toan"],
                    confidence="ai",
                    score=ai_result["confidence"],
                )

        return None  # Không match → cần manual input

    # ── Alias management ──────────────────────────────────

    def ensure_alias_table(self):
        """[P0 Escalation] Tạo bảng material_aliases nếu chưa tồn tại."""
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS material_aliases (
                    id SERIAL PRIMARY KEY,
                    ocr_name VARCHAR(500) NOT NULL UNIQUE,
                    matched_ma_hc VARCHAR(50) NOT NULL,
                    matched_ten_nl VARCHAR(500),
                    confidence VARCHAR(20) DEFAULT 'manual',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        conn.commit()

    def save_alias(self, ocr_name: str, ma_hc: str, ten_nl: str, confidence: str = "manual"):
        """Lưu alias mới vào DB + cập nhật cache."""
        conn = self.get_connection()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO material_aliases (ocr_name, matched_ma_hc, matched_ten_nl, confidence)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ocr_name) DO UPDATE
                SET matched_ma_hc = EXCLUDED.matched_ma_hc,
                    matched_ten_nl = EXCLUDED.matched_ten_nl,
                    confidence = EXCLUDED.confidence
            """, (ocr_name, ma_hc, ten_nl, confidence))
        conn.commit()

        # Update cache
        ten_ke_toan = ""
        for mat in self._materials_cache:
            if mat["ma_hc"].upper() == ma_hc.upper():
                ten_ke_toan = mat["ten_ke_toan"]
                break
        self._alias_cache[normalize_name(ocr_name)] = MaterialMatch(
            ma_hc=ma_hc,
            ten_nguyen_lieu_db=ten_nl,
            ten_ke_toan=ten_ke_toan,
            confidence=confidence,
            score=1.0,
        )

    def close(self):
        """Đóng connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
