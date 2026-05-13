"""
setup_project.py — One-click Project Setup (compilable to .exe)
Tự động hóa toàn bộ quá trình cài đặt:
  1. Kiểm tra/tải Docker Desktop
  2. Khởi động PostgreSQL container
  3. Tạo Python virtual environment
  4. Cài đặt dependencies
  5. Import dữ liệu từ CSV/XLSX vào DB
  6. Chạy ứng dụng Streamlit

Build .exe:
    pip install pyinstaller
    pyinstaller --onefile --name MaterialOCR_Setup --icon=assets/icon.ico setup_project.py

Usage:
    python setup_project.py          # Full setup
    setup_project.exe                # Sau khi build .exe
"""
import ctypes
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
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

DOCKER_DOWNLOAD_URL = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
PYTHON_DOWNLOAD_URL = "https://www.python.org/downloads/"

# ── UI Helpers ────────────────────────────────────────────
class Colors:
    """ANSI color codes for console output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"


def enable_ansi_colors():
    """Enable ANSI color support on Windows 10+."""
    if platform.system() == "Windows":
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def banner():
    """Hiển thị banner."""
    print(f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   📦  MATERIAL OCR — AUTO SETUP                         ║
║   Hệ thống Nhập liệu Nguyên liệu Tự động               ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝{Colors.RESET}
""")


def step_header(step_num: int, total: int, title: str):
    """Hiển thị header cho mỗi bước."""
    print(f"\n{Colors.BLUE}{'─' * 60}")
    print(f"  [{step_num}/{total}] {title}")
    print(f"{'─' * 60}{Colors.RESET}")


def success(msg: str):
    print(f"  {Colors.GREEN}✅ {msg}{Colors.RESET}")


def warning(msg: str):
    print(f"  {Colors.YELLOW}⚠️  {msg}{Colors.RESET}")


def error(msg: str):
    print(f"  {Colors.RED}❌ {msg}{Colors.RESET}")


def info(msg: str):
    print(f"  {Colors.CYAN}ℹ️  {msg}{Colors.RESET}")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Hỏi Yes/No."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    answer = input(f"  {Colors.YELLOW}❓ {prompt}{suffix}{Colors.RESET}").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes", "có", "co")


def press_enter():
    input(f"\n  {Colors.CYAN}⏎  Nhấn Enter để tiếp tục...{Colors.RESET}")


