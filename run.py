"""
همراه — اجراکننده کامل
=====================================
این اسکریپت هم بک‌اند و هم فرانت‌اند را با هم راه‌اندازی می‌کند.

اجرا: python run.py
"""

import os
import sys
import subprocess
import time
import webbrowser
import threading
from pathlib import Path


# ============================================================
# تنظیمات
# ============================================================
ROOT = Path(__file__).parent.resolve()
BACKEND_FILE = ROOT / "backend.py"
FRONTEND_FILE = ROOT / "frontend.html"
BACKEND_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:8000/app"
DOCS_URL = "http://localhost:8000/docs"


# رنگ‌های ANSI برای زیبایی ترمینال
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ORANGE = "\033[38;5;208m"
    GREEN = "\033[38;5;82m"
    BLUE = "\033[38;5;39m"
    YELLOW = "\033[38;5;220m"
    RED = "\033[38;5;203m"
    PURPLE = "\033[38;5;141m"
    CYAN = "\033[38;5;51m"


BANNER = f"""{C.ORANGE}{C.BOLD}
   ╔══════════════════════════════════════════════════════════╗
   ║                                                          ║
   ║      🤝  ه م ر ا ه   —   H A M R A H                     ║
   ║                                                          ║
   ║      با هم، هر مسیر آسان‌تر است                          ║
   ║      Together, every path is easier                      ║
   ║                                                          ║
   ╚══════════════════════════════════════════════════════════╝
{C.RESET}"""


# ============================================================
# بررسی پیش‌نیازها
# ============================================================
def check_python_version():
    if sys.version_info < (3, 8):
        print(f"{C.RED}❌ پایتون ۳.۸ یا بالاتر موردنیاز است.{C.RESET}")
        print(f"   نسخه فعلی: {sys.version}")
        sys.exit(1)
    print(f"{C.GREEN}✓{C.RESET} Python {sys.version.split()[0]}")


def check_files():
    ok = True
    if not BACKEND_FILE.exists():
        print(f"{C.RED}❌ فایل backend.py پیدا نشد: {BACKEND_FILE}{C.RESET}")
        ok = False
    else:
        print(f"{C.GREEN}✓{C.RESET} backend.py")
    if not FRONTEND_FILE.exists():
        print(f"{C.RED}❌ فایل frontend.html پیدا نشد: {FRONTEND_FILE}{C.RESET}")
        ok = False
    else:
        print(f"{C.GREEN}✓{C.RESET} frontend.html")
    if not ok:
        print(f"\n{C.YELLOW}💡 فایل‌های backend.py و frontend.html باید کنار run.py باشند.{C.RESET}")
        sys.exit(1)


def ensure_packages():
    """نصب پکیج‌های موردنیاز اگر نبودند."""
    required = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn[standard]",
        "pydantic": "pydantic[email]",
    }
    missing = []
    for mod, pip_name in required.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)

    if missing:
        print(f"\n{C.YELLOW}📦 نصب پکیج‌های موردنیاز: {', '.join(missing)}{C.RESET}")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])
            print(f"{C.GREEN}✓ پکیج‌ها نصب شدند.{C.RESET}\n")
        except subprocess.CalledProcessError:
            print(f"{C.RED}❌ خطا در نصب پکیج‌ها. لطفاً دستی اجرا کنید:{C.RESET}")
            print(f"   pip install {' '.join(missing)}")
            sys.exit(1)
    else:
        print(f"{C.GREEN}✓{C.RESET} همه پکیج‌ها موجودند")


# ============================================================
# بک‌اند: ادغام فرانت با FastAPI
# ============================================================
def build_app_launcher():
    """
    یک backend با قابلیت سرو frontend می‌سازیم:
    - تمام محتوای backend.py را import می‌کنیم
    - سپس روت /app را برای frontend اضافه می‌کنیم
    """
    print(f"\n{C.CYAN}🔧 ساخت لانچر یکپارچه...{C.RESET}")

    launcher_code = f'''
import sys, os
from pathlib import Path
sys.path.insert(0, r"{ROOT}")

# import backend app
import backend
from backend import app, init_db
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

FRONTEND = Path(r"{FRONTEND_FILE}")

@app.get("/app", include_in_schema=False)
@app.get("/app/", include_in_schema=False)
def serve_frontend():
    if not FRONTEND.exists():
        return HTMLResponse("<h1>frontend.html یافت نشد</h1>", status_code=404)
    return FileResponse(str(FRONTEND), media_type="text/html")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return HTMLResponse("", status_code=204)

if __name__ == "__main__":
    init_db()
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
'''
    launcher_path = ROOT / "_hamrah_launcher.py"
    launcher_path.write_text(launcher_code, encoding="utf-8")
    print(f"{C.GREEN}✓{C.RESET} لانچر آماده شد: {launcher_path.name}")
    return launcher_path


# ============================================================
# اجرا
# ============================================================
def open_browser_later(url: str, delay: float = 2.5):
    def worker():
        time.sleep(delay)
        try:
            webbrowser.open(url)
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()


def run_server():
    launcher = build_app_launcher()

    print(f"\n{C.PURPLE}{'═'*62}{C.RESET}")
    print(f"{C.BOLD}{C.ORANGE}  🚀  در حال راه‌اندازی سرور همراه...{C.RESET}")
    print(f"{C.PURPLE}{'═'*62}{C.RESET}\n")

    print(f"  {C.GREEN}🌐 Frontend  :{C.RESET}  {C.CYAN}{FRONTEND_URL}{C.RESET}")
    print(f"  {C.BLUE}📡 Backend   :{C.RESET}  {C.CYAN}{BACKEND_URL}{C.RESET}")
    print(f"  {C.YELLOW}📖 API Docs  :{C.RESET}  {C.CYAN}{DOCS_URL}{C.RESET}")
    print(f"  {C.DIM}💾 Database :{C.RESET}  {C.DIM}{ROOT / 'hamrah.db'}{C.RESET}\n")

    print(f"{C.PURPLE}{'═'*62}{C.RESET}")
    print(f"  {C.DIM}برای توقف: Ctrl+C{C.RESET}")
    print(f"{C.PURPLE}{'═'*62}{C.RESET}\n")

    # باز کردن مرورگر بعد از راه‌اندازی
    open_browser_later(FRONTEND_URL, delay=3.0)

    try:
        # اجرای لانچر در همان پروسه
        os.chdir(ROOT)
        subprocess.run([sys.executable, str(launcher)])
    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}👋 خدانگهدار!{C.RESET}\n")
    except FileNotFoundError:
        print(f"{C.RED}❌ خطا در اجرای سرور.{C.RESET}")
        sys.exit(1)


def cleanup():
    launcher = ROOT / "_hamrah_launcher.py"
    if launcher.exists():
        try:
            launcher.unlink()
        except Exception:
            pass


# ============================================================
# Main
# ============================================================
def main():
    print(BANNER)

    print(f"{C.BOLD}🔍 بررسی پیش‌نیازها...{C.RESET}")
    check_python_version()
    check_files()
    ensure_packages()

    try:
        run_server()
    finally:
        cleanup()


if __name__ == "__main__":
    main()