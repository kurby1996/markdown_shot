import os
import sys
import time
import socket
import logging
import webbrowser
import threading

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("main")

from core.screen_grab import set_dpi_aware, ensure_desktop_access
from core.config import config_manager
from core.markdown_handler import markdown_handler
from core.hotkey_manager import hotkey_manager
from core.capture_service import capture_service
from core.clipboard_watcher import clipboard_watcher
from server.api import app

def is_port_available(port, host="0.0.0.0"):
    """Check if the port can actually be bound (not in use and not reserved by Windows OS/Hyper-V)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False

def find_available_port(start_port=5000, max_attempts=100, host="0.0.0.0"):
    for p in range(start_port, start_port + max_attempts):
        if is_port_available(p, host):
            return p
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))
            return s.getsockname()[1]
    except OSError:
        return start_port

def setup_services():
    # 1. Windows DPI & Desktop Station
    set_dpi_aware()
    ensure_desktop_access()

    # 2. Ensure initial note file
    default_target = markdown_handler.get_target_md_path()
    markdown_handler.ensure_target_file_exists(default_target)
    logger.info(f"Target Markdown: {default_target}")
    logger.info(f"Image Save Dir:  {markdown_handler.get_image_save_dir()}")

    # 3. Setup Hotkey callbacks
    hotkey_manager.set_callbacks({
        "snip_region": capture_service.trigger_region_capture,
        "snip_fullscreen": capture_service.trigger_fullscreen_capture,
        "snip_active_window": capture_service.trigger_active_window_capture
    })
    hotkey_manager.start_listener()

    # 4. Clipboard Watcher
    if config_manager.get("auto_clipboard_watch", False):
        clipboard_watcher.start()

def main():
    print("=" * 60)
    print("  📸 Markdown 视频课程截图助手 - Web 控制台启动中...")
    print("=" * 60)

    setup_services()

    preferred_port = int(config_manager.get("server_port", 5000))
    port = find_available_port(preferred_port)
    url = f"http://127.0.0.1:{port}"

    hotkeys = config_manager.get("hotkeys", {})
    print("\n✅ 系统就绪！当前配置：")
    print(f"   🎯 选区划选截图快捷键 : [{hotkeys.get('snip_region', 'Alt+Q')}]")
    print(f"   ⚡ 全屏快速截图快捷键 : [{hotkeys.get('snip_fullscreen', 'F9')}]")
    print(f"   🪟 活动窗口截图快捷键 : [{hotkeys.get('snip_active_window', 'Alt+W')}]")
    print(f"   📄 目标 Markdown 文档 : {markdown_handler.get_target_md_path()}")
    print(f"   🌐 Web 控制台地址     : {url}\n")
    print("💡 提示：在观看视频课程时，直接按下对应快捷键即可截取画面并自动存入文档！")
    print("=" * 60)

    # Open Browser automatically after server boots
    if config_manager.get("open_browser_on_start", True):
        def _open_url():
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception as e:
                logger.debug(f"Auto open browser notice: {e}")
        threading.Thread(target=_open_url, daemon=True).start()

    # Start Flask Server
    try:
        # Run in single process mode with threading to avoid subshell issues
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        print("\n正在关闭服务与热键监听...")
        hotkey_manager.stop_listener()
        clipboard_watcher.stop()
        print("服务已安全退出。")
    except SystemExit as e:
        hotkey_manager.stop_listener()
        clipboard_watcher.stop()
        if e.code and e.code != 0:
            print(f"\n[错误] Web 服务异常退出 (退出码: {e.code})")
            sys.exit(e.code)
    except Exception as e:
        logger.error(f"Web 服务运行失败: {e}", exc_info=True)
        hotkey_manager.stop_listener()
        clipboard_watcher.stop()
        sys.exit(1)

if __name__ == "__main__":
    main()
