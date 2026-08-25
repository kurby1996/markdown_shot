import time
import threading
import hashlib
from PIL import Image
import logging

from core.screen_grab import grab_clipboard_image
from core.config import config_manager

logger = logging.getLogger("clipboard_watcher")

class ClipboardWatcher:
    def __init__(self, on_image_detected=None):
        self.on_image_detected = on_image_detected
        self.is_running = False
        self.thread = None
        self.last_img_hash = None

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("Clipboard watcher started.")

    def stop(self):
        self.is_running = False
        logger.info("Clipboard watcher stopped.")

    def _get_image_hash(self, img):
        try:
            # Downsample for quick hash
            small = img.resize((32, 32)).convert("RGB")
            return hashlib.md5(small.tobytes()).hexdigest()
        except Exception:
            return None

    def _loop(self):
        # Initialize with current clipboard image if any so we don't trigger immediately
        init_img = grab_clipboard_image()
        if init_img:
            self.last_img_hash = self._get_image_hash(init_img)

        while self.is_running:
            try:
                enabled = config_manager.get("auto_clipboard_watch", False)
                if enabled:
                    img = grab_clipboard_image()
                    if img is not None:
                        img_hash = self._get_image_hash(img)
                        if img_hash and img_hash != self.last_img_hash:
                            self.last_img_hash = img_hash
                            logger.info("New image detected in clipboard.")
                            if self.on_image_detected:
                                self.on_image_detected(img, note="", source="clipboard")
                time.sleep(0.6)
            except Exception as e:
                logger.debug(f"Error in clipboard loop: {e}")
                time.sleep(1.0)

clipboard_watcher = ClipboardWatcher()
