"""
setup_project.py — Smart Launcher (compilable to .exe)
Phát hiện trạng thái → tự chọn mode:
  - Lần đầu: Full setup (Docker → venv → DB → Launch)
  - Lần sau: Quick launch (Docker → Launch)

Build .exe:
    pip install pyinstaller
    pyinstaller --onefile --name MaterialOCR_Setup --console setup_project.py
"""
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ── Constants ─────────────────────────────────────────────
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(sys.argv[0])))
VENV_DIR = SCRIPT_DIR / "venv"
PYTHON_CMD = str(VENV_DIR / "Scripts" / "python.exe")
PIP_CMD = str(VENV_DIR / "Scripts" / "pip.exe")
STREAMLIT_CMD = str(VENV_DIR / "Scripts" / "streamlit.exe")
REQUIREMENTS_FILE = SCRIPT_DIR / "requirements.txt"
ENV_FILE = SCRIPT_DIR / ".env"
ENV_EXAMPLE = SCRIPT_DIR / ".env.example"
DATA_DIR = SCRIPT_DIR / "data"
SETUP_MARKER = SCRIPT_DIR / ".setup_done"

DOCKER_DOWNLOAD_URL = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/"


# ── UI Helpers ────────────────────────────────────────────
class C:
    """ANSI colors."""
    R = "\033[0m"; B = "\033[1m"
    RED = "\033[91m"; GRN = "\033[92m"; YEL = "\033[93m"
    BLU = "\033[94m"; CYN = "\033[96m"; MAG = "\033[95m"


