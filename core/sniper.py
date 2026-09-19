import sys
import os
import time
import math
import threading
import tkinter as tk
from tkinter import font as tkfont
from PIL import Image, ImageTk, ImageEnhance, ImageDraw, ImageFont
import logging

from core.screen_grab import grab_fullscreen, get_virtual_screen_geometry, set_dpi_aware, copy_image_to_clipboard

logger = logging.getLogger("sniper")

# Snipaste 8-color palette
PALETTE = [
    ("#ef4444", "经典红"),
    ("#f97316", "活力橙"),
    ("#eab308", "亮黄色"),
    ("#22c55e", "荧光绿"),
    ("#06b6d4", "青蓝色"),
    ("#3b82f6", "天空蓝"),
    ("#a855f7", "优雅紫"),
    ("#ffffff", "纯白色"),
    ("#0f172a", "深黑色"),
]

def get_system_font(size=18, bold=True):
    """Loads high-quality system font."""
    font_candidates = [
        "msyhbd.ttc" if bold else "msyh.ttc",
        "msyh.ttc",
        "simhei.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "arial.ttf",
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for font_name in font_candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def draw_pil_arrow(draw, start, end, fill, width):
    """Draws a clean Snipaste-style arrow on PIL ImageDraw."""
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 2:
        return

    head_length = max(14, min(width * 4.5 + 8, length * 0.75))
    head_width = max(10, head_length * 0.75)
    angle = math.atan2(dy, dx)

    shaft_retract = head_length * 0.6
    shaft_x = x2 - shaft_retract * math.cos(angle)
    shaft_y = y2 - shaft_retract * math.sin(angle)

    draw.line([(x1, y1), (shaft_x, shaft_y)], fill=fill, width=width)

    base_x = x2 - head_length * math.cos(angle)
    base_y = y2 - head_length * math.sin(angle)
    sin_a = math.sin(angle)
    cos_a = math.cos(angle)

    p_left = (base_x - head_width * 0.5 * sin_a, base_y + head_width * 0.5 * cos_a)
    p_right = (base_x + head_width * 0.5 * sin_a, base_y - head_width * 0.5 * cos_a)

    draw.polygon([(x2, y2), p_left, p_right], fill=fill)

def wrap_text_to_width(text, font, max_width):
    """Wraps text so no line exceeds max_width in pixels using font metrics, respecting words and CJK."""
    if not max_width or max_width <= 0:
        return text

    def _measure(s):
        try:
            return font.getlength(s)
        except AttributeError:
            bbox = font.getbbox(s)
            return bbox[2] - bbox[0]

    result_lines = []
    for raw_line in text.split("\n"):
        if not raw_line or _measure(raw_line) <= max_width:
            result_lines.append(raw_line)
            continue

        tokens = []
        buf = ""
        for ch in raw_line:
            if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
                if buf:
                    tokens.append(buf)
                    buf = ""
                tokens.append(ch)
            elif ch == ' ':
                buf += ch
                tokens.append(buf)
                buf = ""
            else:
                buf += ch
        if buf:
            tokens.append(buf)

        cur_line = ""
        for tok in tokens:
            test_line = cur_line + tok
            if _measure(test_line) > max_width and cur_line:
                result_lines.append(cur_line.rstrip(" "))
                cur_line = tok.lstrip(" ")
            else:
                cur_line = test_line
        if cur_line:
            result_lines.append(cur_line.rstrip(" "))
    return "\n".join(result_lines)

def draw_pil_text(draw, pos, text, fill, size, max_width=0):
    """Draws transparent text without background, with contrast outline."""
    font = get_system_font(size=size, bold=True)
    if max_width and max_width > 0:
        text = wrap_text_to_width(text, font, max_width)
    x, y = pos
    outline_color = (0, 0, 0, 220) if fill not in ("#0f172a", "#000000") else (255, 255, 255, 220)
    for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        draw.multiline_text((x + ox, y + oy), text, fill=outline_color, font=font, spacing=4)
    draw.multiline_text((x, y), text, fill=fill, font=font, spacing=4)


class SniperOverlay:
    def __init__(self, full_image, on_complete=None, on_cancel=None):
        self.full_image = full_image
        self.on_complete = on_complete
        self.on_cancel = on_cancel
        self.root = None
        self.canvas = None

        # Selection coordinates
        self.start_x = None
        self.start_y = None
        self.cur_x = None
        self.cur_y = None
        self.is_selecting = False
        self.has_selection = False
        self.confirmed = False

        # Tools: 'rect', 'oval', 'arrow', 'pen', 'text'
        self.active_tool = "rect"
        self.active_color = "#ef4444"  # Default red
        self.stroke_width = 4         # Default 4px (wheel adjustable 1~24)
        self.font_size = 18           # Default 18pt (wheel adjustable 12~36)
        self.annotations = []
        self.redo_stack = []

        # In-progress drawing
        self.is_drawing_tool = False
        self.draw_start_x = None
        self.draw_start_y = None
        self.pen_points = []
        self.current_text_entry = None
        self.current_text_entry_frame = None
        self.text_auto_wrap = True
        self.btn_wrap = None
        self.hud_timer = None
        self.selected_text_index = None
        self.is_dragging_text = False
        self.drag_text_offset_x = 0
        self.drag_text_offset_y = 0
        self.is_resizing_text = False
        self.text_resize_handle = None
        self.text_resize_start = None
        self.text_resize_orig_pos = None
        self.text_resize_orig_w = None
        self.text_resize_orig_bbox = None
        self.text_editor_custom_w = None
        self.current_text_editor_grip = None
        self.editing_annotation_index = None
        self.reopen_backup_item = None
        self.undo_delete_stack = []

        # Darkened overlay background
        enhancer = ImageEnhance.Brightness(self.full_image)
        self.dark_image = enhancer.enhance(0.4)

        self.tk_dark_img = None
        self.tk_orig_img = None
        self.toolbar_frame = None
        self.tool_buttons = {}
        self.color_buttons = {}
        self.lbl_size_val = None
        self.note_var = None
        self._focus_after_ids = []
        self._global_listener = None

    def start(self):
        set_dpi_aware()
        self.root = tk.Tk()
        self.root.title("Snipaste-like Sniper")
        self.root.attributes("-topmost", True)
        self.root.attributes("-fullscreen", True)
        self.root.config(cursor="cross")

        v_left, v_top, v_width, v_height = get_virtual_screen_geometry()
        self.root.geometry(f"{v_width}x{v_height}+{v_left}+{v_top}")
        self.root.overrideredirect(True)

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg="black", takefocus=True)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.tk_dark_img = ImageTk.PhotoImage(self.dark_image)
        self.canvas.create_image(0, 0, image=self.tk_dark_img, anchor=tk.NW, tags="bg")

        # Initial instruction
        self.show_initial_hint(v_width, v_height)

        # Mouse bindings
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<Motion>", self.on_mouse_hover)
        
        # Mouse Wheel for dynamic stroke width and font size adjustment
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.root.bind("<MouseWheel>", self.on_mouse_wheel)

        # Cancel screenshot: right-click or Esc. Enter behavior depends on selection state.
        self.canvas.bind("<ButtonPress-3>", self.on_cancel_event)
        self.root.bind("<ButtonPress-3>", self.on_cancel_event)
        self.root.bind_all("<ButtonPress-3>", self.on_cancel_event)
        for w in (self.root, self.canvas):
            w.bind("<Escape>", self.on_cancel_event)
            w.bind("<KeyPress-Escape>", self.on_cancel_event)
            w.bind("<Return>", self.on_enter_event)
            w.bind("<KP_Enter>", self.on_enter_event)
            w.bind("<KeyPress-Return>", self.on_enter_event)
            w.bind("<KeyPress-KP_Enter>", self.on_enter_event)
        self.root.bind_all("<Escape>", self.on_cancel_event)
        self.root.bind_all("<KeyPress-Escape>", self.on_cancel_event)
        self.root.bind_all("<Return>", self.on_enter_event)
        self.root.bind_all("<KP_Enter>", self.on_enter_event)
        self.root.bind_all("<KeyPress-Return>", self.on_enter_event)
        self.root.bind_all("<KeyPress-KP_Enter>", self.on_enter_event)
        self.root.bind_all("<KeyPress>", self.on_key_press)
        self.root.bind("<space>", self.on_space_event)
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-Z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.bind("<Control-Y>", lambda e: self.redo())
        self.root.bind("<Control-c>", lambda e: self.copy_to_clipboard())
        self.root.bind("<Control-C>", lambda e: self.copy_to_clipboard())
        self.root.bind("<Delete>", self.delete_selected_annotation)
        self.root.bind("<BackSpace>", self.delete_selected_annotation)

        # Hotkeys for tools
        self.root.bind("1", lambda e: self.handle_quick_tool_key("rect"))
        self.root.bind("2", lambda e: self.handle_quick_tool_key("oval"))
        self.root.bind("3", lambda e: self.handle_quick_tool_key("arrow"))
        self.root.bind("4", lambda e: self.handle_quick_tool_key("pen"))
        self.root.bind("5", lambda e: self.handle_quick_tool_key("text"))
        self.root.bind("r", lambda e: self.handle_quick_tool_key("rect"))
        self.root.bind("R", lambda e: self.handle_quick_tool_key("rect"))
        self.root.bind("o", lambda e: self.handle_quick_tool_key("oval"))
        self.root.bind("O", lambda e: self.handle_quick_tool_key("oval"))
        self.root.bind("a", lambda e: self.handle_quick_tool_key("arrow"))
        self.root.bind("A", lambda e: self.handle_quick_tool_key("arrow"))
        self.root.bind("t", lambda e: self.handle_quick_tool_key("text"))
        self.root.bind("T", lambda e: self.handle_quick_tool_key("text"))

        self.root.bind("<Map>", lambda e: self._focus_overlay())
        self._focus_overlay()
        self._focus_after_ids = [
            self.root.after(30, self._focus_overlay),
            self.root.after(120, self._focus_overlay),
        ]

        # Global key listener for Enter / Esc to guarantee response even if window lacks OS focus
        try:
            from pynput import keyboard as pynput_keyboard
            def _on_global_key_press(key):
                if self.confirmed:
                    return
                # If editing text annotation on canvas, don't hijack Enter
                if self.current_text_entry:
                    if key == pynput_keyboard.Key.esc or getattr(key, 'vk', None) == 27:
                        try:
                            self.root.after_idle(self.cancel_text_entry)
                        except Exception:
                            pass
                    return

                is_enter = (key == pynput_keyboard.Key.enter) or (getattr(key, 'vk', None) in (13, 108))
                is_esc = (key == pynput_keyboard.Key.esc) or (getattr(key, 'vk', None) == 27)

                if is_enter:
                    try:
                        self.root.after_idle(lambda: self.on_enter_event(None))
                    except Exception:
                        pass
                elif is_esc:
                    try:
                        self.root.after_idle(lambda: self.on_cancel_event(None))
                    except Exception:
                        pass

            self._global_listener = pynput_keyboard.Listener(on_press=_on_global_key_press)
            self._global_listener.daemon = True
            self._global_listener.start()
        except Exception as e:
            logger.warning(f"Could not start overlay global key listener: {e}")

        self.root.mainloop()

    def show_initial_hint(self, width, height):
        hint_text = "🎯 拖拽鼠标选取截图区域 | 滚轮可调节线条粗细 | 右键或 Enter 取消截图"
        hx = width // 2
        hy = 36
        self.canvas.create_rectangle(
            hx - 250, hy - 14, hx + 250, hy + 14,
            fill="#0f172a", outline="#38bdf8", width=1, tags="initial_hint"
        )
        self.canvas.create_text(
            hx, hy,
            text=hint_text,
            fill="#38bdf8",
            font=("Microsoft YaHei", 9, "bold"),
            tags="initial_hint"
        )

    def on_mouse_wheel(self, event):
        """
        Scroll wheel dynamically increases or decreases stroke width and font size.
        If an annotation was just drawn, its size updates in real time!
        """
        if not self.has_selection:
            return

        delta = 1 if event.delta > 0 else -1
        new_width = max(1, min(24, self.stroke_width + delta))
        if new_width == self.stroke_width:
            return

        self.stroke_width = new_width
        self.font_size = max(11, min(36, int(self.stroke_width * 2 + 10)))

        # Update size badge in toolbar
        if self.lbl_size_val:
            try:
                self.lbl_size_val.config(text=f"{self.stroke_width}px")
            except Exception:
                pass

        # If a text annotation is selected, adjust its font size directly!
        if self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            item = self.annotations[self.selected_text_index]
            if item["type"] == "text":
                new_size = max(10, min(54, item.get("size", self.font_size) + delta * 2))
                item["size"] = new_size
                self.font_size = new_size
                if self.lbl_size_val:
                    try:
                        self.lbl_size_val.config(text=f"{new_size}pt")
                    except Exception:
                        pass
                self.redraw_annotations()
                self.show_size_hud(event.x, event.y)
                return

        # Update last drawn annotation in real-time if exists
        if self.annotations:
            last = self.annotations[-1]
            if last["type"] in ["rect", "oval", "arrow", "pen"]:
                last["width"] = self.stroke_width
            elif last["type"] == "text":
                last["size"] = self.font_size
            self.redraw_annotations()

        # Update active text editor dynamically if typing
        if self.current_text_entry:
            top, tw, (x, y), _, color, dims = self.current_text_entry
            new_size = self.font_size
            self.current_text_entry = (top, tw, (x, y), new_size, color, dims)
            try:
                tw.config(font=("Microsoft YaHei", new_size, "bold"))
                self.update_text_editor_geometry()
            except Exception:
                pass

        # Show floating HUD near mouse
        self.show_size_hud(event.x, event.y)

    def show_size_hud(self, x, y):
        if not self.canvas:
            return
        self.canvas.delete("size_hud")
        if self.is_resizing_text and self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            item = self.annotations[self.selected_text_index]
            w = item.get("wrap_width", 0)
            hud_text = f" ↔ 文本框宽度: {w}px "
        elif self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            item = self.annotations[self.selected_text_index]
            if item["type"] == "text":
                hud_text = f" 🔤 文字字号: {item.get('size', self.font_size)}pt "
            else:
                hud_text = f" 📏 粗细: {self.stroke_width}px | 字号: {self.font_size}pt "
        else:
            hud_text = f" 📏 粗细: {self.stroke_width}px | 字号: {self.font_size}pt "
        hx = x + 15
        hy = y - 25
        self.canvas.create_rectangle(
            hx, hy, hx + len(hud_text) * 7 + 10, hy + 20,
            fill="#0f172a", outline="#38bdf8", width=1, tags="size_hud"
        )
        self.canvas.create_text(
            hx + 6, hy + 10,
            text=hud_text,
            fill="#f8fafc",
            anchor=tk.W,
            font=("Segoe UI", 9, "bold"),
            tags="size_hud"
        )

        if self.hud_timer and self.root:
            try:
                self.root.after_cancel(self.hud_timer)
            except Exception:
                pass
        if self.root:
            self.hud_timer = self.root.after(1200, lambda: self.canvas.delete("size_hud") if self.canvas else None)


    def handle_quick_tool_key(self, tool_name):
        if self.current_text_entry:
            return
        focused = self.root.focus_get()
        if isinstance(focused, tk.Entry) or isinstance(focused, tk.Text):
            return
        if self.has_selection:
            self.set_tool(tool_name)

    def on_space_event(self, event):
        if self.current_text_entry:
            return
        focused = self.root.focus_get()
        if isinstance(focused, tk.Entry) or isinstance(focused, tk.Text):
            return
        self.on_confirm_event()

    def get_norm_coords(self):
        if self.start_x is None or self.cur_x is None:
            return 0, 0, 0, 0
        x1 = min(self.start_x, self.cur_x)
        y1 = min(self.start_y, self.cur_y)
        x2 = max(self.start_x, self.cur_x)
        y2 = max(self.start_y, self.cur_y)
        return int(x1), int(y1), int(x2), int(y2)

    def is_inside_selection(self, x, y):
        if not self.has_selection:
            return False
        x1, y1, x2, y2 = self.get_norm_coords()
        return x1 <= x <= x2 and y1 <= y <= y2

    def clamp_to_selection(self, x, y):
        x1, y1, x2, y2 = self.get_norm_coords()
        return max(x1, min(x, x2)), max(y1, min(y, y2))

    def on_mouse_hover(self, event):
        if self.has_selection and self.is_inside_selection(event.x, event.y):
            # Check if hovering over resize handles or borders of selected text
            if self.selected_text_index is not None:
                handle = self.get_text_resize_handle_at(event.x, event.y)
                if handle in ("e", "w"):
                    self.canvas.config(cursor="size_we")
                    return
                elif handle in ("n", "s"):
                    self.canvas.config(cursor="size_ns")
                    return
                elif handle in ("nw", "se"):
                    self.canvas.config(cursor="size_nw_se")
                    return
                elif handle in ("ne", "sw"):
                    self.canvas.config(cursor="size_ne_sw")
                    return
                elif handle == "move":
                    self.canvas.config(cursor="fleur")
                    return

            hit_idx = self.find_text_annotation_at(event.x, event.y)
            if hit_idx is not None:
                if hit_idx == self.selected_text_index:
                    self.canvas.config(cursor="fleur")
                else:
                    self.canvas.config(cursor="hand2")
                return

            if self.active_tool == "text":
                self.canvas.config(cursor="xterm")
            elif self.active_tool == "pen":
                self.canvas.config(cursor="pencil")
            else:
                self.canvas.config(cursor="cross")
        else:
            self.canvas.config(cursor="cross")

    def on_mouse_down(self, event):
        if not self.current_text_entry:
            try:
                self.canvas.focus_set()
            except Exception:
                pass
        if self.current_text_entry:
            top, tw, (tx, ty), font_size, color, dims = self.current_text_entry
            box_w, box_h = dims[0], dims[1]
            if tx <= event.x <= tx + box_w and ty <= event.y <= ty + box_h:
                rel_x = event.x - tx
                rel_y = event.y - ty
                try:
                    tw.mark_set(tk.INSERT, f"@{rel_x},{rel_y}")
                    tw.focus_set()
                except Exception:
                    pass
                return
            else:
                self.commit_text_entry()
                # Check if clicking on another text annotation directly
                hit_idx = self.find_text_annotation_at(event.x, event.y)
                if hit_idx is not None and hit_idx != self.selected_text_index:
                    self.selected_text_index = hit_idx
                    item = self.annotations[hit_idx]
                    self.font_size = item.get("size", self.font_size)
                    self.active_color = item.get("color", self.active_color)
                    self.set_color(self.active_color)
                    self.redraw_annotations()
                return

        if self.has_selection:
            if self.is_inside_selection(event.x, event.y):
                # 1. Check if clicking on resize handles or borders of currently selected text
                if self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
                    handle = self.get_text_resize_handle_at(event.x, event.y)
                    if handle and handle != "move":
                        item = self.annotations[self.selected_text_index]
                        bx1, by1, bx2, by2 = self.get_text_annotation_bbox(item)
                        self.is_resizing_text = True
                        self.text_resize_handle = handle
                        self.text_resize_start = (event.x, event.y)
                        self.text_resize_orig_pos = item["pos"]
                        pad = 8
                        cur_w = (bx2 - bx1) - pad * 2
                        self.text_resize_orig_w = item.get("wrap_width", 0) or cur_w
                        self.text_resize_orig_bbox = (bx1, by1, bx2, by2)
                        return
                    elif handle == "move":
                        item = self.annotations[self.selected_text_index]
                        self.is_dragging_text = True
                        self.drag_text_offset_x = event.x - item["pos"][0]
                        self.drag_text_offset_y = event.y - item["pos"][1]
                        return

                # 2. Check if clicking on an existing text annotation
                hit_idx = self.find_text_annotation_at(event.x, event.y)
                if hit_idx is not None:
                    self.selected_text_index = hit_idx
                    item = self.annotations[hit_idx]
                    self.font_size = item.get("size", self.font_size)
                    self.active_color = item.get("color", self.active_color)
                    self.set_color(self.active_color)
                    if self.lbl_size_val:
                        try:
                            self.lbl_size_val.config(text=f"{self.font_size}pt")
                        except Exception:
                            pass

                    # Prepare for dragging
                    self.is_dragging_text = True
                    self.drag_text_offset_x = event.x - item["pos"][0]
                    self.drag_text_offset_y = event.y - item["pos"][1]

                    self.redraw_annotations()
                    return

                # 3. If clicking on empty space, deselect any selected text
                if self.selected_text_index is not None:
                    self.selected_text_index = None
                    self.redraw_annotations()

                if self.active_tool == "text":
                    self.open_text_editor(event.x, event.y)
                    return
                self.is_drawing_tool = True
                self.draw_start_x = event.x
                self.draw_start_y = event.y
                if self.active_tool == "pen":
                    self.pen_points = [(event.x, event.y)]
                return
            else:
                # Clicked outside selection: start new selection
                if self.selected_text_index is not None:
                    self.selected_text_index = None
                self.reset_selection()

        self.canvas.delete("initial_hint")
        self.start_x = event.x
        self.start_y = event.y
        self.cur_x = event.x
        self.cur_y = event.y
        self.is_selecting = True
        self.has_selection = False
        self.annotations.clear()
        self.redo_stack.clear()
        self.clear_canvas_elements()
        self.destroy_toolbar()

    def on_mouse_drag(self, event):
        if self.is_resizing_text and self.selected_text_index is not None:
            if 0 <= self.selected_text_index < len(self.annotations):
                item = self.annotations[self.selected_text_index]
                handle = self.text_resize_handle
                dx = event.x - self.text_resize_start[0]
                dy = event.y - self.text_resize_start[1]
                x1, y1, x2, y2 = self.get_norm_coords()

                orig_w = self.text_resize_orig_w
                orig_x, orig_y = self.text_resize_orig_pos

                if "e" in handle:
                    # Dragging right edge / corners: expand or shrink width
                    max_w = max(60, x2 - orig_x - 10)
                    new_w = max(40, min(orig_w + dx, max_w))
                    item["wrap_width"] = int(new_w)
                elif "w" in handle:
                    # Dragging left edge / corners: move x and adjust width
                    new_x = orig_x + dx
                    new_x = max(x1 + 10, min(new_x, orig_x + orig_w - 40))
                    actual_dx = new_x - orig_x
                    new_w = max(40, orig_w - actual_dx)
                    item["pos"] = (int(new_x), item["pos"][1])
                    item["wrap_width"] = int(new_w)

                if "n" in handle:
                    new_y = max(y1 + 10, min(orig_y + dy, y2 - 20))
                    item["pos"] = (item["pos"][0], int(new_y))

                self.redraw_annotations()
                self.show_size_hud(event.x, event.y)
            return

        if self.is_dragging_text and self.selected_text_index is not None:
            if 0 <= self.selected_text_index < len(self.annotations):
                item = self.annotations[self.selected_text_index]
                new_x = event.x - self.drag_text_offset_x
                new_y = event.y - self.drag_text_offset_y
                x1, y1, x2, y2 = self.get_norm_coords()
                bx1, by1, bx2, by2 = self.get_text_annotation_bbox(item)
                box_w = bx2 - bx1
                box_h = by2 - by1
                new_x = max(x1, min(new_x, x2 - box_w + 16))
                new_y = max(y1, min(new_y, y2 - box_h + 16))
                item["pos"] = (int(new_x), int(new_y))
                self.redraw_annotations()
            return

        if self.is_selecting:
            self.cur_x = event.x
            self.cur_y = event.y
            self.redraw_selection_view()
            return

        if self.is_drawing_tool:
            cx, cy = self.clamp_to_selection(event.x, event.y)
            self.render_temp_drawing(cx, cy)

    def on_mouse_up(self, event):
        if self.is_resizing_text:
            self.is_resizing_text = False
            self.text_resize_handle = None
            return

        if self.is_dragging_text:
            self.is_dragging_text = False
            return

        if self.is_selecting:
            self.cur_x = event.x
            self.cur_y = event.y
            self.is_selecting = False
            x1, y1, x2, y2 = self.get_norm_coords()
            if (x2 - x1) > 15 and (y2 - y1) > 15:
                self.has_selection = True
                self.redraw_selection_view()
                self.show_toolbar(x1, y1, x2, y2)
            else:
                self.has_selection = False
                self.clear_canvas_elements()
            return

        if self.is_drawing_tool:
            self.is_drawing_tool = False
            cx, cy = self.clamp_to_selection(event.x, event.y)
            width = self.stroke_width
            color = self.active_color

            if self.active_tool == "rect":
                if abs(cx - self.draw_start_x) > 3 or abs(cy - self.draw_start_y) > 3:
                    self.annotations.append({
                        "type": "rect",
                        "p1": (min(self.draw_start_x, cx), min(self.draw_start_y, cy)),
                        "p2": (max(self.draw_start_x, cx), max(self.draw_start_y, cy)),
                        "color": color,
                        "width": width
                    })
                    self.redo_stack.clear()
                    self.undo_delete_stack.clear()
            elif self.active_tool == "oval":
                if abs(cx - self.draw_start_x) > 3 or abs(cy - self.draw_start_y) > 3:
                    self.annotations.append({
                        "type": "oval",
                        "p1": (min(self.draw_start_x, cx), min(self.draw_start_y, cy)),
                        "p2": (max(self.draw_start_x, cx), max(self.draw_start_y, cy)),
                        "color": color,
                        "width": width
                    })
                    self.redo_stack.clear()
                    self.undo_delete_stack.clear()
            elif self.active_tool == "arrow":
                if math.hypot(cx - self.draw_start_x, cy - self.draw_start_y) > 5:
                    self.annotations.append({
                        "type": "arrow",
                        "p1": (self.draw_start_x, self.draw_start_y),
                        "p2": (cx, cy),
                        "color": color,
                        "width": width
                    })
                    self.redo_stack.clear()
                    self.undo_delete_stack.clear()
            elif self.active_tool == "pen":
                if len(self.pen_points) > 1:
                    self.annotations.append({
                        "type": "pen",
                        "points": list(self.pen_points),
                        "color": color,
                        "width": width
                    })
                    self.redo_stack.clear()
                    self.undo_delete_stack.clear()

            self.canvas.delete("temp_draw")
            self.redraw_annotations()

    def clear_canvas_elements(self):
        self.canvas.delete("overlay_crop")
        self.canvas.delete("selection_box")
        self.canvas.delete("annotation")
        self.canvas.delete("selected_text_box")
        self.canvas.delete("temp_draw")
        self.canvas.delete("hud")
        self.canvas.delete("text_editor_hint")
        self.selected_text_index = None
        self.is_resizing_text = False
        self.text_resize_handle = None
        self.is_dragging_text = False
        self.text_editor_custom_w = None
        if self.current_text_entry:
            self.cancel_text_entry()

    def reset_selection(self):
        self.has_selection = False
        self.is_selecting = False
        self.is_drawing_tool = False
        self.annotations.clear()
        self.redo_stack.clear()
        self.undo_delete_stack.clear()
        self.clear_canvas_elements()
        self.destroy_toolbar()
        v_left, v_top, v_width, v_height = get_virtual_screen_geometry()
        self.show_initial_hint(v_width, v_height)

    def redraw_selection_view(self):
        x1, y1, x2, y2 = self.get_norm_coords()
        w = x2 - x1
        h = y2 - y1

        self.clear_canvas_elements()

        if w <= 0 or h <= 0:
            return

        try:
            cropped = self.full_image.crop((x1, y1, x2, y2))
            self.tk_orig_img = ImageTk.PhotoImage(cropped)
            self.canvas.create_image(x1, y1, image=self.tk_orig_img, anchor=tk.NW, tags="overlay_crop")
        except Exception as e:
            logger.error(f"Error cropping clear area: {e}")

        # Selection border
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#38bdf8",
            width=2,
            tags="selection_box"
        )

        # Dimension HUD badge
        badge_text = f" {w} × {h} px "
        badge_y = y1 - 24 if y1 >= 30 else y1 + 6
        badge_x = x1 + 4
        self.canvas.create_rectangle(
            badge_x, badge_y, badge_x + len(badge_text) * 8 + 12, badge_y + 20,
            fill="#0f172a", outline="#38bdf8", width=1, tags="hud"
        )
        self.canvas.create_text(
            badge_x + 6, badge_y + 10,
            text=badge_text,
            fill="#f8fafc",
            anchor=tk.W,
            font=("Segoe UI", 9, "bold"),
            tags="hud"
        )

        self.redraw_annotations()

    def render_temp_drawing(self, cur_x, cur_y):
        self.canvas.delete("temp_draw")
        width = self.stroke_width
        color = self.active_color
        sx, sy = self.draw_start_x, self.draw_start_y

        if self.active_tool == "rect":
            self.canvas.create_rectangle(
                min(sx, cur_x), min(sy, cur_y), max(sx, cur_x), max(sy, cur_y),
                outline=color, width=width, tags="temp_draw"
            )
        elif self.active_tool == "oval":
            self.canvas.create_oval(
                min(sx, cur_x), min(sy, cur_y), max(sx, cur_x), max(sy, cur_y),
                outline=color, width=width, tags="temp_draw"
            )
        elif self.active_tool == "arrow":
            head_len = max(14, width * 4.5 + 8)
            self.canvas.create_line(
                sx, sy, cur_x, cur_y,
                fill=color,
                width=width,
                arrow=tk.LAST,
                arrowshape=(head_len, head_len + 4, width * 2 + 4),
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags="temp_draw"
            )
        elif self.active_tool == "pen":
            self.pen_points.append((cur_x, cur_y))
            if len(self.pen_points) > 1:
                flat_points = [coord for pt in self.pen_points for coord in pt]
                self.canvas.create_line(
                    flat_points,
                    fill=color,
                    width=width,
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    smooth=True,
                    tags="temp_draw"
                )

    def redraw_annotations(self):
        self.canvas.delete("annotation")
        self.canvas.delete("selected_text_box")
        for item in self.annotations:
            t = item["type"]
            color = item["color"]
            w = item.get("width", self.stroke_width)
            if t == "rect":
                p1, p2 = item["p1"], item["p2"]
                self.canvas.create_rectangle(
                    p1[0], p1[1], p2[0], p2[1],
                    outline=color,
                    width=w,
                    tags="annotation"
                )
            elif t == "oval":
                p1, p2 = item["p1"], item["p2"]
                self.canvas.create_oval(
                    p1[0], p1[1], p2[0], p2[1],
                    outline=color,
                    width=w,
                    tags="annotation"
                )
            elif t == "arrow":
                p1, p2 = item["p1"], item["p2"]
                head_len = max(14, w * 4.5 + 8)
                self.canvas.create_line(
                    p1[0], p1[1], p2[0], p2[1],
                    fill=color,
                    width=w,
                    arrow=tk.LAST,
                    arrowshape=(head_len, head_len + 4, w * 2 + 4),
                    capstyle=tk.ROUND,
                    joinstyle=tk.ROUND,
                    tags="annotation"
                )
            elif t == "pen":
                pts = item["points"]
                if len(pts) > 1:
                    flat_pts = [coord for pt in pts for coord in pt]
                    self.canvas.create_line(
                        flat_pts,
                        fill=color,
                        width=w,
                        capstyle=tk.ROUND,
                        joinstyle=tk.ROUND,
                        smooth=True,
                        tags="annotation"
                    )
            elif t == "text":
                pos = item["pos"]
                text = item["text"]
                font_size = item.get("size", self.font_size)
                wrap_w = item.get("wrap_width", 0)
                font_tuple = ("Microsoft YaHei", font_size, "bold")
                outline_col = "#000000" if color not in ("#0f172a", "#000000") else "#ffffff"
                for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    self.canvas.create_text(
                        pos[0] + ox, pos[1] + oy,
                        text=text,
                        fill=outline_col,
                        font=font_tuple,
                        anchor=tk.NW,
                        width=wrap_w,
                        tags="annotation"
                    )
                self.canvas.create_text(
                    pos[0], pos[1],
                    text=text,
                    fill=color,
                    font=font_tuple,
                    anchor=tk.NW,
                    width=wrap_w,
                    tags="annotation"
                )

        self.draw_selected_text_box()
        if self.canvas:
            self.canvas.update_idletasks()

    def get_text_annotation_bbox(self, item):
        x, y = item["pos"]
        font_size = item.get("size", self.font_size)
        wrap_w = item.get("wrap_width", 0)
        f = tkfont.Font(family="Microsoft YaHei", size=font_size, weight="bold")
        line_h = f.metrics("linespace")

        raw_lines = item["text"].split("\n")
        if wrap_w and wrap_w > 0:
            lines = []
            for rl in raw_lines:
                if not rl:
                    lines.append("")
                    continue
                tokens = []
                buf = ""
                for ch in rl:
                    if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f' or '\uff00' <= ch <= '\uffef':
                        if buf:
                            tokens.append(buf)
                            buf = ""
                        tokens.append(ch)
                    elif ch == ' ':
                        buf += ch
                        tokens.append(buf)
                        buf = ""
                    else:
                        buf += ch
                if buf:
                    tokens.append(buf)

                cur = ""
                for tok in tokens:
                    test = cur + tok
                    if f.measure(test) > wrap_w and cur:
                        lines.append(cur.rstrip(" "))
                        cur = tok.lstrip(" ")
                    else:
                        cur = test
                if cur:
                    lines.append(cur.rstrip(" "))
        else:
            lines = raw_lines

        measured_w = max((f.measure(line) for line in lines), default=28)
        if wrap_w and wrap_w > 0:
            box_w = max(wrap_w, measured_w, 28)
        else:
            box_w = max(measured_w, 28)

        total_lines = max(1, len(lines))
        box_h = max(line_h + 4, total_lines * (line_h + 4))
        pad = 8
        return (x - pad, y - pad, x + box_w + pad, y + box_h + pad)

    def get_text_resize_handle_at(self, x, y):
        if self.selected_text_index is None or not (0 <= self.selected_text_index < len(self.annotations)):
            return None
        item = self.annotations[self.selected_text_index]
        if item["type"] != "text":
            return None

        bx1, by1, bx2, by2 = self.get_text_annotation_bbox(item)

        # 8 Handle hit test (radius 9px around each handle dot)
        r = 9
        mid_x = (bx1 + bx2) // 2
        mid_y = (by1 + by2) // 2

        handles = [
            ("nw", bx1, by1),
            ("ne", bx2, by1),
            ("se", bx2, by2),
            ("sw", bx1, by2),
            ("n", mid_x, by1),
            ("s", mid_x, by2),
            ("w", bx1, mid_y),
            ("e", bx2, mid_y),
        ]
        for name, hx, hy in handles:
            if abs(x - hx) <= r and abs(y - hy) <= r:
                return name

        # Border edge hit test (margin 6px)
        m = 6
        if abs(x - bx2) <= m and (by1 - m) <= y <= (by2 + m):
            return "e"
        if abs(x - bx1) <= m and (by1 - m) <= y <= (by2 + m):
            return "w"
        if abs(y - by2) <= m and (bx1 - m) <= x <= (bx2 + m):
            return "s"
        if abs(y - by1) <= m and (bx1 - m) <= x <= (bx2 + m):
            return "n"

        # Inside the box
        if bx1 < x < bx2 and by1 < y < by2:
            return "move"

        return None

    def find_text_annotation_at(self, x, y):
        # First check if clicking inside currently selected text's badge or bbox
        if self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            item = self.annotations[self.selected_text_index]
            if item["type"] == "text":
                bx1, by1, bx2, by2 = self.get_text_annotation_bbox(item)
                x1, y1, x2, y2 = self.get_norm_coords()
                badge_y = by1 - 24 if by1 >= y1 + 28 else by2 + 6
                badge_x = bx1
                badge_text = f" ↔ 拖边框改长宽 | 🔍 滚轮调字号: {item.get('size', 18)}pt | 拖拽移动 | 双击编辑 | Del删除 "
                badge_w = len(badge_text) * 7 + 10
                if badge_x + badge_w > x2:
                    badge_x = max(x1, x2 - badge_w)
                if (badge_x <= x <= badge_x + badge_w and badge_y <= y <= badge_y + 20) or (bx1 - 8 <= x <= bx2 + 8 and by1 - 8 <= y <= by2 + 8):
                    return self.selected_text_index

        for idx in reversed(range(len(self.annotations))):
            item = self.annotations[idx]
            if item["type"] == "text":
                bx1, by1, bx2, by2 = self.get_text_annotation_bbox(item)
                if bx1 <= x <= bx2 and by1 <= y <= by2:
                    return idx
        return None

    def draw_selected_text_box(self):
        self.canvas.delete("selected_text_box")
        if self.selected_text_index is None:
            return
        if not (0 <= self.selected_text_index < len(self.annotations)):
            self.selected_text_index = None
            return

        item = self.annotations[self.selected_text_index]
        if item["type"] != "text":
            self.selected_text_index = None
            return

        bx1, by1, bx2, by2 = self.get_text_annotation_bbox(item)

        # Dashed selection border
        self.canvas.create_rectangle(
            bx1, by1, bx2, by2,
            outline="#38bdf8",
            width=2,
            dash=(4, 3),
            tags="selected_text_box"
        )

        # 8 Handle dots (modern UI style: white fill, sky blue border)
        handle_size = 5
        mid_x = (bx1 + bx2) // 2
        mid_y = (by1 + by2) // 2
        handles = [
            (bx1, by1), (mid_x, by1), (bx2, by1),
            (bx1, mid_y),             (bx2, mid_y),
            (bx1, by2), (mid_x, by2), (bx2, by2),
        ]
        for hx, hy in handles:
            self.canvas.create_rectangle(
                hx - handle_size, hy - handle_size,
                hx + handle_size, hy + handle_size,
                fill="#ffffff", outline="#0284c7", width=1.5,
                tags="selected_text_box"
            )

        # Floating action badge above or below text
        x1, y1, x2, y2 = self.get_norm_coords()
        badge_y = by1 - 24 if by1 >= y1 + 28 else by2 + 6
        badge_x = bx1
        badge_text = f" ↔ 拖边框改长宽 | 🔍 滚轮调字号: {item.get('size', 18)}pt | 拖拽移动 | 双击编辑 | Del删除 "
        badge_w = len(badge_text) * 7 + 10
        if badge_x + badge_w > x2:
            badge_x = max(x1, x2 - badge_w)
        self.canvas.create_rectangle(
            badge_x, badge_y, badge_x + badge_w, badge_y + 20,
            fill="#0f172a", outline="#38bdf8", width=1, tags="selected_text_box"
        )
        self.canvas.create_text(
            badge_x + 6, badge_y + 10,
            text=badge_text,
            fill="#38bdf8",
            anchor=tk.W,
            font=("Microsoft YaHei", 8, "bold"),
            tags="selected_text_box"
        )

    def delete_selected_annotation(self, event=None):
        if self.current_text_entry:
            return
        focused = self.root.focus_get() if self.root else None
        if isinstance(focused, (tk.Entry, tk.Text)):
            return
        if self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            idx = self.selected_text_index
            item = self.annotations.pop(idx)
            self.undo_delete_stack.append((idx, item))
            self.redo_stack.clear()
            self.selected_text_index = None
            self.redraw_annotations()

    def reopen_text_editor(self, idx):
        if not (0 <= idx < len(self.annotations)):
            return
        item = self.annotations.pop(idx)
        self.selected_text_index = None
        self.editing_annotation_index = idx
        self.reopen_backup_item = dict(item)
        self.redraw_annotations()

        pos = item["pos"]
        self.font_size = item.get("size", self.font_size)
        self.active_color = item.get("color", self.active_color)
        self.set_color(self.active_color)
        self.text_editor_custom_w = item.get("wrap_width", None)
        self.open_text_editor(pos[0], pos[1], initial_text=item["text"])

    def open_text_editor(self, x, y, initial_text=""):
        if self.current_text_entry:
            self.commit_text_entry()

        self.selected_text_index = None
        if self.canvas:
            self.canvas.delete("selected_text_box")

        font_size = self.font_size
        color = self.active_color
        f = tkfont.Font(family="Microsoft YaHei", size=font_size, weight="bold")
        line_h = f.metrics("linespace")

        # Color key for true transparency on Windows
        trans_key = "#000001" if color.lower() != "#000001" else "#000002"

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.transient(self.root)
        top.attributes("-topmost", True)
        try:
            top.attributes("-transparentcolor", trans_key)
        except Exception as e:
            logger.debug(f"Transparent color notice: {e}")
        top.config(bg=trans_key)

        border_frame = tk.Frame(
            top,
            bg=trans_key,
            highlightthickness=1,
            highlightbackground=color,
            highlightcolor=color
        )
        border_frame.pack(fill=tk.BOTH, expand=True)

        # Right-edge drag handle for active editor
        grip_e = tk.Frame(border_frame, width=6, bg=color, cursor="size_we")
        grip_e.pack(side=tk.RIGHT, fill=tk.Y)
        self.current_text_editor_grip = grip_e

        def on_grip_down(event):
            self.editor_drag_start_x = event.x_root
            if self.current_text_entry:
                _, _, _, _, _, dims = self.current_text_entry
                self.editor_drag_orig_w = dims[0]

        def on_grip_motion(event):
            if not self.current_text_entry:
                return
            dx = event.x_root - self.editor_drag_start_x
            _, _, (tx, ty), _, _, _ = self.current_text_entry
            x1, y1, x2, y2 = self.get_norm_coords()
            max_w = max(160, min(x2 - tx - 8, 1400))
            new_w = max(100, min(self.editor_drag_orig_w + dx, max_w))
            self.text_editor_custom_w = int(new_w)
            self.update_text_editor_geometry()

        grip_e.bind("<ButtonPress-1>", on_grip_down)
        grip_e.bind("<B1-Motion>", on_grip_motion)

        text_widget = tk.Text(
            border_frame,
            bg=trans_key,
            fg=color,
            insertbackground=color,
            font=f,
            bd=0,
            highlightthickness=0,
            wrap=tk.WORD if self.text_auto_wrap else tk.NONE,
            undo=True,
            padx=4,
            pady=4,
            spacing2=4,
        )
        text_widget.pack(fill=tk.BOTH, expand=True)
        if initial_text:
            text_widget.insert("1.0", initial_text)
            text_widget.mark_set(tk.INSERT, tk.END)
            text_widget.see(tk.END)
        text_widget.focus_force()

        initial_w = self.text_editor_custom_w if self.text_editor_custom_w else 160
        initial_h = line_h + 16
        dims = [initial_w, initial_h]
        self.current_text_entry = (top, text_widget, (x, y), font_size, color, dims)
        self.current_text_entry_frame = border_frame

        v_left, v_top, _, _ = get_virtual_screen_geometry()
        top.geometry(f"{initial_w}x{initial_h}+{v_left + x}+{v_top + y}")
        top.lift()

        self.update_text_editor_hint(x, y, initial_w, initial_h)

        text_widget.bind("<Return>", lambda e: self.root.after(1, self.update_text_editor_geometry))
        text_widget.bind("<KeyRelease>", lambda e: self.update_text_editor_geometry())
        text_widget.bind("<KeyPress>", lambda e: self.root.after(1, self.update_text_editor_geometry))
        text_widget.bind("<Control-Return>", lambda e: (self.commit_text_entry(), "break")[1])
        text_widget.bind("<Control-KP_Enter>", lambda e: (self.commit_text_entry(), "break")[1])
        text_widget.bind("<Escape>", lambda e: (self.cancel_text_entry(), "break")[1])

        if initial_text or self.text_editor_custom_w:
            self.update_text_editor_geometry()

    def update_text_editor_geometry(self):
        if not self.current_text_entry:
            return
        top, text_widget, (x, y), font_size, color, dims = self.current_text_entry
        f = tkfont.Font(family="Microsoft YaHei", size=font_size, weight="bold")
        line_h = f.metrics("linespace")

        # Crucial fix: get text with trailing newlines intact
        raw_text = text_widget.get("1.0", "end-1c")
        lines = raw_text.split("\n") if raw_text else [""]

        x1, y1, x2, y2 = self.get_norm_coords()
        max_avail_w = max(160, min(x2 - x - 8, 800))
        max_line_w = max((f.measure(line) for line in lines), default=20)

        if getattr(self, "text_editor_custom_w", None) is not None:
            box_w = self.text_editor_custom_w
        else:
            if self.text_auto_wrap:
                box_w = max(160, min(max_line_w + 32, max_avail_w))
            else:
                box_w = max(160, max_line_w + 32)

        total_lines = 0
        for l in lines:
            lw = f.measure(l)
            if self.text_auto_wrap and box_w > 0 and lw > (box_w - 24):
                total_lines += max(1, math.ceil(lw / max(1, box_w - 24)))
            else:
                total_lines += 1

        needed_h = max(line_h + 16, total_lines * (line_h + 4) + 16)
        v_left, v_top, v_width, v_height = get_virtual_screen_geometry()
        max_avail_h = max(line_h + 16, v_height - (v_top + y) - 30)
        box_h = min(needed_h, max_avail_h)

        dims[0] = box_w
        dims[1] = box_h

        target_screen_x = v_left + x
        target_screen_y = v_top + y
        if target_screen_x + box_w > v_left + v_width - 10:
            target_screen_x = max(v_left + 10, v_left + v_width - box_w - 10)

        top.geometry(f"{box_w}x{box_h}+{target_screen_x}+{target_screen_y}")
        top.lift()

        if needed_h <= max_avail_h:
            text_widget.yview_moveto(0.0)
        else:
            text_widget.see(tk.INSERT)

        self.update_text_editor_hint(x, y, box_w, box_h)

    def update_text_editor_hint(self, x, y, box_w, box_h):
        if not self.canvas:
            return
        self.canvas.delete("text_editor_hint")
        hint_text = " 💡 Enter换行 | ↔ 拖右边框调宽 | Ctrl+Enter完成 "
        hx = x
        hy = y + box_h + 4
        x1, y1, x2, y2 = self.get_norm_coords()
        if hy + 22 > y2:
            hy = y - 22
            if hy < y1:
                hy = y + box_h + 4
        badge_w = len(hint_text) * 7 + 10
        self.canvas.create_rectangle(
            hx, hy, hx + badge_w, hy + 20,
            fill="#0f172a", outline="#38bdf8", width=1, tags="text_editor_hint"
        )
        self.canvas.create_text(
            hx + 6, hy + 10,
            text=hint_text,
            fill="#38bdf8",
            anchor=tk.W,
            font=("Microsoft YaHei", 8),
            tags="text_editor_hint"
        )

    def commit_text_entry(self):
        if not self.current_text_entry:
            return
        top, text_widget, pos, font_size, color, (box_w, box_h) = self.current_text_entry
        raw_text = text_widget.get("1.0", "end-1c").strip("\n")
        self.current_text_entry = None
        self.current_text_entry_frame = None
        self.current_text_editor_grip = None
        self.text_editor_custom_w = None
        if self.canvas:
            self.canvas.delete("text_editor_hint")
        try:
            top.destroy()
        except Exception:
            pass
        if self.root:
            self.root.focus_force()

        if raw_text.strip():
            wrap_width = box_w if self.text_auto_wrap else 0
            new_item = {
                "type": "text",
                "pos": pos,
                "text": raw_text,
                "color": color,
                "size": font_size,
                "wrap_width": wrap_width
            }
            if self.editing_annotation_index is not None and 0 <= self.editing_annotation_index <= len(self.annotations):
                self.annotations.insert(self.editing_annotation_index, new_item)
                self.selected_text_index = self.editing_annotation_index
            else:
                self.annotations.append(new_item)
                self.selected_text_index = len(self.annotations) - 1
            self.redo_stack.clear()
            self.undo_delete_stack.clear()
        elif self.reopen_backup_item is not None:
            if self.editing_annotation_index is not None and 0 <= self.editing_annotation_index <= len(self.annotations):
                self.annotations.insert(self.editing_annotation_index, self.reopen_backup_item)
                self.selected_text_index = self.editing_annotation_index

        self.editing_annotation_index = None
        self.reopen_backup_item = None
        self.redraw_annotations()

    def cancel_text_entry(self):
        if not self.current_text_entry:
            return
        top, _, _, _, _, _ = self.current_text_entry
        self.current_text_entry = None
        self.current_text_entry_frame = None
        self.current_text_editor_grip = None
        self.text_editor_custom_w = None
        if self.canvas:
            self.canvas.delete("text_editor_hint")
        try:
            top.destroy()
        except Exception:
            pass
        if self.root:
            self.root.focus_force()

        if self.reopen_backup_item is not None and self.editing_annotation_index is not None:
            if 0 <= self.editing_annotation_index <= len(self.annotations):
                self.annotations.insert(self.editing_annotation_index, self.reopen_backup_item)
                self.selected_text_index = self.editing_annotation_index
            self.editing_annotation_index = None
            self.reopen_backup_item = None

        self.redraw_annotations()

    def toggle_text_wrap(self):
        self.text_auto_wrap = not self.text_auto_wrap
        if hasattr(self, "btn_wrap") and self.btn_wrap:
            self.btn_wrap.config(
                text="↵ 换行:开" if self.text_auto_wrap else "↵ 换行:关",
                bg="#0284c7" if self.text_auto_wrap else "#1e293b",
                fg="#ffffff" if self.text_auto_wrap else "#94a3b8",
                relief=tk.SUNKEN if self.text_auto_wrap else tk.FLAT,
            )
        if self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            item = self.annotations[self.selected_text_index]
            if item["type"] == "text":
                x1, y1, x2, y2 = self.get_norm_coords()
                avail_w = max(160, x2 - item["pos"][0] - 8)
                item["wrap_width"] = avail_w if self.text_auto_wrap else 0
                self.redraw_annotations()

        if self.current_text_entry:
            _, text_widget, _, _, _, _ = self.current_text_entry
            try:
                text_widget.config(wrap=tk.WORD if self.text_auto_wrap else tk.NONE)
                self.update_text_editor_geometry()
            except Exception:
                pass

    def undo(self):
        if self.current_text_entry:
            self.cancel_text_entry()
            return
        self.selected_text_index = None
        self.canvas.delete("selected_text_box")
        if self.undo_delete_stack:
            idx, item = self.undo_delete_stack.pop()
            if 0 <= idx <= len(self.annotations):
                self.annotations.insert(idx, item)
                self.selected_text_index = idx
            else:
                self.annotations.append(item)
                self.selected_text_index = len(self.annotations) - 1
            self.redraw_annotations()
            return
        if self.annotations:
            item = self.annotations.pop()
            self.redo_stack.append(item)
            self.redraw_annotations()

    def redo(self):
        if self.current_text_entry:
            return
        self.selected_text_index = None
        self.canvas.delete("selected_text_box")
        if self.redo_stack:
            item = self.redo_stack.pop()
            self.annotations.append(item)
            if item.get("type") == "text":
                self.selected_text_index = len(self.annotations) - 1
            self.redraw_annotations()

    def clear_annotations(self):
        self.selected_text_index = None
        self.canvas.delete("selected_text_box")
        if self.annotations:
            self.annotations.clear()
            self.redo_stack.clear()
            self.undo_delete_stack.clear()
            self.redraw_annotations()

    def set_tool(self, tool_name):
        if self.current_text_entry:
            self.commit_text_entry()
        self.active_tool = tool_name
        for name, btn in self.tool_buttons.items():
            if name == tool_name:
                btn.config(bg="#0284c7", fg="#ffffff", relief=tk.SUNKEN)
            else:
                btn.config(bg="#1e293b", fg="#e2e8f0", relief=tk.FLAT)

    def set_color(self, hex_color):
        self.active_color = hex_color
        for col, btn in self.color_buttons.items():
            if col == hex_color:
                btn.config(highlightbackground="#ffffff", highlightthickness=2, relief=tk.SOLID)
            else:
                btn.config(highlightbackground="#334155", highlightthickness=1, relief=tk.FLAT)

        # 1. Update currently selected text annotation color in real-time
        if self.selected_text_index is not None and 0 <= self.selected_text_index < len(self.annotations):
            item = self.annotations[self.selected_text_index]
            if item["type"] == "text":
                item["color"] = hex_color
                self.redraw_annotations()
        elif not self.current_text_entry and self.annotations and self.annotations[-1].get("type") == "text":
            self.annotations[-1]["color"] = hex_color
            self.selected_text_index = len(self.annotations) - 1
            self.redraw_annotations()

        # 2. Update active floating text editor if currently typing
        if self.current_text_entry:
            top, tw, pos, font_size, _, dims = self.current_text_entry
            self.current_text_entry = (top, tw, pos, font_size, hex_color, dims)
            try:
                tw.config(fg=hex_color, insertbackground=hex_color)
                if hasattr(self, "current_text_entry_frame") and self.current_text_entry_frame:
                    self.current_text_entry_frame.config(highlightbackground=hex_color, highlightcolor=hex_color)
                if hasattr(self, "current_text_editor_grip") and self.current_text_editor_grip:
                    self.current_text_editor_grip.config(bg=hex_color)
                top.lift()
                tw.focus_force()
            except Exception:
                pass

        if self.canvas:
            self.canvas.update_idletasks()

    def _disable_button_takefocus(self, widget):
        if isinstance(widget, tk.Button):
            try:
                widget.configure(takefocus=0)
            except Exception:
                pass
        for child in widget.winfo_children():
            self._disable_button_takefocus(child)

    def destroy_toolbar(self):
        if self.toolbar_frame:
            try:
                self.toolbar_frame.destroy()
            except Exception:
                pass
            self.toolbar_frame = None
        self.btn_wrap = None
        self.canvas.delete("toolbar_hud")

    def show_toolbar(self, x1, y1, x2, y2):
        """
        Builds a concise, single-row streamlined Snipaste floating toolbar directly below selection.
        """
        self.destroy_toolbar()

        self.toolbar_frame = tk.Frame(
            self.canvas,
            bg="#0f172a",
            bd=1,
            relief=tk.SOLID,
            padx=6,
            pady=4,
            highlightthickness=1,
            highlightbackground="#38bdf8"
        )

        # 1. Compact Drawing Tool Buttons
        tool_defs = [
            ("rect", "🔲 矩形", "矩形框 (1/R)"),
            ("oval", "⭕ 圆形", "椭圆/圆 (2/O)"),
            ("arrow", "↗ 箭头", "指示箭头 (3/A)"),
            ("pen", "✏ 画笔", "自由涂鸦 (4)"),
            ("text", "🔤 文字", "打字标注 (5/T)"),
        ]

        self.tool_buttons = {}
        for tool_key, label, tooltip in tool_defs:
            is_active = (self.active_tool == tool_key)
            btn = tk.Button(
                self.toolbar_frame,
                text=label,
                bg="#0284c7" if is_active else "#1e293b",
                fg="#ffffff" if is_active else "#cbd5e1",
                activebackground="#0369a1",
                activeforeground="#ffffff",
                relief=tk.SUNKEN if is_active else tk.FLAT,
                font=("Microsoft YaHei", 9, "bold"),
                padx=5,
                pady=2,
                cursor="hand2",
                command=lambda k=tool_key: self.set_tool(k)
            )
            btn.pack(side=tk.LEFT, padx=1)
            self.tool_buttons[tool_key] = btn

        # Wrap toggle button for text tool
        self.btn_wrap = tk.Button(
            self.toolbar_frame,
            text="↵ 换行:开" if self.text_auto_wrap else "↵ 换行:关",
            bg="#0284c7" if self.text_auto_wrap else "#1e293b",
            fg="#ffffff" if self.text_auto_wrap else "#94a3b8",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief=tk.SUNKEN if self.text_auto_wrap else tk.FLAT,
            font=("Microsoft YaHei", 9),
            padx=4,
            pady=2,
            cursor="hand2",
            command=self.toggle_text_wrap
        )
        self.btn_wrap.pack(side=tk.LEFT, padx=1)

        # Divider 1
        div1 = tk.Frame(self.toolbar_frame, width=1, height=20, bg="#334155")
        div1.pack(side=tk.LEFT, padx=3)

        # 2. Undo & Clear
        btn_undo = tk.Button(
            self.toolbar_frame,
            text="↩ 撤销",
            bg="#1e293b",
            fg="#cbd5e1",
            activebackground="#334155",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9),
            padx=4,
            pady=2,
            cursor="hand2",
            command=self.undo
        )
        btn_undo.pack(side=tk.LEFT, padx=1)

        btn_clear = tk.Button(
            self.toolbar_frame,
            text="🗑",
            bg="#1e293b",
            fg="#94a3b8",
            activebackground="#334155",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9),
            padx=3,
            pady=2,
            cursor="hand2",
            command=self.clear_annotations
        )
        btn_clear.pack(side=tk.LEFT, padx=1)

        # Divider 2
        div2 = tk.Frame(self.toolbar_frame, width=1, height=20, bg="#334155")
        div2.pack(side=tk.LEFT, padx=3)

        # 3. Compact 8-Color Palette
        self.color_buttons = {}
        for hex_col, col_name in PALETTE:
            is_sel = (self.active_color == hex_col)
            btn_col = tk.Button(
                self.toolbar_frame,
                bg=hex_col,
                activebackground=hex_col,
                width=2,
                height=1,
                relief=tk.SOLID if is_sel else tk.FLAT,
                bd=0,
                highlightthickness=2 if is_sel else 1,
                highlightbackground="#ffffff" if is_sel else "#334155",
                cursor="hand2",
                command=lambda c=hex_col: self.set_color(c)
            )
            btn_col.pack(side=tk.LEFT, padx=1)
            self.color_buttons[hex_col] = btn_col

        # Divider 3
        div3 = tk.Frame(self.toolbar_frame, width=1, height=20, bg="#334155")
        div3.pack(side=tk.LEFT, padx=3)

        # 4. Dynamic Size Indicator (Wheel Adjustable)
        size_box = tk.Frame(self.toolbar_frame, bg="#1e293b", padx=3, pady=1)
        size_box.pack(side=tk.LEFT, padx=1)
        self.lbl_size_val = tk.Label(
            size_box,
            text=f"{self.stroke_width}px",
            bg="#1e293b",
            fg="#38bdf8",
            font=("Microsoft YaHei", 8, "bold")
        )
        self.lbl_size_val.pack(side=tk.LEFT)
        lbl_hint_w = tk.Label(size_box, text="⇳", bg="#1e293b", fg="#64748b", font=("Segoe UI", 7))
        lbl_hint_w.pack(side=tk.LEFT, padx=(1, 0))

        # Divider 4
        div4 = tk.Frame(self.toolbar_frame, width=1, height=20, bg="#334155")
        div4.pack(side=tk.LEFT, padx=3)

        # 5. Compact Note Entry
        if self.note_var is None:
            self.note_var = tk.StringVar(value="")
        note_entry = tk.Entry(
            self.toolbar_frame,
            textvariable=self.note_var,
            width=12,
            bg="#1e293b",
            fg="#f8fafc",
            insertbackground="#38bdf8",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9)
        )
        note_entry.pack(side=tk.LEFT, padx=2, ipady=1)
        note_entry.bind("<Return>", lambda e: (self.on_enter_event(e), "break")[1])
        note_entry.bind("<KP_Enter>", lambda e: (self.on_enter_event(e), "break")[1])
        self._disable_button_takefocus(self.toolbar_frame)
        try:
            self.canvas.focus_set()
        except Exception:
            pass

        # Divider 5
        div5 = tk.Frame(self.toolbar_frame, width=1, height=20, bg="#334155")
        div5.pack(side=tk.LEFT, padx=3)

        # 6. Action Buttons (Copy, Save, Cancel)
        btn_copy = tk.Button(
            self.toolbar_frame,
            text="📋 复制",
            bg="#1e293b",
            fg="#38bdf8",
            activebackground="#0284c7",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9, "bold"),
            padx=5,
            pady=2,
            cursor="hand2",
            command=self.copy_to_clipboard
        )
        btn_copy.pack(side=tk.LEFT, padx=1)

        btn_ok = tk.Button(
            self.toolbar_frame,
            text="✔ 完成 (Enter)",
            bg="#0284c7",
            fg="#ffffff",
            activebackground="#0369a1",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9, "bold"),
            padx=6,
            pady=2,
            cursor="hand2",
            command=self.on_confirm_event
        )
        btn_ok.pack(side=tk.LEFT, padx=2)

        btn_cancel = tk.Button(
            self.toolbar_frame,
            text="✕ 取消",
            bg="#334155",
            fg="#cbd5e1",
            activebackground="#475569",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9),
            padx=4,
            pady=2,
            cursor="hand2",
            command=self.on_cancel_event
        )
        btn_cancel.pack(side=tk.LEFT, padx=1)

        # Position toolbar cleanly below the selection box
        self.toolbar_frame.update_idletasks()
        tb_w = self.toolbar_frame.winfo_reqwidth()
        tb_h = self.toolbar_frame.winfo_reqheight()

        v_left, v_top, v_width, v_height = get_virtual_screen_geometry()

        # Center or right-align beneath selection
        tb_x = x2 - tb_w
        if tb_x < v_left + 10:
            tb_x = x1
        tb_x = max(v_left + 10, min(tb_x, v_left + v_width - tb_w - 10))

        tb_y = y2 + 6
        if tb_y + tb_h > v_top + v_height - 10:
            tb_y = y1 - tb_h - 6
            if tb_y < v_top + 10:
                tb_y = y1 + 6

        self.canvas.create_window(tb_x, tb_y, window=self.toolbar_frame, anchor=tk.NW, tags="toolbar_hud")

    def get_annotated_image(self):
        x1, y1, x2, y2 = self.get_norm_coords()
        if (x2 - x1) <= 5 or (y2 - y1) <= 5:
            return None

        crop_img = self.full_image.crop((x1, y1, x2, y2)).convert("RGB")
        draw = ImageDraw.Draw(crop_img)

        for item in self.annotations:
            t = item["type"]
            color = item["color"]
            w = item.get("width", self.stroke_width)

            if t == "rect":
                p1, p2 = item["p1"], item["p2"]
                rx1, ry1 = p1[0] - x1, p1[1] - y1
                rx2, ry2 = p2[0] - x1, p2[1] - y1
                draw.rectangle([min(rx1, rx2), min(ry1, ry2), max(rx1, rx2), max(ry1, ry2)], outline=color, width=w)
            elif t == "oval":
                p1, p2 = item["p1"], item["p2"]
                rx1, ry1 = p1[0] - x1, p1[1] - y1
                rx2, ry2 = p2[0] - x1, p2[1] - y1
                draw.ellipse([min(rx1, rx2), min(ry1, ry2), max(rx1, rx2), max(ry1, ry2)], outline=color, width=w)
            elif t == "arrow":
                p1, p2 = item["p1"], item["p2"]
                start = (p1[0] - x1, p1[1] - y1)
                end = (p2[0] - x1, p2[1] - y1)
                draw_pil_arrow(draw, start, end, fill=color, width=w)
            elif t == "pen":
                pts = [(pt[0] - x1, pt[1] - y1) for pt in item["points"]]
                if len(pts) > 1:
                    draw.line(pts, fill=color, width=w, joint="curve")
                    r = w / 2
                    for pt in pts:
                        draw.ellipse([pt[0] - r, pt[1] - r, pt[0] + r, pt[1] + r], fill=color)
            elif t == "text":
                pos = (item["pos"][0] - x1, item["pos"][1] - y1)
                size = item.get("size", self.font_size)
                wrap_w = item.get("wrap_width", 0)
                draw_pil_text(draw, pos, item["text"], fill=color, size=size, max_width=wrap_w)

        return crop_img

    def copy_to_clipboard(self):
        if self.confirmed:
            return
        if self.current_text_entry:
            self.commit_text_entry()

        annotated_img = self.get_annotated_image()
        if not annotated_img:
            return

        self.confirmed = True
        copy_image_to_clipboard(annotated_img)
        logger.info("Annotated screenshot copied to clipboard.")
        self._close_overlay()

        if self.on_cancel:
            self.on_cancel()

    def on_double_click(self, event):
        if self.has_selection:
            hit_idx = self.find_text_annotation_at(event.x, event.y)
            if hit_idx is not None:
                self.reopen_text_editor(hit_idx)
                return
            self.on_confirm_event()

    def on_confirm_event(self, event=None):
        if self.confirmed:
            return
        if self.current_text_entry:
            self.commit_text_entry()

        annotated_img = self.get_annotated_image()
        if not annotated_img:
            return

        self.confirmed = True
        note = self.note_var.get().strip() if hasattr(self, "note_var") and self.note_var else ""
        self._close_overlay()

        if self.on_complete:
            self.on_complete(annotated_img, note)

    def on_enter_event(self, event=None):
        if self.confirmed:
            return "break"
        # Annotation text editor uses Enter as newline.
        if self.current_text_entry:
            return
        if self.has_selection:
            self.on_confirm_event(event)
        else:
            self._abort_snip()
        return "break"

    def on_key_press(self, event=None):
        if event is None or self.confirmed:
            return
        if event.keysym in ("Return", "KP_Enter", "ISO_Enter") or getattr(event, "keycode", None) in (13, 108, 0x0D):
            return self.on_enter_event(event)
        if event.keysym in ("Escape",) or getattr(event, "keycode", None) == 27:
            return self.on_cancel_event(event)

    def on_cancel_event(self, event=None):
        if self.confirmed:
            return
        if self.current_text_entry:
            self.cancel_text_entry()
            return
        if self.selected_text_index is not None:
            self.selected_text_index = None
            self.redraw_annotations()
            return
        self._abort_snip()
        return "break"

    def _focus_overlay(self):
        if self.confirmed or not self.root:
            return
        try:
            self.root.lift()
            self.root.focus_force()
            self.canvas.focus_set()
        except Exception:
            pass
        if sys.platform != "win32":
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            # Release Alt key in case Alt+Q left Windows in modal menu state
            user32.keybd_event(0x12, 0, 2, 0)

            w_id = self.root.winfo_id()
            top_hwnd = user32.GetAncestor(w_id, 2) or w_id

            user32.AllowSetForegroundWindow(-1)
            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd and fg_hwnd != top_hwnd:
                fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
                cur_thread = kernel32.GetCurrentThreadId()
                if fg_thread != cur_thread:
                    user32.AttachThreadInput(cur_thread, fg_thread, True)
                    user32.BringWindowToTop(top_hwnd)
                    user32.SetForegroundWindow(top_hwnd)
                    user32.SetFocus(top_hwnd)
                    user32.AttachThreadInput(cur_thread, fg_thread, False)
                else:
                    user32.BringWindowToTop(top_hwnd)
                    user32.SetForegroundWindow(top_hwnd)
                    user32.SetFocus(top_hwnd)
            else:
                user32.BringWindowToTop(top_hwnd)
                user32.SetForegroundWindow(top_hwnd)
                user32.SetFocus(top_hwnd)

            ctypes.windll.imm32.ImmAssociateContext(top_hwnd, 0)
            ctypes.windll.imm32.ImmAssociateContext(w_id, 0)
            canvas_hwnd = self.canvas.winfo_id()
            ctypes.windll.imm32.ImmAssociateContext(canvas_hwnd, 0)
        except Exception as e:
            logger.debug(f"Focus overlay notice: {e}")

    def _close_overlay(self):
        if getattr(self, "_global_listener", None):
            try:
                self._global_listener.stop()
            except Exception:
                pass
            self._global_listener = None
        for after_id in self._focus_after_ids:
            try:
                self.root.after_cancel(after_id)
            except Exception:
                pass
        self._focus_after_ids = []
        if self.current_text_entry:
            try:
                top = self.current_text_entry[0]
                self.current_text_entry = None
                self.current_text_entry_frame = None
                top.destroy()
            except Exception:
                self.current_text_entry = None
                self.current_text_entry_frame = None
        try:
            if self.root:
                self.root.grab_release()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        self._restore_global_hotkeys()

    def _restore_global_hotkeys(self):
        try:
            from core.hotkey_manager import hotkey_manager
            hotkey_manager.restart_listener()
        except Exception as e:
            logger.warning(f"Failed to restore hotkeys after snip: {e}")

    def _abort_snip(self):
        if self.confirmed:
            return
        self.confirmed = True
        self._close_overlay()
        if self.on_cancel:
            self.on_cancel()


def trigger_sniper(on_complete=None, on_cancel=None):
    """Triggers region snipping overlay in a daemon worker thread."""
    def _run():
        try:
            full_img = grab_fullscreen()
            overlay = SniperOverlay(full_img, on_complete=on_complete, on_cancel=on_cancel)
            overlay.start()
        except Exception as e:
            logger.error(f"Failed to launch sniper: {e}")
            if on_cancel:
                on_cancel()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
