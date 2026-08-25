import sys
import os
import time
import threading
import tkinter as tk
from PIL import Image, ImageTk, ImageEnhance
import logging

from core.screen_grab import grab_fullscreen, get_virtual_screen_geometry, set_dpi_aware

logger = logging.getLogger("sniper")

class SniperOverlay:
    def __init__(self, full_image, on_complete=None, on_cancel=None):
        self.full_image = full_image
        self.on_complete = on_complete
        self.on_cancel = on_cancel
        self.root = None
        self.canvas = None
        self.start_x = None
        self.start_y = None
        self.cur_x = None
        self.cur_y = None
        self.is_dragging = False
        self.has_selection = False
        self.confirmed = False

        # Prepare darkened version for overlay mask
        enhancer = ImageEnhance.Brightness(self.full_image)
        self.dark_image = enhancer.enhance(0.4)

        self.tk_dark_img = None
        self.tk_orig_img = None
        self.note_entry = None
        self.toolbar_frame = None

    def start(self):
        set_dpi_aware()
        self.root = tk.Tk()
        self.root.title("Snipper")
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

        # Events
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.canvas.bind("<Double-Button-1>", self.on_double_click)
        self.canvas.bind("<ButtonPress-3>", self.on_cancel_event) # Right click to cancel
        self.root.bind("<Escape>", self.on_cancel_event)
        self.root.bind("<Return>", self.on_confirm_event)
        self.root.bind("<space>", self.on_confirm_event)

        # Force focus
        self.root.lift()
        self.root.focus_force()
        self.root.mainloop()

    def get_norm_coords(self):
        if self.start_x is None or self.cur_x is None:
            return 0, 0, 0, 0
        x1 = min(self.start_x, self.cur_x)
        y1 = min(self.start_y, self.cur_y)
        x2 = max(self.start_x, self.cur_x)
        y2 = max(self.start_y, self.cur_y)
        return int(x1), int(y1), int(x2), int(y2)

    def on_mouse_down(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.cur_x = event.x
        self.cur_y = event.y
        self.is_dragging = True
        self.has_selection = False
        self.canvas.delete("overlay_crop")
        self.canvas.delete("selection_box")
        self.canvas.delete("hud")
        if self.toolbar_frame:
            self.toolbar_frame.destroy()
            self.toolbar_frame = None

    def on_mouse_drag(self, event):
        if not self.is_dragging:
            return
        self.cur_x = event.x
        self.cur_y = event.y
        self.redraw_selection()

    def on_mouse_up(self, event):
        if not self.is_dragging:
            return
        self.cur_x = event.x
        self.cur_y = event.y
        self.is_dragging = False
        x1, y1, x2, y2 = self.get_norm_coords()
        if (x2 - x1) > 10 and (y2 - y1) > 10:
            self.has_selection = True
            self.redraw_selection()
            self.show_toolbar(x1, y1, x2, y2)
        else:
            self.has_selection = False
            self.canvas.delete("overlay_crop")
            self.canvas.delete("selection_box")
            self.canvas.delete("hud")

    def redraw_selection(self):
        x1, y1, x2, y2 = self.get_norm_coords()
        w = x2 - x1
        h = y2 - y1

        self.canvas.delete("overlay_crop")
        self.canvas.delete("selection_box")
        self.canvas.delete("hud")

        if w <= 0 or h <= 0:
            return

        # Crop clear area from original image and render on top
        try:
            cropped = self.full_image.crop((x1, y1, x2, y2))
            self.tk_orig_img = ImageTk.PhotoImage(cropped)
            self.canvas.create_image(x1, y1, image=self.tk_orig_img, anchor=tk.NW, tags="overlay_crop")
        except Exception as e:
            logger.error(f"Error cropping clear area: {e}")

        # Border rectangle
        self.canvas.create_rectangle(
            x1, y1, x2, y2,
            outline="#38bdf8",
            width=2,
            tags="selection_box"
        )

        # Dimension badge
        badge_text = f" {w} × {h} px "
        badge_y = y1 - 24 if y1 >= 30 else y1 + 6
        badge_x = x1 + 4
        self.canvas.create_rectangle(
            badge_x, badge_y, badge_x + len(badge_text) * 8 + 10, badge_y + 20,
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

    def show_toolbar(self, x1, y1, x2, y2):
        if self.toolbar_frame:
            self.toolbar_frame.destroy()

        self.toolbar_frame = tk.Frame(self.canvas, bg="#0f172a", bd=1, relief=tk.SOLID, padx=6, pady=4)
        
        # Note Entry (Optional inline note)
        self.note_var = tk.StringVar(value="")
        note_entry = tk.Entry(
            self.toolbar_frame,
            textvariable=self.note_var,
            width=20,
            bg="#1e293b",
            fg="#f8fafc",
            insertbackground="#38bdf8",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9)
        )
        note_entry.insert(0, "")
        note_entry.pack(side=tk.LEFT, padx=(2, 6), ipady=2)
        note_entry.bind("<Return>", lambda e: self.on_confirm_event())

        # Placeholder label
        lbl_hint = tk.Label(self.toolbar_frame, text="💬备注:", bg="#0f172a", fg="#94a3b8", font=("Microsoft YaHei", 8))
        lbl_hint.pack(side=tk.LEFT, padx=(0, 2))

        # Confirm Button
        btn_ok = tk.Button(
            self.toolbar_frame,
            text="✔ 保存追加 (Enter)",
            bg="#0284c7",
            fg="white",
            activebackground="#0369a1",
            activeforeground="white",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9, "bold"),
            padx=8,
            pady=2,
            command=self.on_confirm_event,
            cursor="hand2"
        )
        btn_ok.pack(side=tk.LEFT, padx=3)

        # Cancel Button
        btn_cancel = tk.Button(
            self.toolbar_frame,
            text="✕ 取消 (Esc)",
            bg="#334155",
            fg="#cbd5e1",
            activebackground="#475569",
            activeforeground="white",
            relief=tk.FLAT,
            font=("Microsoft YaHei", 9),
            padx=6,
            pady=2,
            command=self.on_cancel_event,
            cursor="hand2"
        )
        btn_cancel.pack(side=tk.LEFT, padx=2)

        # Position toolbar below or above selection
        tb_w = 400
        tb_h = 38
        tb_x = x2 - tb_w
        if tb_x < 10:
            tb_x = x1

        tb_y = y2 + 8
        if tb_y + tb_h > self.canvas.winfo_height() - 10:
            tb_y = y1 - tb_h - 8
            if tb_y < 10:
                tb_y = y1 + 10

        self.canvas.create_window(tb_x, tb_y, window=self.toolbar_frame, anchor=tk.NW, tags="hud")

    def on_double_click(self, event):
        if self.has_selection:
            self.on_confirm_event()

    def on_confirm_event(self, event=None):
        if self.confirmed:
            return
        x1, y1, x2, y2 = self.get_norm_coords()
        if (x2 - x1) <= 5 or (y2 - y1) <= 5:
            # No valid selection
            return

        self.confirmed = True
        cropped_image = self.full_image.crop((x1, y1, x2, y2))
        note = self.note_var.get().strip() if hasattr(self, "note_var") else ""

        try:
            self.root.destroy()
        except Exception:
            pass

        if self.on_complete:
            self.on_complete(cropped_image, note)

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
    """
    Triggers region snipping overlay.
    Must be called from a GUI worker thread or main thread.
    """
    def _run():
        try:
            # Capture freeze frame first
            full_img = grab_fullscreen()
            overlay = SniperOverlay(full_img, on_complete=on_complete, on_cancel=on_cancel)
            overlay.start()
        except Exception as e:
            logger.error(f"Failed to launch sniper: {e}")
            if on_cancel:
                on_cancel()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
