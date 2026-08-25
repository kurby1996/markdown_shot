import os
import sys
import json
import time
import subprocess
import tkinter as tk
from tkinter import filedialog
from flask import Flask, request, jsonify, send_from_directory, Response, send_file
import logging

from core.config import config_manager
from core.markdown_handler import markdown_handler
from core.hotkey_manager import hotkey_manager
from core.capture_service import capture_service
from core.clipboard_watcher import clipboard_watcher

logger = logging.getLogger("server_api")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = config_manager.load()
    hotkey_status = hotkey_manager.get_status()
    target_md = markdown_handler.get_target_md_path()
    image_dir = markdown_handler.get_image_save_dir()
    
    return jsonify({
        "status": "ok",
        "config": cfg,
        "hotkey_status": hotkey_status,
        "target_md_path": target_md,
        "image_save_dir": image_dir,
        "file_exists": os.path.exists(target_md)
    })

@app.route("/api/config", methods=["POST"])
def update_config():
    try:
        data = request.get_json(force=True)
        old_hotkeys = config_manager.get("hotkeys", {})
        old_target = config_manager.get("target_md_path", "")
        old_clipboard = config_manager.get("auto_clipboard_watch", False)

        updated = config_manager.update(data)

        # Check if target MD path changed
        if "target_md_path" in data and data["target_md_path"] != old_target:
            markdown_handler.set_target_md_path(data["target_md_path"])

        # Check if hotkeys changed
        if "hotkeys" in data and data["hotkeys"] != old_hotkeys:
            hotkey_manager.restart_listener()

        # Check if clipboard watch toggled
        if "auto_clipboard_watch" in data:
            if data["auto_clipboard_watch"]:
                clipboard_watcher.start()
            else:
                clipboard_watcher.stop()

        return jsonify({
            "status": "ok",
            "config": updated,
            "hotkey_status": hotkey_manager.get_status(),
            "target_md_path": markdown_handler.get_target_md_path(),
            "image_save_dir": markdown_handler.get_image_save_dir()
        })
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/markdown", methods=["GET"])
def get_markdown():
    content = markdown_handler.read_markdown_file()
    target_md = markdown_handler.get_target_md_path()
    img_count = markdown_handler.count_existing_screenshots()
    
    return jsonify({
        "status": "ok",
        "path": target_md,
        "filename": os.path.basename(target_md),
        "content": content,
        "screenshot_count": img_count,
        "last_modified": os.path.getmtime(target_md) if os.path.exists(target_md) else 0
    })

