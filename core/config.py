import os
import json
import logging

logger = logging.getLogger("config_manager")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "target_md_path": os.path.join(BASE_DIR, "notes", "course_notes.md").replace("\\", "/"),
    "image_folder_mode": "relative",  # "relative" (next to MD) or "custom"
    "image_folder_name": "assets",    # used when mode is "relative"
    "custom_image_folder": "",        # used when mode is "custom"
    "image_prefix": "course_",
    "image_format": "png",            # "png" or "jpg"
    "image_quality": 95,
    "hotkeys": {
        "snip_region": "alt+q",
        "snip_fullscreen": "f9",
        "snip_active_window": "alt+w"
    },
    "auto_clipboard_watch": False,
    "markdown_template": "\n\n![{filename}]({image_path})\n{note}\n",
    "play_sound": True,
    "desktop_notification": True,
    "open_browser_on_start": True,
    "server_port": 5000,
    "recent_files": []
}

class ConfigManager:
    def __init__(self, config_path=DEFAULT_CONFIG_PATH):
        self.config_path = config_path
        self.config = self.load()

    def load(self):
        config = DEFAULT_CONFIG.copy()
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    user_cfg = json.load(f)
                    # Deep merge
                    for k, v in user_cfg.items():
                        if isinstance(v, dict) and k in config and isinstance(config[k], dict):
                            config[k].update(v)
                        else:
                            config[k] = v
            except Exception as e:
                logger.error(f"Failed to load config from {self.config_path}: {e}")
        else:
            self.save(config)
        return config

    def save(self, config=None):
        if config is not None:
            self.config = config
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save config to {self.config_path}: {e}")
            return False

    def update(self, partial_dict):
        for k, v in partial_dict.items():
            if isinstance(v, dict) and k in self.config and isinstance(self.config[k], dict):
                self.config[k].update(v)
            else:
                self.config[k] = v
        self.save()
        return self.config

    def get(self, key, default=None):
        return self.config.get(key, default)

    def add_recent_file(self, file_path):
        norm_path = os.path.normpath(file_path).replace("\\", "/")
        recents = self.config.get("recent_files", [])
        if norm_path in recents:
            recents.remove(norm_path)
        recents.insert(0, norm_path)
        self.config["recent_files"] = recents[:10]  # keep top 10
        self.save()

config_manager = ConfigManager()
