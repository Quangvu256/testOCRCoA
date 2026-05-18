"""
app.py — Streamlit UI cho Hệ thống Nhập liệu Nguyên liệu Tự động
v2: Multi-batch loading + AI matching
Luồng: Upload nhiều lần PDF → OCR+Extract → DB Lookup (5-step + AI) → Tổng hợp → Download .xlsx
"""
import os
import sys
from datetime import datetime

import streamlit as st
import pandas as pd

# ── Path setup ────────────────────────────────────────────
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from config import EXPIRY_WARNING_DAYS
from models import OutputRecord
from modules.ocr_extractor import extract_coa, extract_delivery
from modules.db_connector import DBConnector, normalize_name, _keyword_overlap_score
from modules.excel_generator import generate_xlsx

# ── Page config ───────────────────────────────────────────
st.set_page_config(
    page_title="Nhập liệu Nguyên liệu Tự động",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5f8a 50%, #4a90d9 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
        text-align: center;
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.8rem; }
    .main-header p { color: #c8ddf0; margin: 0.3rem 0 0 0; font-size: 0.95rem; }

    .status-card {
        padding: 0.8rem 1.2rem;
        border-radius: 8px;
        border-left: 4px solid;
        margin-bottom: 0.8rem;
    }
    .status-ok { background: #e8f5e9; border-color: #4caf50; }
    .status-err { background: #ffebee; border-color: #f44336; }
    .status-warn { background: #fff3e0; border-color: #ff9800; }

    [data-testid="stFileUploader"] {
        border: 2px dashed #4a90d9;
        border-radius: 10px;
        padding: 1rem;
    }

    [data-testid="stMetric"] {
        background: #f8f9fa;
        padding: 0.8rem;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
    }

    .batch-badge {
        display: inline-block;
        background: #e3f2fd;
        color: #1565c0;
        padding: 0.2rem 0.6rem;
        border-radius: 12px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .batch-badge-ai {
        background: #f3e5f5;
        color: #7b1fa2;
    }
</style>
""", unsafe_allow_html=True)


# ── Session state init ────────────────────────────────────
def init_session():
    defaults = {
        "db": None,
        "db_ok": False,
        # Multi-batch: danh sách tích lũy tất cả records qua nhiều lần upload
        "all_records": [],         # list[dict] — tích lũy từ mọi batch
        "batch_count": 0,          # Số batch đã xử lý
        "current_batch": None,     # Batch hiện tại đang xử lý
        "xlsx_path": None,
        "alias_table_created": False,
        "use_ai_matching": True,   # Toggle AI matching
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


init_session()


# ── DB Connection (cached) ────────────────────────────────
@st.cache_resource
def get_db_connector() -> DBConnector:
    db = DBConnector()
    return db


# ── Header ────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>📦 Hệ thống Nhập liệu Nguyên liệu Tự động</h1>
    <p>Upload nhiều lần CoA + Biên bản → AI đối chiếu DB → Tổng hợp Excel</p>
</div>
""", unsafe_allow_html=True)


# ── Sidebar: System Status ────────────────────────────────
with st.sidebar:
    st.header("⚙️ Trạng thái hệ thống")

    db = get_db_connector()
    db_ok, db_msg = db.check_health()
    st.session_state.db = db
    st.session_state.db_ok = db_ok

    if db_ok:
        st.markdown(f'<div class="status-card status-ok">{db_msg}</div>', unsafe_allow_html=True)
        if not db._is_loaded:
            db.load_cache()
            st.success(f"📦 Cache: {len(db.get_all_materials())} nguyên liệu")
    else:
        st.markdown(f'<div class="status-card status-err">{db_msg}</div>', unsafe_allow_html=True)
        st.markdown("""
        **Hướng dẫn:**
        1. Mở Docker Desktop
        2. Chạy: `docker-compose up -d` từ thư mục project
        3. Hoặc chạy: `python setup_project.py`
        4. Reload trang này
        """)

    st.divider()

    # AI matching toggle
    st.subheader("🧠 AI Matching")
    st.session_state.use_ai_matching = st.toggle(
        "Bật AI matching (Gemini)",
        value=st.session_state.use_ai_matching,
        help="Khi bật: sử dụng Gemini 3.1 Flash Lite để so sánh ngữ nghĩa khi fuzzy match thất bại",
    )
    if st.session_state.use_ai_matching:
        st.caption("🟢 Pipeline: Exact → Normalize → Alias → Fuzzy → **AI**")
    else:
        st.caption("⚪ Pipeline: Exact → Normalize → Alias → Fuzzy → Manual")

    st.divider()
    st.markdown(f"**Ngưỡng HSD cảnh báo:** {EXPIRY_WARNING_DAYS} ngày")
    st.markdown(f"**Thời gian:** {datetime.now().strftime('%d/%m/%Y %H:%M')}")

    # Multi-batch stats
    st.divider()
    st.subheader("📊 Tổng hợp")
    st.metric("Số batch đã xử lý", st.session_state.batch_count)
    st.metric("Tổng NL đã nhập", len(st.session_state.all_records))

    if st.session_state.all_records and st.button("🗑️ Xóa tất cả dữ liệu", use_container_width=True):
        st.session_state.all_records = []
        st.session_state.batch_count = 0
        st.session_state.current_batch = None
        st.session_state.xlsx_path = None
        st.rerun()

    # Alias table management
    st.divider()
    st.subheader("🗄️ Alias Table")
    if st.button("Tạo/Kiểm tra Alias Table", use_container_width=True):
        try:
            db.ensure_alias_table()
            st.session_state.alias_table_created = True
            st.success("✅ Alias table sẵn sàng")
            db.load_cache()
        except Exception as e:
            st.error(f"❌ Lỗi: {e}")


# ── Main content ──────────────────────────────────────────
if not st.session_state.db_ok:
    st.error("⚠️ Không thể kết nối Database. Vui lòng kiểm tra Docker và reload trang.")
    st.stop()


# ══════════════════════════════════════════════════════════
# STEP 1: Upload files (cho phép upload nhiều lần)
# ══════════════════════════════════════════════════════════
st.header("📤 Bước 1: Upload tài liệu")

if st.session_state.batch_count > 0:
    st.info(f"📦 Đã xử lý **{st.session_state.batch_count} batch** "
            f"({len(st.session_state.all_records)} nguyên liệu). "
            f"Upload thêm để tích lũy hoặc kéo xuống để xuất Excel.")

col1, col2 = st.columns(2)

with col1:
    st.subheader("① CoA (Certificate of Analysis)")
    coa_file = st.file_uploader(
        "Upload file CoA",
        type=["pdf"],
        key=f"coa_upload_{st.session_state.batch_count}",
        help="Phiếu phân tích chất lượng — có thể nhiều trang, mỗi trang 1 NL",
    )
    if coa_file:
        st.success(f"✅ {coa_file.name} ({coa_file.size / 1024:.1f} KB)")

with col2:
    st.subheader("② Biên bản đơn hàng")
    delivery_file = st.file_uploader(
        "Upload biên bản đơn hàng / hóa đơn giao hàng",
        type=["pdf"],
        key=f"delivery_upload_{st.session_state.batch_count}",
        help="Phiếu giao hàng — chứa số lượng kg và số pack",
    )
    if delivery_file:
        st.success(f"✅ {delivery_file.name} ({delivery_file.size / 1024:.1f} KB)")

both_uploaded = coa_file is not None and delivery_file is not None

if not both_uploaded:
    missing = []
    if not coa_file:
        missing.append("CoA")
    if not delivery_file:
        missing.append("Biên bản đơn hàng")
    st.warning(f"⚠️ Cần upload: {', '.join(missing)}")

st.divider()

# ══════════════════════════════════════════════════════════
# STEP 2: Processing (OCR + AI Matching)
# ══════════════════════════════════════════════════════════
st.header("⚡ Bước 2: Xử lý OCR + Trích xuất + AI Matching")

process_btn = st.button(
    f"🚀 Xử lý Batch #{st.session_state.batch_count + 1}",
    disabled=not both_uploaded,
    use_container_width=True,
    type="primary",
)

if process_btn and both_uploaded:
    progress = st.progress(0, text="Đang khởi tạo...")

    try:
        # ── OCR CoA ──
        progress.progress(10, text="📄 Đang OCR file CoA...")
        coa_bytes = coa_file.read()
        coa_records = extract_coa(coa_bytes)
        progress.progress(30, text=f"✅ CoA: {len(coa_records)} nguyên liệu")

        # ── OCR Delivery ──
        progress.progress(35, text="📄 Đang OCR biên bản đơn hàng...")
        delivery_bytes = delivery_file.read()
        delivery_records = extract_delivery(delivery_bytes)
        progress.progress(55, text=f"✅ Delivery: {len(delivery_records)} nguyên liệu")

        # ── Merge CoA + Delivery ──
        progress.progress(60, text="🔗 Đang ghép CoA + Delivery...")
        db = st.session_state.db
        use_ai = st.session_state.use_ai_matching
        batch_num = st.session_state.batch_count + 1
        existing_count = len(st.session_state.all_records)
        batch_records = []

        total_items = len(coa_records)
        for i, coa in enumerate(coa_records):
            # Progress cho từng item
            pct = 60 + int((i / max(total_items, 1)) * 35)
            step_label = "🧠 AI matching" if use_ai else "🔍 Fuzzy matching"
            progress.progress(pct, text=f"{step_label}: {coa.ten_nguyen_lieu[:40]}...")

            # Tìm delivery record tương ứng
            best_delivery = None
            best_score = 0.0
            for dlv in delivery_records:
                score = _keyword_overlap_score(coa.ten_nguyen_lieu, dlv.ten_nguyen_lieu)
                if score > best_score:
                    best_score = score
                    best_delivery = dlv

            # DB lookup (5-step with AI nếu bật)
            match = db.lookup(coa.ten_nguyen_lieu, use_ai=use_ai)

            # Auto-save alias nếu AI match thành công
            if match and match.confidence == "ai":
                try:
                    db.ensure_alias_table()
                    db.save_alias(
                        ocr_name=coa.ten_nguyen_lieu,
                        ma_hc=match.ma_hc,
                        ten_nl=match.ten_nguyen_lieu_db,
                        confidence="ai",
                    )
                except Exception:
                    pass

            batch_records.append({
                "stt": existing_count + i + 1,
                "batch": batch_num,
                "source_coa": coa_file.name,
                "source_delivery": delivery_file.name,
                "ten_nl_ocr": coa.ten_nguyen_lieu,
                "so_lo": coa.so_lo,
                "ngay_sx": coa.ngay_san_xuat,
                "hsd": coa.han_su_dung,
                "so_luong_kg": best_delivery.so_luong_kg if best_delivery else None,
                "so_pack": best_delivery.so_pack if best_delivery else None,
                "ten_cong_ty": coa.ten_cong_ty or (best_delivery.ten_cong_ty if best_delivery else None),
                "ti_trong": coa.ti_trong or (best_delivery.ti_trong if best_delivery else None),
                "ti_le": coa.ti_le or (best_delivery.ti_le if best_delivery else None),
                "trong_luong_rieng": coa.trong_luong_rieng or (best_delivery.trong_luong_rieng if best_delivery else None),
                "ma_hc": match.ma_hc if match else "",
                "ten_ke_toan": match.ten_ke_toan if match else "",
                "match_confidence": match.confidence if match else "none",
                "match_score": match.score if match else 0.0,
                "matched": match is not None,
            })

        # Tích lũy vào all_records
        st.session_state.all_records.extend(batch_records)
        st.session_state.batch_count = batch_num
        st.session_state.current_batch = batch_records

        progress.progress(100, text=f"✅ Batch #{batch_num} hoàn tất! ({len(batch_records)} NL)")
        st.balloons()

    except Exception as e:
        st.error(f"❌ Lỗi xử lý: {e}")
        import traceback
        with st.expander("Chi tiết lỗi"):
            st.code(traceback.format_exc())


# ══════════════════════════════════════════════════════════
# STEP 3: Preview & Edit (tất cả records tích lũy)
# ══════════════════════════════════════════════════════════
if st.session_state.all_records:
    st.divider()
    st.header("📊 Bước 3: Xem trước & Chỉnh sửa (tổng hợp)")

    all_recs = st.session_state.all_records

    # ── Metrics ──
    total = len(all_recs)
    matched = sum(1 for m in all_recs if m["matched"])
    unmatched = total - matched
    ai_matched = sum(1 for m in all_recs if m.get("match_confidence") == "ai")

    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
    col_m1.metric("Tổng NL", total)
    col_m2.metric("Đã match", matched,
                  delta=f"{matched/total*100:.0f}%" if total > 0 else "0%")
    col_m3.metric("AI match", ai_matched,
                  delta="🧠" if ai_matched > 0 else "—")
    col_m4.metric("Chưa match", unmatched,
                  delta=f"-{unmatched}" if unmatched > 0 else "0",
                  delta_color="inverse")

    expiring = 0
    for m in all_recs:
        if m["hsd"]:
            days = (m["hsd"] - datetime.now()).days
            if days < EXPIRY_WARNING_DAYS:
                expiring += 1
    col_m5.metric("HSD cảnh báo", expiring, delta="⚠️" if expiring > 0 else "✅")

    # ── Batch filter ──
    batch_numbers = sorted(set(r["batch"] for r in all_recs))
    if len(batch_numbers) > 1:
        filter_options = ["Tất cả"] + [f"Batch #{b}" for b in batch_numbers]
        selected_filter = st.selectbox("🔍 Lọc theo batch:", filter_options)
        if selected_filter != "Tất cả":
            batch_num = int(selected_filter.split("#")[1])
            display_recs = [r for r in all_recs if r["batch"] == batch_num]
        else:
            display_recs = all_recs
    else:
        display_recs = all_recs

    # ── DataFrame ──
    st.subheader("📝 Dữ liệu trích xuất")

    df_data = []
    for m in display_recs:
        hsd_remaining = None
        if m["hsd"]:
            hsd_remaining = (m["hsd"] - datetime.now()).days

        # Confidence badge
        conf = m["match_confidence"]
        conf_display = {
            "exact": "✅ Exact",
            "normalized": "✅ Normalized",
            "alias": "🔄 Alias",
            "fuzzy": "🟡 Fuzzy",
            "ai": "🧠 AI",
            "manual": "👤 Manual",
            "none": "❌ None",
        }.get(conf, conf)

        df_data.append({
            "STT": m["stt"],
            "Batch": f"#{m['batch']}",
            "Tên NL (OCR)": m["ten_nl_ocr"],
            "Mã HC": m["ma_hc"],
            "Tên NL (kế toán)": m["ten_ke_toan"],
            "Số lô": m["so_lo"],
            "Số lượng (kg)": m["so_luong_kg"],
            "Số pack": m["so_pack"],
            "Ngày SX": m["ngay_sx"].strftime("%d/%m/%Y") if m["ngay_sx"] else "",
            "HSD": m["hsd"].strftime("%d/%m/%Y") if m["hsd"] else "",
            "TenCongTy": m.get("ten_cong_ty") or "",
            "Titrong": m.get("ti_trong") or "",
            "Tile": m.get("ti_le") or "",
            "Trongluongrieng": m.get("trong_luong_rieng") or "",
            "HSD còn lại": f"{hsd_remaining} ngày" if hsd_remaining is not None else "",
            "Match": conf_display,
            "Score": f"{m['match_score']:.0%}" if m["match_score"] else "",
        })

    df = pd.DataFrame(df_data)

    def highlight_rows(row):
        match_val = row["Match"]
        if "None" in match_val:
            return ["background-color: #ffebee"] * len(row)
        elif "Fuzzy" in match_val:
            return ["background-color: #fff3e0"] * len(row)
        elif "AI" in match_val:
            return ["background-color: #f3e5f5"] * len(row)
        return [""] * len(row)

    styled_df = df.style.apply(highlight_rows, axis=1)
    st.dataframe(styled_df, use_container_width=True, height=450)

    # ── Source summary ──
    if len(batch_numbers) > 1:
        with st.expander("📂 Nguồn tài liệu"):
            source_data = []
            for b in batch_numbers:
                b_recs = [r for r in all_recs if r["batch"] == b]
                if b_recs:
                    source_data.append({
                        "Batch": f"#{b}",
                        "CoA": b_recs[0].get("source_coa", "—"),
                        "Delivery": b_recs[0].get("source_delivery", "—"),
                        "Số NL": len(b_recs),
                        "Matched": sum(1 for r in b_recs if r["matched"]),
                    })
            st.dataframe(pd.DataFrame(source_data), use_container_width=True)

    # ── Xử lý NL chưa match ──
    unmatched_items = [m for m in all_recs if not m["matched"]]

    if unmatched_items:
        st.subheader(f"⚠️ {len(unmatched_items)} nguyên liệu chưa match — Chọn thủ công")

        all_materials = st.session_state.db.get_all_materials()
        material_options = {
            f"{mat['ma_hc']} — {mat['ten_nguyen_lieu']}": mat
            for mat in all_materials
        }
        option_list = ["-- Chọn nguyên liệu --"] + sorted(material_options.keys())

        for item in unmatched_items:
            with st.expander(
                f"🔍 [{item.get('source_coa', '')}] {item['ten_nl_ocr']}",
                expanded=len(unmatched_items) <= 5,
            ):
                selected = st.selectbox(
                    f"Chọn NL cho: **{item['ten_nl_ocr']}**",
                    options=option_list,
                    key=f"manual_{item['stt']}_{item['batch']}",
                )

                if selected != "-- Chọn nguyên liệu --":
                    mat = material_options[selected]
                    item["ma_hc"] = mat["ma_hc"]
                    item["ten_ke_toan"] = mat["ten_ke_toan"]
                    item["matched"] = True
                    item["match_confidence"] = "manual"
                    item["match_score"] = 1.0

                    try:
                        st.session_state.db.ensure_alias_table()
                        st.session_state.db.save_alias(
                            ocr_name=item["ten_nl_ocr"],
                            ma_hc=mat["ma_hc"],
                            ten_nl=mat["ten_nguyen_lieu"],
                            confidence="manual",
                        )
                        st.success(f"💾 Alias lưu: {item['ten_nl_ocr']} → {mat['ma_hc']}")
                    except Exception as e:
                        st.warning(f"⚠️ Không thể lưu alias: {e}")

    # ══════════════════════════════════════════════════════
    # STEP 4: Generate Excel (tổng hợp tất cả batches)
    # ══════════════════════════════════════════════════════
    st.divider()
    st.header("📥 Bước 4: Xuất Excel tổng hợp")

    st.info(f"📊 File Excel sẽ chứa **{len(all_recs)} dòng** "
            f"từ **{st.session_state.batch_count} batch** tài liệu.")

    if st.button("📊 Tạo file Excel tổng hợp", use_container_width=True, type="primary"):
        # Re-number STT
        output_records = []
        for idx, m in enumerate(all_recs, start=1):
            record = OutputRecord(
                stt=idx,
                ngay_nhap=datetime.now(),
                ma_hc=m["ma_hc"],
                ten_nl=m["ten_nl_ocr"],
                ten_ke_toan=m["ten_ke_toan"],
                so_lo=m["so_lo"],
                so_luong_kg=m["so_luong_kg"],
                so_pack=m["so_pack"],
                ngay_sx=m["ngay_sx"],
                hsd=m["hsd"],
                ten_cong_ty=m.get("ten_cong_ty"),
                ti_trong=m.get("ti_trong"),
                ti_le=m.get("ti_le"),
                trong_luong_rieng=m.get("trong_luong_rieng"),
            )
            output_records.append(record)

        output_dir = os.path.join(ROOT_DIR, "outputs")
        xlsx_path = generate_xlsx(output_records, output_dir)
        st.session_state.xlsx_path = xlsx_path
        st.success(f"✅ File đã tạo: `{xlsx_path}` ({len(output_records)} dòng)")

    if st.session_state.xlsx_path and os.path.exists(st.session_state.xlsx_path):
        with open(st.session_state.xlsx_path, "rb") as f:
            st.download_button(
                label=f"⬇️ Tải Excel ({len(all_recs)} NL, {st.session_state.batch_count} batch)",
                data=f.read(),
                file_name=os.path.basename(st.session_state.xlsx_path),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
