import sys
import time
import queue
import threading
import logging
from datetime import datetime

from core.screen_grab import grab_fullscreen, grab_active_window, grab_clipboard_image
from core.sniper import trigger_sniper
from core.markdown_handler import markdown_handler
from core.config import config_manager
from core.clipboard_watcher import clipboard_watcher

logger = logging.getLogger("capture_service")

class CaptureService:
    def __init__(self):
        self.events_queue = queue.Queue(maxsize=100)
        self.last_event_time = 0
        self.recent_events = []
        self.lock = threading.Lock()
        
        # Setup clipboard watcher callback
        clipboard_watcher.on_image_detected = self.handle_captured_image

    def play_sound_feedback(self):
        if not config_manager.get("play_sound", True):
            return
        def _beep():
            try:
                if sys.platform == "win32":
                    import winsound
                    # Play two quick pleasant high pitch tones
                    winsound.Beep(1200, 60)
                    winsound.Beep(1600, 80)
            except Exception as e:
                logger.debug(f"Audio cue failed: {e}")
        threading.Thread(target=_beep, daemon=True).start()

    def send_notification(self, title, message):
        if not config_manager.get("desktop_notification", True):
            return
        def _notify():
            try:
                from plyer import notification
                notification.notify(
                    title=title,
                    message=message,
                    app_name="Markdown 截图助手",
                    timeout=3
                )
            except Exception:
                try:
                    from win10toast import ToastNotifier
                    toaster = ToastNotifier()
                    toaster.show_toast(title, message, duration=2, threaded=True)
                except Exception as e:
                    logger.debug(f"Notification notice: {e}")
        threading.Thread(target=_notify, daemon=True).start()

    def broadcast_event(self, event_type, data):
        event = {
            "id": int(time.time() * 1000),
            "type": event_type,
            "data": data,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        with self.lock:
            self.recent_events.append(event)
            if len(self.recent_events) > 50:
                self.recent_events.pop(0)

        # Non-blocking put
        try:
            self.events_queue.put_nowait(event)
        except queue.Full:
            try:
                self.events_queue.get_nowait()
                self.events_queue.put_nowait(event)
            except Exception:
                pass

    def handle_captured_image(self, pil_image, note="", source="unknown"):
        """
        Receives raw PIL image, saves to asset dir, appends to MD, sends alerts.
        """
        try:
            result = markdown_handler.append_screenshot(pil_image, note=note)
            result["source"] = source

            self.play_sound_feedback()
            self.send_notification(
                "📸 截图已追加到 Markdown",
                f"文件: {result['filename']} | 目标: {result['target_md'].split('/')[-1]}"
            )

            self.broadcast_event("screenshot_added", result)
            logger.info(f"Successfully processed capture from {source}: {result['filename']}")
            return result
        except Exception as e:
            logger.error(f"Error handling captured image: {e}")
            self.broadcast_event("error", {"message": str(e), "source": source})
            raise

    def trigger_region_capture(self):
        """Triggers interactive region sniper."""
        logger.info("Triggering interactive region snip...")
        def on_complete(cropped_image, note):
            self.handle_captured_image(cropped_image, note=note, source="region")

        def on_cancel():
            logger.info("Region snip cancelled.")

        trigger_sniper(on_complete=on_complete, on_cancel=on_cancel)

    def trigger_fullscreen_capture(self, note=""):
        """Instantly grabs fullscreen."""
        logger.info("Triggering fullscreen capture...")
        try:
            img = grab_fullscreen()
            return self.handle_captured_image(img, note=note, source="fullscreen")
        except Exception as e:
            logger.error(f"Fullscreen capture failed: {e}")
            raise

    def trigger_active_window_capture(self, note=""):
        """Instantly grabs active foreground window."""
        logger.info("Triggering active window capture...")
        try:
            img = grab_active_window()
            return self.handle_captured_image(img, note=note, source="window")
        except Exception as e:
            logger.error(f"Active window capture failed: {e}")
            raise

    def trigger_clipboard_capture(self, note=""):
        """Grabs current clipboard image."""
        img = grab_clipboard_image()
        if img:
            return self.handle_captured_image(img, note=note, source="clipboard")
        else:
            raise ValueError("剪贴板中没有有效的图片数据")

capture_service = CaptureService()
