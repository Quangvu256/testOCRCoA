"""
models.py — Data contracts cho toàn bộ pipeline [P1 Fact]
Đảm bảo mỗi module có Input→Transform→Output rõ ràng.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CoARecord:
    """Dữ liệu trích xuất từ Certificate of Analysis (1 nguyên liệu)."""
    ten_nguyen_lieu: str
    so_lo: str
    ngay_san_xuat: Optional[datetime] = None
    han_su_dung: Optional[datetime] = None


@dataclass
class DeliveryRecord:
    """Dữ liệu trích xuất từ Biên bản đơn hàng / Hóa đơn giao hàng."""
    ten_nguyen_lieu: str
    so_luong_kg: Optional[float] = None
    so_pack: Optional[int] = None


@dataclass
class MaterialMatch:
    """Kết quả lookup từ DB — 1 nguyên liệu đã match."""
    ma_hc: str
    ten_nguyen_lieu_db: str
    ten_ke_toan: str
    confidence: str  # 'exact' | 'normalized' | 'alias' | 'fuzzy' | 'manual'
    score: float = 1.0


@dataclass
class OutputRecord:
    """Record hoàn chỉnh cho Excel export — 1 dòng trong file .xlsx."""
    stt: int
    ngay_nhap: datetime
    ma_hc: str
    ten_nl: str
    ten_ke_toan: str
    so_lo: str
    so_luong_kg: Optional[float] = None
    so_pack: Optional[int] = None
    ngay_sx: Optional[datetime] = None
    hsd: Optional[datetime] = None
    thoi_gian_hsd_con_lai: Optional[int] = None  # số ngày còn lại

    def calculate_remaining_days(self):
        """Tính số ngày HSD còn lại."""
        if self.hsd:
            self.thoi_gian_hsd_con_lai = (self.hsd - datetime.now()).days
