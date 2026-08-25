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

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def find_available_port(start_port=5000, max_attempts=10):
    for p in range(start_port, start_port + max_attempts):
        if not is_port_in_use(p):
            return p
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
    except (KeyboardInterrupt, SystemExit):
        print("\n正在关闭服务与热键监听...")
        hotkey_manager.stop_listener()
        clipboard_watcher.stop()
        print("服务已安全退出。")

if __name__ == "__main__":
    main()
