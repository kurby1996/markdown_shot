import os
import sys
import ctypes
from PIL import Image, ImageGrab
import logging

logger = logging.getLogger("screen_grab")

_dpi_set = False

def set_dpi_aware():
    global _dpi_set
    if _dpi_set:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor DPI aware
        _dpi_set = True
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _dpi_set = True
        except Exception as e:
            logger.warning(f"Could not set DPI awareness: {e}")

def ensure_desktop_access():
    if sys.platform != "win32":
        return
    try:
        import win32service, win32con
        hwinsta = win32service.OpenWindowStation('winsta0', False, win32con.MAXIMUM_ALLOWED)
        hwinsta.SetProcessWindowStation()
        hdesk = win32service.OpenDesktop('default', 0, False, win32con.MAXIMUM_ALLOWED)
        hdesk.SetThreadDesktop()
    except Exception as e:
        logger.debug(f"ensure_desktop_access notice: {e}")

def get_virtual_screen_geometry():
    set_dpi_aware()
    if sys.platform == "win32":
        import win32api, win32con
        left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        return (left, top, width, height)
    return (0, 0, 1920, 1080)

def grab_fullscreen():
    """Captures the full virtual screen."""
    set_dpi_aware()
    ensure_desktop_access()
    try:
        im = ImageGrab.grab(all_screens=True)
        return im
    except Exception as e:
        logger.error(f"ImageGrab failed: {e}, attempting fallback...")
        try:
            import mss
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                sct_img = sct.grab(monitor)
                return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as e2:
            logger.error(f"MSS grab failed: {e2}")
            raise RuntimeError(f"Screen grab failed: {e}")

def grab_active_window():
    """Captures the currently active foreground window."""
    set_dpi_aware()
    ensure_desktop_access()
    if sys.platform != "win32":
        return grab_fullscreen()

    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or hwnd == win32gui.GetDesktopWindow():
            return grab_fullscreen()

        rect = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = rect
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            return grab_fullscreen()

        # Grab full screen and crop window rect
        full_img = grab_fullscreen()
        v_left, v_top, v_width, v_height = get_virtual_screen_geometry()

        # Adjust coordinates relative to full virtual screen image
        crop_x1 = max(0, left - v_left)
        crop_y1 = max(0, top - v_top)
        crop_x2 = min(full_img.width, right - v_left)
        crop_y2 = min(full_img.height, bottom - v_top)

        if crop_x2 <= crop_x1 or crop_y2 <= crop_y1:
            return full_img

        return full_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    except Exception as e:
        logger.error(f"grab_active_window failed: {e}")
        return grab_fullscreen()

def grab_clipboard_image():
    """Grabs an image from system clipboard if available."""
    set_dpi_aware()
    ensure_desktop_access()
    try:
        clip = ImageGrab.grabclipboard()
        if isinstance(clip, Image.Image):
            return clip
        elif isinstance(clip, list) and len(clip) > 0:
            # File list copied
            for p in clip:
                if isinstance(p, str) and os.path.exists(p) and p.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.webp')):
                    return Image.open(p)
    except Exception as e:
        logger.debug(f"grab_clipboard_image notice: {e}")
    return None

def copy_image_to_clipboard(pil_image):
    """Copies a PIL Image directly to the Windows clipboard."""
    if sys.platform != "win32":
        return False
    try:
        import io
        import win32clipboard
        import win32con
        output = io.BytesIO()
        pil_image.convert("RGB").save(output, "BMP")
        data = output.getvalue()[14:]  # BMP header is 14 bytes; CF_DIB requires DIB header without BMP file header
        output.close()

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_DIB, data)
        win32clipboard.CloseClipboard()
        return True
    except Exception as e:
        logger.error(f"Failed to copy image to clipboard: {e}")
        return False

