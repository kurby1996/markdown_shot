import sys
import threading
import logging
from pynput import keyboard

from core.config import config_manager

logger = logging.getLogger("hotkey_manager")

def normalize_hotkey_for_pynput(hotkey_str):
    """
    Converts human-friendly string (e.g., 'Ctrl+Alt+A', 'F9', 'Alt+Q')
    to pynput GlobalHotKeys format (e.g., '<ctrl>+<alt>+a', '<f9>', '<alt>+q').
    """
    if not hotkey_str or not isinstance(hotkey_str, str):
        return ""
    
    parts = [p.strip().lower() for p in hotkey_str.split("+") if p.strip()]
    normalized_parts = []
    
    special_keys = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "cmd": "<cmd>",
        "win": "<cmd>",
        "super": "<cmd>",
        "space": "<space>",
        "enter": "<enter>",
        "tab": "<tab>",
        "esc": "<esc>",
        "escape": "<esc>",
        "backspace": "<backspace>",
        "delete": "<delete>",
        "insert": "<insert>",
        "home": "<home>",
        "end": "<end>",
        "pageup": "<page_up>",
        "page_up": "<page_up>",
        "pagedown": "<page_down>",
        "page_down": "<page_down>",
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "print_screen": "<print_screen>",
        "prtscn": "<print_screen>",
        "f1": "<f1>", "f2": "<f2>", "f3": "<f3>", "f4": "<f4>",
        "f5": "<f5>", "f6": "<f6>", "f7": "<f7>", "f8": "<f8>",
        "f9": "<f9>", "f10": "<f10>", "f11": "<f11>", "f12": "<f12>"
    }

    for part in parts:
        if part in special_keys:
            normalized_parts.append(special_keys[part])
        else:
            # Single character or key
            normalized_parts.append(part)

    return "+".join(normalized_parts)

class HotkeyManager:
    def __init__(self):
        self.listener = None
        self.registered_hotkeys = {}
        self.callbacks = {}
        self.status = {
            "active": False,
            "bindings": {},
            "errors": {}
        }
        self.lock = threading.Lock()

    def set_callbacks(self, callbacks):
        """
        callbacks dict:
        {
            'snip_region': func,
            'snip_fullscreen': func,
            'snip_active_window': func
        }
        """
        self.callbacks = callbacks

    def restart_listener(self):
        with self.lock:
            self.stop_listener()
            self.start_listener()

    def start_listener(self):
        hotkeys_cfg = config_manager.get("hotkeys", {})
        hotkey_dict = {}
        bindings_status = {}
        errors = {}

        for action_name, key_str in hotkeys_cfg.items():
            if not key_str:
                continue
            pynput_key = normalize_hotkey_for_pynput(key_str)
            if not pynput_key:
                continue

            callback = self.callbacks.get(action_name)
            if callback:
                # Wrap callback in thread so hotkey listener thread is never blocked
                def make_wrapper(cb, name=action_name):
                    def wrapper():
                        logger.info(f"Triggered hotkey for {name}")
                        threading.Thread(target=cb, daemon=True).start()
                    return wrapper

                hotkey_dict[pynput_key] = make_wrapper(callback)
                bindings_status[action_name] = {
                    "raw": key_str,
                    "pynput": pynput_key,
                    "bound": True
                }

        if not hotkey_dict:
            logger.info("No hotkeys configured to listen.")
            self.status = {"active": False, "bindings": bindings_status, "errors": errors}
            return

        try:
            self.listener = keyboard.GlobalHotKeys(hotkey_dict)
            self.listener.daemon = True
            self.listener.start()
            self.status = {
                "active": True,
                "bindings": bindings_status,
                "errors": {}
            }
            logger.info(f"Hotkey listener active with bindings: {bindings_status}")
        except Exception as e:
            logger.error(f"Failed to start hotkey listener: {e}")
            self.status = {
                "active": False,
                "bindings": bindings_status,
                "errors": {"global": str(e)}
            }

    def stop_listener(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception as e:
                logger.debug(f"Error stopping hotkey listener: {e}")
            self.listener = None
        self.status["active"] = False

    def get_status(self):
        return self.status

hotkey_manager = HotkeyManager()
