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

def draw_pil_text(draw, pos, text, fill, size):
    """Draws text with contrast outline for clear legibility."""
    font = get_system_font(size=size, bold=True)
    x, y = pos
    outline_color = (0, 0, 0, 220) if fill != "#0f172a" and fill != "#000000" else (255, 255, 255, 220)
    for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)]:
        draw.text((x + ox, y + oy), text, fill=outline_color, font=font)
    draw.text((x, y), text, fill=fill, font=font)


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
        self.hud_timer = None

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

        self.canvas = tk.Canvas(self.root, highlightthickness=0, bg="black")
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
        self.canvas.bind("<ButtonPress-3>", self.on_cancel_event)
        self.canvas.bind("<Motion>", self.on_mouse_hover)
        
        # Mouse Wheel for dynamic stroke width and font size adjustment
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.root.bind("<MouseWheel>", self.on_mouse_wheel)

        # Keybindings
        self.root.bind("<Escape>", self.on_cancel_event)
        self.root.bind("<Return>", self.on_confirm_event)
        self.root.bind("<space>", self.on_space_event)
        self.root.bind("<Control-z>", lambda e: self.undo())
        self.root.bind("<Control-Z>", lambda e: self.undo())
        self.root.bind("<Control-y>", lambda e: self.redo())
        self.root.bind("<Control-Y>", lambda e: self.redo())
        self.root.bind("<Control-c>", lambda e: self.copy_to_clipboard())
        self.root.bind("<Control-C>", lambda e: self.copy_to_clipboard())

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

        self.root.lift()
        self.root.focus_force()
        self.root.mainloop()

    def show_initial_hint(self, width, height):
        hint_text = "🎯 拖拽鼠标选取截图区域 | 滚轮可调节线条粗细 | 右键或 Esc 退出"
        hx = width // 2
        hy = 36
        self.canvas.create_rectangle(
            hx - 220, hy - 14, hx + 220, hy + 14,
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

        # Update last drawn annotation in real-time if exists
        if self.annotations:
            last = self.annotations[-1]
            if last["type"] in ["rect", "oval", "arrow", "pen"]:
                last["width"] = self.stroke_width
            elif last["type"] == "text":
                last["size"] = self.font_size
            self.redraw_annotations()

        # Show floating HUD near mouse
        self.show_size_hud(event.x, event.y)

    def show_size_hud(self, x, y):
        if not self.canvas:
            return
        self.canvas.delete("size_hud")
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
        focused = self.root.focus_get()
        if isinstance(focused, tk.Entry) or isinstance(focused, tk.Text):
            return
        if self.has_selection:
            self.set_tool(tool_name)

    def on_space_event(self, event):
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
            if self.active_tool == "text":
                self.canvas.config(cursor="xterm")
            elif self.active_tool == "pen":
                self.canvas.config(cursor="pencil")
            else:
                self.canvas.config(cursor="cross")
        else:
            self.canvas.config(cursor="cross")

    def on_mouse_down(self, event):
        if self.current_text_entry:
            self.commit_text_entry()

        if self.has_selection:
            if self.is_inside_selection(event.x, event.y):
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
        if self.is_selecting:
            self.cur_x = event.x
            self.cur_y = event.y
            self.redraw_selection_view()
            return

        if self.is_drawing_tool:
            cx, cy = self.clamp_to_selection(event.x, event.y)
            self.render_temp_drawing(cx, cy)

    def on_mouse_up(self, event):
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
            elif self.active_tool == "pen":
                if len(self.pen_points) > 1:
                    self.annotations.append({
                        "type": "pen",
                        "points": list(self.pen_points),
                        "color": color,
                        "width": width
                    })
                    self.redo_stack.clear()

            self.canvas.delete("temp_draw")
            self.redraw_annotations()

    def clear_canvas_elements(self):
        self.canvas.delete("overlay_crop")
        self.canvas.delete("selection_box")
        self.canvas.delete("annotation")
        self.canvas.delete("temp_draw")
        self.canvas.delete("hud")

    def reset_selection(self):
        self.has_selection = False
        self.is_selecting = False
        self.is_drawing_tool = False
        self.annotations.clear()
        self.redo_stack.clear()
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
                for ox, oy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                    self.canvas.create_text(
                        pos[0] + ox, pos[1] + oy,
                        text=text,
                        fill="#000000" if color != "#0f172a" else "#ffffff",
                        font=("Microsoft YaHei", font_size, "bold"),
                        anchor=tk.NW,
                        tags="annotation"
                    )
                self.canvas.create_text(
                    pos[0], pos[1],
                    text=text,
                    fill=color,
                    font=("Microsoft YaHei", font_size, "bold"),
                    anchor=tk.NW,
                    tags="annotation"
                )

    def open_text_editor(self, x, y):
        font_size = self.font_size
        color = self.active_color

        entry = tk.Entry(
            self.canvas,
            bg="#0f172a",
            fg=color,
            insertbackground=color,
            relief=tk.SOLID,
            bd=1,
            highlightthickness=1,
            highlightbackground="#38bdf8",
            highlightcolor="#38bdf8",
            font=("Microsoft YaHei", font_size, "bold")
        )
        self.current_text_entry = (entry, (x, y), font_size, color)
        self.canvas.create_window(x, y, window=entry, anchor=tk.NW, tags="text_editor_win")
        entry.focus_set()

        entry.bind("<Return>", lambda e: self.commit_text_entry())
        entry.bind("<Escape>", lambda e: self.cancel_text_entry())
        entry.bind("<FocusOut>", lambda e: self.commit_text_entry())

    def commit_text_entry(self):
        if not self.current_text_entry:
            return
        entry, pos, font_size, color = self.current_text_entry
        text = entry.get().strip()
        self.current_text_entry = None
        self.canvas.delete("text_editor_win")
        entry.destroy()

        if text:
            self.annotations.append({
                "type": "text",
                "pos": pos,
                "text": text,
                "color": color,
                "size": font_size
            })
            self.redo_stack.clear()
            self.redraw_annotations()

    def cancel_text_entry(self):
        if not self.current_text_entry:
            return
        entry, _, _, _ = self.current_text_entry
        self.current_text_entry = None
        self.canvas.delete("text_editor_win")
        entry.destroy()

    def undo(self):
        if self.current_text_entry:
            self.cancel_text_entry()
            return
        if self.annotations:
            item = self.annotations.pop()
            self.redo_stack.append(item)
            self.redraw_annotations()

    def redo(self):
        if self.redo_stack:
            item = self.redo_stack.pop()
            self.annotations.append(item)
            self.redraw_annotations()

    def clear_annotations(self):
        if self.annotations:
            self.annotations.clear()
            self.redo_stack.clear()
            self.redraw_annotations()

    def set_tool(self, tool_name):
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

    def destroy_toolbar(self):
        if self.toolbar_frame:
            try:
                self.toolbar_frame.destroy()
            except Exception:
                pass
            self.toolbar_frame = None
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
        note_entry.bind("<Return>", lambda e: self.on_confirm_event())

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
            text="✕",
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
                draw_pil_text(draw, pos, item["text"], fill=color, size=size)

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

        try:
            self.root.destroy()
        except Exception:
            pass

        if self.on_cancel:
            self.on_cancel()

    def on_double_click(self, event):
        if self.has_selection:
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

        try:
            self.root.destroy()
        except Exception:
            pass

        if self.on_complete:
            self.on_complete(annotated_img, note)

    def on_cancel_event(self, event=None):
        if self.confirmed:
            return
        self.confirmed = True
        try:
            self.root.destroy()
        except Exception:
            pass
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
