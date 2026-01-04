# core/window.py
import time
import win32gui
import win32con

class WindowBinder:
    def __init__(self, title: str):
        self.title = title
        self.hwnd: int | None = None

    def bind_exact(self) -> int:
        hwnd = win32gui.FindWindow(None, self.title)
        if hwnd == 0:
            raise RuntimeError(f"找不到窗口（标题需完全一致）: {self.title}")
        self.hwnd = hwnd
        return hwnd

    def ensure(self, retry_interval=1.0) -> int:
        if self.hwnd is not None and win32gui.IsWindow(self.hwnd):
            hwnd = self.hwnd
        else:
            hwnd = self.bind_exact()

        # 如果最小化，先恢复（否则客户区可能是 0）
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)

        return hwnd