import os
import re
import time
from datetime import datetime
from PIL import Image
import logging

from core.config import config_manager

logger = logging.getLogger("markdown_handler")

class MarkdownHandler:
    def __init__(self):
        self.ensure_default_target_file()

    def get_target_md_path(self):
        path = config_manager.get("target_md_path", "").strip()
        if not path:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, "notes", "course_notes.md")
            config_manager.update({"target_md_path": path.replace("\\", "/")})
        return os.path.abspath(path)

    def set_target_md_path(self, new_path):
        norm_path = os.path.abspath(new_path).replace("\\", "/")
        config_manager.update({"target_md_path": norm_path})
        config_manager.add_recent_file(norm_path)
        self.ensure_target_file_exists(norm_path)
        return norm_path

    def ensure_default_target_file(self):
        target_path = self.get_target_md_path()
        self.ensure_target_file_exists(target_path)

    def ensure_target_file_exists(self, target_path):
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if not os.path.exists(target_path):
            try:
                with open(target_path, "w", encoding="utf-8") as f:
                    filename = os.path.splitext(os.path.basename(target_path))[0]
                    title = filename.replace("_", " ").replace("-", " ").title()
                    f.write(f"# 📚 {title} 学习笔记\n\n> 创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n> 记录工具: Markdown 截图助手\n\n---\n\n")
            except Exception as e:
                logger.error(f"Failed to create default markdown file {target_path}: {e}")

    def get_image_save_dir(self):
        target_md = self.get_target_md_path()
        md_dir = os.path.dirname(target_md)
        mode = config_manager.get("image_folder_mode", "relative")

        if mode == "custom":
            custom_folder = config_manager.get("custom_image_folder", "").strip()
            if custom_folder:
                os.makedirs(custom_folder, exist_ok=True)
                return os.path.abspath(custom_folder)

        folder_name = config_manager.get("image_folder_name", "assets").strip() or "assets"
        assets_dir = os.path.join(md_dir, folder_name)
        os.makedirs(assets_dir, exist_ok=True)
        return os.path.abspath(assets_dir)

    def calculate_relative_image_path(self, image_abs_path):
        target_md = self.get_target_md_path()
        md_dir = os.path.dirname(target_md)
        try:
            rel_path = os.path.relpath(image_abs_path, md_dir)
            return rel_path.replace("\\", "/")
        except Exception:
            return image_abs_path.replace("\\", "/")

    def count_existing_screenshots(self):
        target_md = self.get_target_md_path()
        if not os.path.exists(target_md):
            return 0
        try:
            with open(target_md, "r", encoding="utf-8") as f:
                content = f.read()
                # Count markdown images ![...] (...)
                matches = re.findall(r'!\[.*?\]\((.*?)\)', content)
                return len(matches)
        except Exception:
            return 0

    def append_screenshot(self, pil_image, note=""):
        """
        Saves PIL image to image directory and appends markdown formatted text to target md.
        Returns metadata dict about the saved capture.
        """
        target_md = self.get_target_md_path()
        self.ensure_target_file_exists(target_md)

        img_dir = self.get_image_save_dir()
        prefix = config_manager.get("image_prefix", "course_").strip()
        img_format = config_manager.get("image_format", "png").lower()
        quality = int(config_manager.get("image_quality", 95))

        ext = "png" if img_format == "png" else "jpg"
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        millis = int((time.time() % 1) * 1000)
        filename = f"{prefix}{timestamp_str}_{millis:03d}.{ext}"
        image_abs_path = os.path.join(img_dir, filename)

        # Save Image
        try:
            if ext == "jpg":
                rgb_im = pil_image.convert("RGB")
                rgb_im.save(image_abs_path, format="JPEG", quality=quality)
            else:
                pil_image.save(image_abs_path, format="PNG", optimize=True)
        except Exception as e:
            logger.error(f"Failed to save image {image_abs_path}: {e}")
            raise

        # Calculate relative path
        rel_img_path = self.calculate_relative_image_path(image_abs_path)
        capture_index = self.count_existing_screenshots() + 1
        formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")

        # Format markdown content
        template = config_manager.get(
            "markdown_template",
            "\n\n![{filename}]({image_path})\n{note}\n"
        )

        formatted_note = f"\n> 📝 **备注**: {note}" if note else ""

        entry_text = template.replace("{image_path}", rel_img_path) \
                             .replace("{filename}", filename) \
                             .replace("{timestamp}", formatted_time) \
                             .replace("{index}", str(capture_index)) \
                             .replace("{note}", formatted_note) \
                             .replace("{title}", f"截图 {capture_index}")

        # Ensure newline before and after
        if not entry_text.startswith("\n"):
            entry_text = "\n" + entry_text
        if not entry_text.endswith("\n"):
            entry_text = entry_text + "\n"

        # Append to target MD
        try:
            with open(target_md, "a", encoding="utf-8") as f:
                f.write(entry_text)
        except Exception as e:
            logger.error(f"Failed to append to MD {target_md}: {e}")
            raise

        file_size = os.path.getsize(image_abs_path)

        result_data = {
            "index": capture_index,
            "filename": filename,
            "abs_path": image_abs_path.replace("\\", "/"),
            "rel_path": rel_img_path,
            "target_md": target_md.replace("\\", "/"),
            "timestamp": formatted_time,
            "note": note,
            "size": file_size,
            "dimensions": f"{pil_image.width}×{pil_image.height}",
            "width": pil_image.width,
            "height": pil_image.height
        }

        return result_data

    def read_markdown_file(self):
        target_md = self.get_target_md_path()
        if not os.path.exists(target_md):
            self.ensure_target_file_exists(target_md)
        try:
            with open(target_md, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to read MD file {target_md}: {e}")
            return f"# 错误\n读取文件失败: {e}"

    def write_markdown_file(self, content):
        target_md = self.get_target_md_path()
        try:
            with open(target_md, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error(f"Failed to write MD file {target_md}: {e}")
            return False

    def list_recent_captures(self, limit=20):
        """Scans the target Markdown file to extract recently added image entries."""
        target_md = self.get_target_md_path()
        if not os.path.exists(target_md):
            return []

        md_dir = os.path.dirname(target_md)
        captures = []

        try:
            with open(target_md, "r", encoding="utf-8") as f:
                lines = f.readlines()

            current_timestamp = ""
            current_note = ""

            for i, line in enumerate(lines):
                line_str = line.strip()
                # Check for timestamp in heading
                time_match = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', line_str)
                if time_match:
                    current_timestamp = time_match.group(1)

                # Check for note
                if line_str.startswith("> 📝 **备注**:") or line_str.startswith("> 备注:"):
                    current_note = line_str.split(":", 1)[1].strip()

                # Check for image
                img_match = re.search(r'!\[(.*?)\]\((.*?)\)', line_str)
                if img_match:
                    alt_text = img_match.group(1)
                    rel_path = img_match.group(2)
                    filename = os.path.basename(rel_path)
                    abs_path = os.path.normpath(os.path.join(md_dir, rel_path))

                    size_str = ""
                    dims_str = ""
                    w, h = 0, 0
                    if os.path.exists(abs_path):
                        try:
                            file_size = os.path.getsize(abs_path)
                            size_str = f"{file_size / 1024:.1f} KB" if file_size < 1024*1024 else f"{file_size / (1024*1024):.1f} MB"
                            with Image.open(abs_path) as im:
                                w, h = im.size
                                dims_str = f"{w}×{h}"
                        except Exception:
                            pass

                    captures.append({
                        "filename": filename,
                        "alt": alt_text,
                        "rel_path": rel_path,
                        "abs_path": abs_path.replace("\\", "/"),
                        "timestamp": current_timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "note": current_note,
                        "size": size_str,
                        "dimensions": dims_str,
                        "width": w,
                        "height": h,
                        "line_number": i + 1
                    })
                    # Reset current note for next
                    current_note = ""

            # Return in reverse chronological order
            captures.reverse()
            return captures[:limit]
        except Exception as e:
            logger.error(f"Error parsing recent captures from MD: {e}")
            return []

    def update_capture_note(self, filename, new_note):
        """Updates note text for a specific image filename in the markdown document."""
        target_md = self.get_target_md_path()
        if not os.path.exists(target_md):
            return False

        try:
            with open(target_md, "r", encoding="utf-8") as f:
                lines = f.readlines()

            modified = False
            new_lines = []
            i = 0
            while i < len(lines):
                line = lines[i]
                new_lines.append(line)
                if filename in line and line.strip().startswith("!["):
                    # Found image line, check if next line is already a note
                    note_line = f"> 📝 **备注**: {new_note}\n" if new_note.strip() else ""
                    if i + 1 < len(lines) and (lines[i+1].strip().startswith("> 📝 **备注**:") or lines[i+1].strip().startswith("> 备注:")):
                        if note_line:
                            new_lines.append(note_line)
                        i += 1  # Skip old note line
                    else:
                        if note_line:
                            new_lines.append(note_line)
                    modified = True
                i += 1

            if modified:
                with open(target_md, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                return True
        except Exception as e:
            logger.error(f"Failed to update note for {filename}: {e}")
        return False

markdown_handler = MarkdownHandler()
