# 📦 Material OCR — Hệ thống Nhập liệu Nguyên liệu Tự động

> Upload CoA + Biên bản giao hàng (PDF) → AI OCR trích xuất → Đối chiếu DB nguyên liệu → Xuất Excel tổng hợp

## ✨ Tính năng

- 🔍 **AI OCR**: Sử dụng Gemini 3.1 Flash Lite để đọc PDF trực tiếp (multimodal)
- 🧠 **5-step Smart Matching**: Exact → Normalized → Alias → Fuzzy → AI semantic matching
- 📊 **Multi-batch Processing**: Upload nhiều lần, tích lũy dữ liệu
- 📥 **Excel Export**: Xuất file `.xlsx` với conditional formatting (HSD < 90 ngày → đỏ)
- 💾 **Auto-learn Aliases**: Tự học tên nguyên liệu mới từ OCR → DB mapping
- 🐳 **Docker-based**: PostgreSQL chạy trong Docker, zero-config

## 📋 Yêu cầu hệ thống

- **OS**: Windows 10/11 (64-bit)
- **Python**: 3.10+
- **Docker Desktop**: [Tải tại đây](https://www.docker.com/products/docker-desktop)
- **Google Cloud**: Vertex AI credentials (Gemini 3.1 Flash Lite)

## 🚀 Cài đặt nhanh (1-click)

### Cách 1: Dùng file `.exe` (Khuyến nghị)

1. Tải file `MaterialOCR_Setup.exe` từ [Releases](../../releases)
2. Đặt vào thư mục project
3. Double-click để chạy → setup tự động

### Cách 2: Chạy script Python

```bash
python setup_project.py
```

### Cách 3: Cài đặt thủ công

```bash
# 1. Clone repo
git clone https://github.com/your-username/material-ocr.git
cd material-ocr

# 2. Khởi động PostgreSQL
docker-compose up -d

# 3. Tạo virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Linux/Mac

# 4. Cài đặt dependencies
pip install -r requirements.txt

# 5. Cấu hình
copy .env.example .env
# Chỉnh sửa .env với thông tin của bạn

# 6. Import dữ liệu vào DB
python init_db.py --file data/your_materials.csv

# 7. Chạy ứng dụng
streamlit run app.py
```

## 📂 Cấu trúc dự án

```
material-ocr/
├── app.py                  # 🖥️ Streamlit UI (entry point)
├── config.py               # ⚙️ Centralized configuration
├── models.py               # 📝 Data contracts (dataclasses)
├── init_db.py              # 🏗️ Database initialization (CSV/XLSX → DB)
├── setup_project.py        # 🚀 Auto setup script (→ .exe)
├── build_exe.bat           # 🔨 Build .exe script
├── docker-compose.yml      # 🐳 PostgreSQL container
├── requirements.txt        # 📦 Python dependencies
├── .env.example            # 🔑 Environment template
├── .gitignore              # 🚫 Git ignore rules
├── modules/
│   ├── __init__.py
│   ├── ocr_extractor.py    # 🔍 Gemini OCR + extraction
│   ├── db_connector.py     # 🗄️ DB lookup + 5-step matching
│   └── excel_generator.py  # 📊 Excel export with formatting
├── data/
│   └── sample_materials.csv # 📄 Sample data template
└── outputs/                 # 📥 Generated Excel files
```

## 📄 Định dạng file dữ liệu

### File CSV/XLSX yêu cầu các cột sau:

| Cột | Bắt buộc | Mô tả | Ví dụ |
|-----|----------|-------|-------|
| `ma_hc` | ✅ | Mã hóa chất | HC001 |
| `ten_nguyen_lieu` | ✅ | Tên nguyên liệu | Sodium Laureth Sulfate |
| `ten_ke_toan` | ✅ | Tên kế toán | NL SLES |
| `chuc_nang` | ❌ | Chức năng | Chất hoạt động bề mặt |

### Ví dụ CSV:

```csv
ma_hc,ten_nguyen_lieu,chuc_nang,ten_ke_toan
HC001,Sodium Laureth Sulfate,Chất hoạt động bề mặt,NL SLES
HC002,Cocamidopropyl Betaine,Chất hoạt động bề mặt,NL Cocamidopropyl Betaine
HC003,Glycerin,Chất giữ ẩm,NL Glycerin
```

Xem file mẫu: [`data/sample_materials.csv`](data/sample_materials.csv)

## 🏗️ Import dữ liệu vào Database

```bash
# Interactive mode (hỏi chọn file)
python init_db.py

# Import trực tiếp từ CSV
python init_db.py --file data/materials.csv

# Import từ XLSX (chọn sheet cụ thể)
python init_db.py --file data/materials.xlsx --sheet "Sheet1"

# Chỉ tạo schema (không import data)
python init_db.py --schema-only

# Reset DB (⚠️ xóa toàn bộ dữ liệu)
python init_db.py --reset
```

## ⚙️ Cấu hình (.env)

```ini
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pif_db
DB_USER=admin
DB_PASSWORD=adminpassword

# Vertex AI (bắt buộc cho OCR + AI matching)
VERTEX_PROJECT=your-project-id
VERTEX_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json
```

## 🔨 Build file .exe

Để tạo file `.exe` cho người dùng khác:

```bash
# Cách 1: Dùng build script
build_exe.bat

# Cách 2: Thủ công
pip install pyinstaller
pyinstaller --onefile --name MaterialOCR_Setup --console setup_project.py
```

File `.exe` sẽ nằm trong `dist/MaterialOCR_Setup.exe`

## 🔄 Pipeline xử lý

```
PDF (CoA) ─────────────┐
                       ├──→ Gemini OCR ──→ Structured JSON ──→ DB Lookup ──→ Excel
PDF (Biên bản GH) ─────┘                                        ↓
                                                          5-step Matching:
                                                          1. Exact match
                                                          2. Normalized
                                                          3. Alias table
                                                          4. Keyword fuzzy
                                                          5. AI semantic (Gemini)
```

## 📝 Lưu ý

- **Credentials**: Không commit file `.env` và `credentials.json` lên Git
- **Data**: Đặt file dữ liệu nguyên liệu vào thư mục `data/`
- **Docker**: Đảm bảo Docker Desktop đang chạy trước khi sử dụng
- **Port**: Mặc định PostgreSQL chạy trên port `5432` (có thể đổi trong `.env`)

## 📜 License

MIT License