@app.route("/api/markdown", methods=["POST"])
def save_markdown():
    try:
        data = request.get_json(force=True)
        content = data.get("content", "")
        success = markdown_handler.write_markdown_file(content)
        if success:
            return jsonify({"status": "ok", "message": "保存成功"})
        else:
            return jsonify({"status": "error", "message": "保存失败"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/captures", methods=["GET"])
def get_captures():
    limit = int(request.args.get("limit", 30))
    captures = markdown_handler.list_recent_captures(limit=limit)
    return jsonify({
        "status": "ok",
        "captures": captures,
        "count": len(captures)
    })

@app.route("/api/capture/region", methods=["POST"])
def capture_region():
    try:
        capture_service.trigger_region_capture()
        return jsonify({"status": "ok", "message": "选区截图已启动"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/capture/fullscreen", methods=["POST"])
def capture_fullscreen():
    try:
        data = request.get_json(silent=True) or {}
        note = data.get("note", "")
        res = capture_service.trigger_fullscreen_capture(note=note)
        return jsonify({"status": "ok", "data": res})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/capture/window", methods=["POST"])
def capture_window():
    try:
        data = request.get_json(silent=True) or {}
        note = data.get("note", "")
        res = capture_service.trigger_active_window_capture(note=note)
        return jsonify({"status": "ok", "data": res})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/capture/clipboard", methods=["POST"])
def capture_clipboard():
    try:
        data = request.get_json(silent=True) or {}
        note = data.get("note", "")
        res = capture_service.trigger_clipboard_capture(note=note)
        return jsonify({"status": "ok", "data": res})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/capture/update-note", methods=["POST"])
def update_capture_note():
    try:
        data = request.get_json(force=True)
        filename = data.get("filename", "").strip()
        new_note = data.get("note", "").strip()
        if not filename:
            return jsonify({"status": "error", "message": "Missing filename"}), 400

        success = markdown_handler.update_capture_note(filename, new_note)
        if success:
            return jsonify({"status": "ok", "message": "备注更新成功"})
        else:
            return jsonify({"status": "error", "message": "未找到匹配的截图项"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/file/pick", methods=["POST"])
def pick_file():
    """Opens native Windows file dialog to choose Markdown file."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_file = filedialog.askopenfilename(
            title="选择要记录截图的 Markdown 文件",
            filetypes=[("Markdown Files", "*.md;*.markdown"), ("All Files", "*.*")],
            parent=root
        )
        root.destroy()

        if selected_file:
            norm_path = markdown_handler.set_target_md_path(selected_file)
            return jsonify({
                "status": "ok",
                "path": norm_path,
                "filename": os.path.basename(norm_path),
                "image_save_dir": markdown_handler.get_image_save_dir()
            })
        else:
            return jsonify({"status": "cancelled"})
    except Exception as e:
        logger.error(f"Pick file failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/file/pick-dir", methods=["POST"])
def pick_dir():
    """Opens native Windows directory dialog to choose image folder."""
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected_dir = filedialog.askdirectory(
            title="选择图片保存文件夹",
            parent=root
        )
        root.destroy()

        if selected_dir:
            norm_path = os.path.abspath(selected_dir).replace("\\", "/")
            config_manager.update({
                "image_folder_mode": "custom",
                "custom_image_folder": norm_path
            })
            return jsonify({
                "status": "ok",
                "path": norm_path
            })
        else:
            return jsonify({"status": "cancelled"})
    except Exception as e:
        logger.error(f"Pick dir failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/file/create", methods=["POST"])
def create_file():
    try:
        data = request.get_json(force=True)
        file_path = data.get("path", "").strip()
        title = data.get("title", "").strip()

        if not file_path:
            # Default in notes dir
            title_slug = title.strip().replace(" ", "_") if title else f"course_{int(time.time())}"
            file_path = os.path.join(BASE_DIR, "notes", f"{title_slug}.md")

        norm_path = os.path.abspath(file_path).replace("\\", "/")
        os.makedirs(os.path.dirname(norm_path), exist_ok=True)

        doc_title = title or os.path.splitext(os.path.basename(norm_path))[0]
        initial_content = f"# 📚 {doc_title} 课程笔记\n\n> ⏰ 创建时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n> 🎯 目标: 视频课程截图与重点要点记录\n\n---\n\n"

        with open(norm_path, "w", encoding="utf-8") as f:
            f.write(initial_content)

        markdown_handler.set_target_md_path(norm_path)

        return jsonify({
            "status": "ok",
            "path": norm_path,
            "filename": os.path.basename(norm_path),
            "content": initial_content
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

@app.route("/api/file/open-folder", methods=["POST"])
def open_folder():
    """Reveals the target markdown file or asset in Windows Explorer."""
    try:
        data = request.get_json(silent=True) or {}
        target = data.get("target", "md")
        if target == "image" and data.get("path"):
            path = data.get("path")
        elif target == "images":
            path = markdown_handler.get_image_save_dir()
        else:
            path = markdown_handler.get_target_md_path()

        if os.path.exists(path):
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path)])
            return jsonify({"status": "ok", "message": "已打开目录"})
        else:
            return jsonify({"status": "error", "message": "路径不存在"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/file/open-editor", methods=["POST"])
def open_editor():
    """Opens target markdown in default system editor (Typora / VSCode / Notepad)."""
    try:
        path = markdown_handler.get_target_md_path()
        if os.path.exists(path):
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
            return jsonify({"status": "ok", "message": "已在系统默认编辑器中打开"})
        else:
            return jsonify({"status": "error", "message": "文件不存在"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/api/image-preview")
def image_preview():
    """Serves image file safely for live markdown preview in browser."""
    rel_or_abs = request.args.get("path", "")
    if not rel_or_abs:
        return "Path missing", 400

    target_md = markdown_handler.get_target_md_path()
    md_dir = os.path.dirname(target_md)

    if os.path.isabs(rel_or_abs):
        abs_path = os.path.normpath(rel_or_abs)
    else:
        abs_path = os.path.normpath(os.path.join(md_dir, rel_or_abs))

    if os.path.exists(abs_path) and os.path.isfile(abs_path):
        return send_file(abs_path)
    else:
        return "Image not found", 404

@app.route("/api/events")
def sse_events():
    """Server-Sent Events endpoint for real-time reactive UI updates."""
    def event_stream():
        last_id = 0
        while True:
            try:
                # Check for recent events
                with capture_service.lock:
                    pending = [e for e in capture_service.recent_events if e["id"] > last_id]
                
                for ev in pending:
                    last_id = max(last_id, ev["id"])
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"

                time.sleep(0.5)
            except Exception:
                time.sleep(1)

    return Response(event_stream(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no"
    })