# ── Step 1: Check Docker ─────────────────────────────────
def check_docker() -> bool:
    """Kiểm tra Docker Desktop đã cài đặt và đang chạy."""
    # Check if docker command exists
    docker_path = shutil.which("docker")
    if not docker_path:
        return False

    # Check if Docker daemon is running
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_docker_compose() -> bool:
    """Kiểm tra docker-compose có sẵn."""
    # Try 'docker compose' (v2 - built-in)
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try 'docker-compose' (v1 - standalone)
    try:
        result = subprocess.run(
            ["docker-compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_compose_command() -> list[str]:
    """Trả về command phù hợp cho docker compose."""
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return ["docker", "compose"]
    except Exception:
        pass
    return ["docker-compose"]


def install_docker():
    """Hướng dẫn/tải Docker Desktop."""
    print(f"""
  {Colors.YELLOW}Docker Desktop chưa được cài đặt hoặc chưa chạy.{Colors.RESET}

  Bạn có 2 lựa chọn:
    1. Tải Docker Desktop tự động (mở trình duyệt)
    2. Tự cài đặt từ https://www.docker.com/products/docker-desktop

  {Colors.CYAN}Sau khi cài đặt:{Colors.RESET}
    • Mở Docker Desktop
    • Chờ Docker khởi động hoàn tất (icon ở taskbar chuyển xanh)
    • Chạy lại setup này
""")

    if ask_yes_no("Mở trang tải Docker Desktop?"):
        webbrowser.open(DOCKER_DOWNLOAD_URL)
        info("Đã mở trình duyệt để tải Docker Desktop.")
        info("Sau khi cài đặt và khởi động Docker, chạy lại setup này.")
        press_enter()
        sys.exit(0)


def setup_docker():
    """Step 1: Kiểm tra và cấu hình Docker."""
    if check_docker():
        success("Docker Desktop đang chạy")

        # Show Docker version
        try:
            result = subprocess.run(
                ["docker", "version", "--format", "{{.Server.Version}}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                info(f"Docker Engine: v{result.stdout.strip()}")
        except Exception:
            pass

        if check_docker_compose():
            success("Docker Compose sẵn sàng")
        else:
            error("Docker Compose không tìm thấy!")
            info("Cập nhật Docker Desktop lên phiên bản mới nhất.")
            sys.exit(1)
    else:
        install_docker()
        # Re-check after potential install
        if not check_docker():
            error("Docker vẫn chưa sẵn sàng. Hãy cài đặt và khởi động Docker Desktop trước.")
            sys.exit(1)


# ── Step 2: Start PostgreSQL ─────────────────────────────
def start_postgres():
    """Step 2: Khởi động PostgreSQL container."""
    compose_file = SCRIPT_DIR / "docker-compose.yml"
    if not compose_file.exists():
        error(f"Không tìm thấy docker-compose.yml tại: {compose_file}")
        sys.exit(1)

    compose_cmd = get_compose_command()

    # Check if container already running
    try:
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=material_ocr_db", "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            success(f"PostgreSQL container đã chạy: {result.stdout.strip()}")
            return
    except Exception:
        pass

    # Start container
    info("Đang khởi động PostgreSQL container...")
    try:
        result = subprocess.run(
            [*compose_cmd, "-f", str(compose_file), "up", "-d"],
            capture_output=True, text=True, timeout=120,
            cwd=str(SCRIPT_DIR),
        )
        if result.returncode == 0:
            success("PostgreSQL container đã khởi động")
        else:
            error(f"Lỗi khởi động container:\n{result.stderr}")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        error("Timeout khi khởi động container. Kiểm tra Docker Desktop.")
        sys.exit(1)

    # Wait for PostgreSQL to be ready
    info("Đang chờ PostgreSQL sẵn sàng...")
    for i in range(30):
        try:
            result = subprocess.run(
                ["docker", "exec", "material_ocr_db",
                 "pg_isready", "-U", "admin", "-d", "pif_db"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                success("PostgreSQL sẵn sàng nhận kết nối")
                return
        except Exception:
            pass
        time.sleep(2)
        print(".", end="", flush=True)

    print()
    warning("PostgreSQL có thể chưa sẵn sàng. Sẽ thử tiếp ở bước sau.")


# ── Step 3: Python venv ──────────────────────────────────
def check_python() -> str | None:
    """Tìm Python executable trên hệ thống."""
    # Check common names
    for cmd in ["python", "python3", "py"]:
        path = shutil.which(cmd)
        if path:
            try:
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    version = result.stdout.strip() or result.stderr.strip()
                    return path
            except Exception:
                continue
    return None


def setup_venv():
    """Step 3: Tạo virtual environment."""
    python_path = check_python()

    if not python_path:
        error("Python không tìm thấy trên hệ thống!")
        info(f"Tải Python từ: {PYTHON_DOWNLOAD_URL}")
        if ask_yes_no("Mở trang tải Python?"):
            webbrowser.open(PYTHON_DOWNLOAD_URL)
        sys.exit(1)

    # Show Python version
    try:
        result = subprocess.run(
            [python_path, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        info(f"Sử dụng: {result.stdout.strip()} ({python_path})")
    except Exception:
        pass

    # Check if venv already exists
    if VENV_DIR.exists() and Path(PYTHON_CMD).exists():
        success(f"Virtual environment đã tồn tại: {VENV_DIR}")
        if not ask_yes_no("Tạo lại venv mới?", default=False):
            return
        info("Đang xóa venv cũ...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    # Create venv
    info(f"Đang tạo virtual environment tại: {VENV_DIR}")
    try:
        result = subprocess.run(
            [python_path, "-m", "venv", str(VENV_DIR)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            success("Virtual environment đã tạo thành công")
        else:
            error(f"Lỗi tạo venv:\n{result.stderr}")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        error("Timeout khi tạo venv.")
        sys.exit(1)


# ── Step 4: Install dependencies ─────────────────────────
def install_dependencies():
    """Step 4: Cài đặt Python dependencies."""
    if not REQUIREMENTS_FILE.exists():
        error(f"Không tìm thấy {REQUIREMENTS_FILE}")
        sys.exit(1)

    # Upgrade pip first
    info("Đang cập nhật pip...")
    subprocess.run(
        [PYTHON_CMD, "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True, timeout=120,
    )

    # Install requirements
    info("Đang cài đặt dependencies (có thể mất vài phút)...")
    try:
        result = subprocess.run(
            [PIP_CMD, "install", "-r", str(REQUIREMENTS_FILE)],
            text=True, timeout=600,
            cwd=str(SCRIPT_DIR),
        )
        if result.returncode == 0:
            success("Tất cả dependencies đã cài đặt thành công")
        else:
            error("Có lỗi khi cài đặt dependencies.")
            info("Thử chạy thủ công: venv\\Scripts\\pip install -r requirements.txt")
            sys.exit(1)
    except subprocess.TimeoutExpired:
        error("Timeout khi cài đặt dependencies.")
        sys.exit(1)


# ── Step 5: Setup .env ───────────────────────────────────
def setup_env():
    """Step 5: Tạo file .env từ .env.example."""
    if ENV_FILE.exists():
        success(".env đã tồn tại")
        if not ask_yes_no("Ghi đè .env hiện tại?", default=False):
            return

    if ENV_EXAMPLE.exists():
        shutil.copy2(ENV_EXAMPLE, ENV_FILE)
        success(f".env đã tạo từ .env.example")
        warning("⚡ Hãy chỉnh sửa file .env với thông tin Vertex AI/Gemini của bạn!")
        info(f"   File: {ENV_FILE}")
    else:
        # Create default .env
        env_content = """# ── Database ──────────────────────────────────────────────
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pif_db
DB_USER=admin
DB_PASSWORD=adminpassword

# ── Vertex AI / Gemini ────────────────────────────────────
VERTEX_PROJECT=your-project-id
VERTEX_LOCATION=global
GOOGLE_APPLICATION_CREDENTIALS=path/to/your-credentials.json
"""
        with open(ENV_FILE, "w", encoding="utf-8") as f:
            f.write(env_content)
        success(".env đã tạo với giá trị mặc định")
        warning("⚡ Cần chỉnh sửa VERTEX_PROJECT và GOOGLE_APPLICATION_CREDENTIALS!")


# ── Step 6: Import data ──────────────────────────────────
def import_data():
    """Step 6: Import dữ liệu từ CSV/XLSX vào DB."""
    # Find available data files
    available_files = []
    if DATA_DIR.exists():
        for f in DATA_DIR.iterdir():
            if f.suffix.lower() in (".csv", ".xlsx"):
                available_files.append(f)

    if not available_files:
        warning("Không tìm thấy file dữ liệu trong thư mục data/")
        info("Bạn có thể import sau bằng lệnh:")
        info(f"  {PYTHON_CMD} init_db.py --file <path/to/file.csv>")
        # Still create schema
        info("Đang tạo schema DB...")
        subprocess.run(
            [PYTHON_CMD, str(SCRIPT_DIR / "init_db.py"), "--schema-only"],
            cwd=str(SCRIPT_DIR), timeout=60,
        )
        return

    print(f"\n  📂 File dữ liệu có sẵn:")
    for i, f in enumerate(available_files, 1):
        size_kb = f.stat().st_size / 1024
        print(f"     {i}. {f.name} ({size_kb:.1f} KB)")
    print(f"     {len(available_files) + 1}. Nhập đường dẫn khác")
    print(f"     {len(available_files) + 2}. Bỏ qua (chỉ tạo schema)")

    choice = input(f"\n  🔹 Chọn file (1-{len(available_files) + 2}): ").strip()

    try:
        idx = int(choice) - 1
        if idx == len(available_files) + 1:
            # Schema only
            info("Đang tạo schema DB...")
            subprocess.run(
                [PYTHON_CMD, str(SCRIPT_DIR / "init_db.py"), "--schema-only"],
                cwd=str(SCRIPT_DIR), timeout=60,
            )
            return
        elif idx == len(available_files):
            # Custom path
            filepath = input("  📁 Nhập đường dẫn file: ").strip().strip('"').strip("'")
        elif 0 <= idx < len(available_files):
            filepath = str(available_files[idx])
        else:
            filepath = str(available_files[0])
    except ValueError:
        filepath = str(available_files[0]) if available_files else ""

    if filepath and Path(filepath).exists():
        info(f"Đang import từ: {Path(filepath).name}")
        result = subprocess.run(
            [PYTHON_CMD, str(SCRIPT_DIR / "init_db.py"), "--file", filepath],
            cwd=str(SCRIPT_DIR), timeout=120,
        )
        if result.returncode == 0:
            success("Import dữ liệu hoàn tất!")
        else:
            warning("Import có lỗi. Kiểm tra lại file dữ liệu.")
    else:
        warning(f"File không tồn tại: {filepath}")
        info("Tạo schema trống...")
        subprocess.run(
            [PYTHON_CMD, str(SCRIPT_DIR / "init_db.py"), "--schema-only"],
            cwd=str(SCRIPT_DIR), timeout=60,
        )


# ── Step 7: Launch app ───────────────────────────────────
def launch_app():
    """Step 7: Chạy Streamlit app."""
    app_file = SCRIPT_DIR / "app.py"
    if not app_file.exists():
        error(f"Không tìm thấy {app_file}")
        return

    if not Path(STREAMLIT_CMD).exists():
        error("Streamlit chưa được cài đặt trong venv.")
        return

    print(f"""
{Colors.GREEN}{'═' * 60}
  🎉 SETUP HOÀN TẤT!
{'═' * 60}{Colors.RESET}

  {Colors.CYAN}Ứng dụng sẽ chạy tại: http://localhost:8501{Colors.RESET}
  {Colors.YELLOW}Nhấn Ctrl+C để dừng server.{Colors.RESET}
""")

    if ask_yes_no("Chạy ứng dụng ngay bây giờ?"):
        info("Đang khởi động Streamlit...")
        try:
            subprocess.run(
                [STREAMLIT_CMD, "run", str(app_file),
                 "--server.headless", "true",
                 "--browser.gatherUsageStats", "false"],
                cwd=str(SCRIPT_DIR),
            )
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}  ⏹️  Server đã dừng.{Colors.RESET}")
    else:
        print(f"""
  {Colors.CYAN}Để chạy ứng dụng sau, dùng lệnh:{Colors.RESET}
    cd {SCRIPT_DIR}
    venv\\Scripts\\activate
    streamlit run app.py
""")


# ── Main ──────────────────────────────────────────────────
def main():
    enable_ansi_colors()
    banner()

    total_steps = 7

    step_header(1, total_steps, "🐳 KIỂM TRA DOCKER")
    setup_docker()

    step_header(2, total_steps, "🐘 KHỞI ĐỘNG POSTGRESQL")
    start_postgres()

    step_header(3, total_steps, "🐍 TẠO VIRTUAL ENVIRONMENT")
    setup_venv()

    step_header(4, total_steps, "📦 CÀI ĐẶT DEPENDENCIES")
    install_dependencies()

    step_header(5, total_steps, "⚙️ CẤU HÌNH .ENV")
    setup_env()

    step_header(6, total_steps, "📥 IMPORT DỮ LIỆU VÀO DATABASE")
    import_data()

    step_header(7, total_steps, "🚀 CHẠY ỨNG DỤNG")
    launch_app()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}  ⏹️  Setup bị hủy bởi người dùng.{Colors.RESET}")
        sys.exit(0)
    except Exception as e:
        print(f"\n{Colors.RED}  ❌ Lỗi không mong đợi: {e}{Colors.RESET}")
        import traceback
        traceback.print_exc()
        input("\nNhấn Enter để thoát...")
        sys.exit(1)