def enable_colors():
    if platform.system() == "Windows":
        try:
            ctypes.windll.kernel32.SetConsoleMode(
                ctypes.windll.kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def ok(msg):    print(f"  {C.GRN}✅ {msg}{C.R}")
def warn(msg): print(f"  {C.YEL}⚠️  {msg}{C.R}")
def err(msg):  print(f"  {C.RED}❌ {msg}{C.R}")
def inf(msg):  print(f"  {C.CYN}ℹ️  {msg}{C.R}")


def step(n, total, title):
    print(f"\n{C.BLU}{'─'*60}\n  [{n}/{total}] {title}\n{'─'*60}{C.R}")


def ask(prompt, default=True):
    s = " [Y/n]: " if default else " [y/N]: "
    a = input(f"  {C.YEL}❓ {prompt}{s}{C.R}").strip().lower()
    return default if not a else a in ("y", "yes", "có", "co")


def banner(mode):
    label = "🚀 QUICK LAUNCH" if mode == "launch" else "📦 FIRST-TIME SETUP"
    print(f"""
{C.CYN}╔══════════════════════════════════════════════════════════╗
║  📦  MATERIAL OCR — {label:<36} ║
║  Hệ thống Nhập liệu Nguyên liệu Tự động               ║
╚══════════════════════════════════════════════════════════╝{C.R}
""")


# ── Detection ─────────────────────────────────────────────
def is_setup_done() -> bool:
    """Kiểm tra project đã được setup chưa."""
    return (
        SETUP_MARKER.exists()
        and VENV_DIR.exists()
        and Path(STREAMLIT_CMD).exists()
        and ENV_FILE.exists()
    )


# ── Docker ────────────────────────────────────────────────
def check_docker() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def get_compose_cmd() -> list[str]:
    try:
        r = subprocess.run(["docker", "compose", "version"],
                           capture_output=True, timeout=10)
        if r.returncode == 0:
            return ["docker", "compose"]
    except Exception:
        pass
    return ["docker-compose"]


def ensure_docker():
    """Đảm bảo Docker đang chạy."""
    if check_docker():
        ok("Docker Desktop đang chạy")
        return
    err("Docker Desktop chưa chạy!")
    print(f"\n  Hãy cài đặt/mở Docker Desktop trước.")
    print(f"  Tải tại: {DOCKER_DOWNLOAD_URL}\n")
    if ask("Mở trang tải Docker Desktop?"):
        webbrowser.open(DOCKER_DOWNLOAD_URL)
    input(f"\n  {C.CYN}Sau khi Docker đã chạy, nhấn Enter...{C.R}")
    if not check_docker():
        err("Docker vẫn chưa sẵn sàng. Hãy thử lại.")
        sys.exit(1)
    ok("Docker Desktop đã sẵn sàng!")


def ensure_postgres():
    """Đảm bảo PostgreSQL container đang chạy."""
    compose_file = SCRIPT_DIR / "docker-compose.yml"
    if not compose_file.exists():
        err(f"Không tìm thấy docker-compose.yml")
        sys.exit(1)

    # Check running
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", "name=material_ocr_db", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=10)
        if r.stdout.strip():
            ok(f"PostgreSQL: {r.stdout.strip()}")
            return
    except Exception:
        pass

    # Start
    inf("Đang khởi động PostgreSQL...")
    cmd = get_compose_cmd()
    r = subprocess.run([*cmd, "-f", str(compose_file), "up", "-d"],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(SCRIPT_DIR))
    if r.returncode != 0:
        err(f"Lỗi: {r.stderr}")
        sys.exit(1)

    # Wait ready
    for _ in range(30):
        try:
            r = subprocess.run(
                ["docker", "exec", "material_ocr_db",
                 "pg_isready", "-U", "admin", "-d", "pif_db"],
                capture_output=True, timeout=5)
            if r.returncode == 0:
                ok("PostgreSQL sẵn sàng")
                return
        except Exception:
            pass
        time.sleep(2)
        print(".", end="", flush=True)
    print()
    warn("PostgreSQL có thể chưa sẵn sàng hoàn toàn.")


# ── Python / Venv ─────────────────────────────────────────
def find_python() -> str | None:
    for cmd in ["python", "python3", "py"]:
        p = shutil.which(cmd)
        if p:
            try:
                r = subprocess.run([p, "--version"], capture_output=True, timeout=10)
                if r.returncode == 0:
                    return p
            except Exception:
                continue
    return None


def ensure_venv():
    """Tạo venv nếu chưa có."""
    if VENV_DIR.exists() and Path(PYTHON_CMD).exists():
        ok(f"Venv đã tồn tại")
        return

    py = find_python()
    if not py:
        err("Python chưa được cài đặt!")
        inf(f"Tải Python: {PYTHON_DOWNLOAD_URL}")
        if ask("Mở trang tải Python?"):
            webbrowser.open(PYTHON_DOWNLOAD_URL)
        sys.exit(1)

    inf(f"Đang tạo venv bằng {py}...")
    r = subprocess.run([py, "-m", "venv", str(VENV_DIR)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        err(f"Lỗi tạo venv: {r.stderr}")
        sys.exit(1)
    ok("Venv đã tạo")


def ensure_deps():
    """Cài đặt dependencies nếu cần."""
    # Quick check: streamlit có chưa
    if Path(STREAMLIT_CMD).exists():
        ok("Dependencies đã cài đặt")
        return

    if not REQUIREMENTS_FILE.exists():
        err("Không tìm thấy requirements.txt")
        sys.exit(1)

    subprocess.run([PYTHON_CMD, "-m", "pip", "install", "--upgrade", "pip"],
                   capture_output=True, timeout=120)

    inf("Đang cài đặt dependencies (vài phút)...")
    r = subprocess.run([PIP_CMD, "install", "-r", str(REQUIREMENTS_FILE)],
                       timeout=600, cwd=str(SCRIPT_DIR))
    if r.returncode != 0:
        err("Lỗi cài đặt dependencies!")
        sys.exit(1)
    ok("Dependencies đã cài đặt")


# ── .env ──────────────────────────────────────────────────
def ensure_env():
    """Tạo .env nếu chưa có."""
    if ENV_FILE.exists():
        ok(".env đã tồn tại")
        return

    if ENV_EXAMPLE.exists():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
    else:
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write("DB_HOST=localhost\nDB_PORT=5432\nDB_NAME=pif_db\n"
                    "DB_USER=admin\nDB_PASSWORD=adminpassword\n"
                    "VERTEX_PROJECT=your-project-id\nVERTEX_LOCATION=global\n"
                    "GOOGLE_APPLICATION_CREDENTIALS=path/to/credentials.json\n")
    ok(".env đã tạo")
    warn("Hãy chỉnh sửa .env với Vertex AI credentials của bạn!")


# ── DB Import ─────────────────────────────────────────────
def setup_database():
    """Import data từ CSV/XLSX vào DB."""
    files = []
    if DATA_DIR.exists():
        files = [f for f in DATA_DIR.iterdir()
                 if f.suffix.lower() in (".csv", ".xlsx")]

    if not files:
        warn("Không tìm thấy file dữ liệu trong data/")
        inf("Tạo schema trống...")
        subprocess.run([PYTHON_CMD, str(SCRIPT_DIR / "init_db.py"), "--schema-only"],
                       cwd=str(SCRIPT_DIR), timeout=60)
        inf("Import sau: python init_db.py --file <file.csv>")
        return

    print(f"\n  📂 File dữ liệu có sẵn:")
    for i, f in enumerate(files, 1):
        print(f"     {i}. {f.name} ({f.stat().st_size/1024:.1f} KB)")
    print(f"     {len(files)+1}. Nhập đường dẫn khác")
    print(f"     {len(files)+2}. Bỏ qua (chỉ tạo schema)")

    choice = input(f"\n  🔹 Chọn (1-{len(files)+2}): ").strip()

    try:
        idx = int(choice) - 1
        if idx == len(files) + 1:
            subprocess.run([PYTHON_CMD, str(SCRIPT_DIR/"init_db.py"), "--schema-only"],
                           cwd=str(SCRIPT_DIR), timeout=60)
            return
        elif idx == len(files):
            fp = input("  📁 Đường dẫn file: ").strip().strip('"')
        elif 0 <= idx < len(files):
            fp = str(files[idx])
        else:
            fp = str(files[0])
    except ValueError:
        fp = str(files[0])

    if fp and Path(fp).exists():
        subprocess.run([PYTHON_CMD, str(SCRIPT_DIR/"init_db.py"), "--file", fp],
                       cwd=str(SCRIPT_DIR), timeout=120)
    else:
        warn("File không tồn tại. Tạo schema trống...")
        subprocess.run([PYTHON_CMD, str(SCRIPT_DIR/"init_db.py"), "--schema-only"],
                       cwd=str(SCRIPT_DIR), timeout=60)


# ── Launch ────────────────────────────────────────────────
def launch_streamlit():
    """Chạy Streamlit app."""
    app = SCRIPT_DIR / "app.py"
    if not app.exists():
        err("Không tìm thấy app.py!")
        return
    if not Path(STREAMLIT_CMD).exists():
        err("Streamlit chưa cài đặt!")
        return

    print(f"""
{C.GRN}{'═'*60}
  🎉 SẴN SÀNG! Ứng dụng sẽ mở tại:
     👉  http://localhost:8501
{'═'*60}{C.R}
  {C.YEL}Nhấn Ctrl+C trong cửa sổ này để dừng server.{C.R}
""")

    # Auto-open browser after 3 seconds
    import threading
    def open_browser():
        time.sleep(3)
        webbrowser.open("http://localhost:8501")
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        subprocess.run(
            [STREAMLIT_CMD, "run", str(app),
             "--server.headless", "true",
             "--browser.gatherUsageStats", "false"],
            cwd=str(SCRIPT_DIR))
    except KeyboardInterrupt:
        print(f"\n{C.YEL}  ⏹️  Server đã dừng.{C.R}")


# ── Main Modes ────────────────────────────────────────────
def run_first_time_setup():
    """Full setup cho lần đầu."""
    banner("setup")
    total = 7

    step(1, total, "🐳 KIỂM TRA DOCKER")
    ensure_docker()

    step(2, total, "🐘 KHỞI ĐỘNG POSTGRESQL")
    ensure_postgres()

    step(3, total, "🐍 TẠO VIRTUAL ENVIRONMENT")
    ensure_venv()

    step(4, total, "📦 CÀI ĐẶT DEPENDENCIES")
    ensure_deps()

    step(5, total, "⚙️ CẤU HÌNH .ENV")
    ensure_env()

    step(6, total, "📥 IMPORT DỮ LIỆU VÀO DATABASE")
    setup_database()

    # Mark setup done
    SETUP_MARKER.write_text("ok", encoding="utf-8")
    ok("Setup đã hoàn tất! File .setup_done đã tạo.")

    step(7, total, "🚀 KHỞI CHẠY ỨNG DỤNG")
    launch_streamlit()


def run_quick_launch():
    """Quick launch khi đã setup rồi."""
    banner("launch")

    step(1, 3, "🐳 KIỂM TRA DOCKER")
    ensure_docker()

    step(2, 3, "🐘 KHỞI ĐỘNG POSTGRESQL")
    ensure_postgres()

    step(3, 3, "🚀 KHỞI CHẠY ỨNG DỤNG")
    launch_streamlit()


def run_menu():
    """Menu chính khi đã setup."""
    banner("launch")
    print(f"""  Chọn chế độ:
     {C.GRN}1.{C.R} 🚀 Chạy ứng dụng (Quick Launch)
     {C.CYN}2.{C.R} 📥 Import thêm dữ liệu vào DB
     {C.YEL}3.{C.R} 🔄 Setup lại từ đầu (re-install)
     {C.RED}4.{C.R} 🚪 Thoát
""")
    choice = input(f"  🔹 Chọn (1-4) [1]: ").strip() or "1"

    if choice == "1":
        run_quick_launch()
    elif choice == "2":
        ensure_docker()
        ensure_postgres()
        setup_database()
        if ask("Chạy ứng dụng ngay?"):
            launch_streamlit()
    elif choice == "3":
        SETUP_MARKER.unlink(missing_ok=True)
        run_first_time_setup()
    else:
        print(f"\n  {C.CYN}👋 Tạm biệt!{C.R}\n")


# ── Entry Point ──────────────────────────────────────────
def main():
    enable_colors()

    if is_setup_done():
        # Đã setup → hiện menu
        run_menu()
    else:
        # Chưa setup → full setup
        run_first_time_setup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{C.YEL}  ⏹️  Đã dừng.{C.R}")
    except Exception as e:
        print(f"\n{C.RED}  ❌ Lỗi: {e}{C.R}")
        import traceback
        traceback.print_exc()
        input("\nNhấn Enter để thoát...")
