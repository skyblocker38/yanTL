# core/capture_win32.py
import time
import numpy as np
import win32gui
import win32ui
import win32con

def grab_client(hwnd: int, retries: int = 5) -> np.ndarray:
    """
    截取窗口客户区图像，返回 BGR np.ndarray (H,W,3)
    - 自动重试：应对窗口切换/尺寸瞬时为 0
    - 使用 GetDC(hwnd)：更贴合“客户区”
    """
    last_rect = None

    for _ in range(retries):
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        last_rect = (left, top, right, bottom)

        if w > 0 and h > 0:
            # 取客户区 DC（比 GetWindowDC 更稳）
            hwnd_dc = win32gui.GetDC(hwnd)
            mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
            save_dc = mfc_dc.CreateCompatibleDC()

            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bmp)

            save_dc.BitBlt((0, 0), (w, h), mfc_dc, (0, 0), win32con.SRCCOPY)

            bmpinfo = bmp.GetInfo()
            bmpstr = bmp.GetBitmapBits(True)

            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img = img.reshape((bmpinfo["bmHeight"], bmpinfo["bmWidth"], 4))
            img = img[:, :, :3]  # BGRA -> BGR

            # cleanup
            win32gui.DeleteObject(bmp.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

            return img

        # 客户区为 0：短暂等待后重试
        time.sleep(0.1)

    raise RuntimeError(f"窗口客户区尺寸异常（多次重试仍为 0）：client_rect={last_rect}")