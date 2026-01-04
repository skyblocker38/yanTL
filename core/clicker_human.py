import time
import random
import ctypes
import win32gui
import win32con
import win32process

# DPI aware：避免缩放导致坐标漂
ctypes.windll.user32.SetProcessDPIAware()
user32 = ctypes.windll.user32

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP   = 0x0004

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _anonymous_ = ("i",)
    _fields_ = [("type", ctypes.c_ulong), ("i", _I)]

def _send_left_down():
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def _send_left_up():
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

def _click_hold(hold: float):
    _send_left_down()
    time.sleep(hold)
    _send_left_up()

def _move_mouse_like_human(sx: int, sy: int, steps: int, total_time: float):
    x0, y0 = win32gui.GetCursorPos()
    for i in range(1, steps + 1):
        t = i / steps
        x = int(x0 + (sx - x0) * t)
        y = int(y0 + (sy - y0) * t)
        user32.SetCursorPos(x, y)
        time.sleep(total_time / steps)

class ForegroundBlock:
    """
    进入：尽力把目标窗口激活到前台，并等待确认成功
    退出：不恢复原前台窗口（按你的需求）
    """
    def __init__(self, hwnd_target: int, max_wait: float = 0.8, raise_on_fail: bool = False):
        self.hwnd_target = hwnd_target
        self.max_wait = max_wait
        self.raise_on_fail = raise_on_fail
        self.activated = False

    def _force_foreground(self):
        # 1) 若最小化先恢复
        if win32gui.IsIconic(self.hwnd_target):
            win32gui.ShowWindow(self.hwnd_target, win32con.SW_RESTORE)
            time.sleep(0.05)

        # 2) 确保可见
        win32gui.ShowWindow(self.hwnd_target, win32con.SW_SHOW)

        # 3) 尝试置顶/激活
        win32gui.BringWindowToTop(self.hwnd_target)
        try:
            win32gui.SetActiveWindow(self.hwnd_target)
        except Exception:
            pass

        # 4) 强力前台：AttachThreadInput + SetForegroundWindow
        try:
            fg = win32gui.GetForegroundWindow()
            cur_tid = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
            tgt_tid = win32process.GetWindowThreadProcessId(self.hwnd_target)[0]

            if cur_tid and tgt_tid and cur_tid != tgt_tid:
                user32.AttachThreadInput(cur_tid, tgt_tid, True)

            try:
                win32gui.SetForegroundWindow(self.hwnd_target)
            except Exception:
                pass

            try:
                user32.SetFocus(self.hwnd_target)
            except Exception:
                pass

        finally:
            # detach
            try:
                if cur_tid and tgt_tid and cur_tid != tgt_tid:
                    user32.AttachThreadInput(cur_tid, tgt_tid, False)
            except Exception:
                pass

        # 5) 兜底：TopMost 闪一下再取消（常用技巧）
        try:
            win32gui.SetWindowPos(
                self.hwnd_target, win32con.HWND_TOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            )
            win32gui.SetWindowPos(
                self.hwnd_target, win32con.HWND_NOTOPMOST,
                0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            )
        except Exception:
            pass

    def __enter__(self):
        # 多次尝试直到真的成为前台
        t0 = time.time()
        while time.time() - t0 < self.max_wait:
            self._force_foreground()
            if win32gui.GetForegroundWindow() == self.hwnd_target:
                self.activated = True
                break
            time.sleep(0.03)

        # 人会停顿一下再操作（也给UI一点时间）
        time.sleep(random.uniform(0.03, 0.10))

        if not self.activated and self.raise_on_fail:
            raise RuntimeError("无法将目标窗口激活到前台（可能被系统前台限制拦截）")

        return self

    def __exit__(self, exc_type, exc, tb):
        # 不恢复原窗口
        return False

class HumanClicker:
    """
    人性化点击器：client 坐标 -> screen 坐标 -> 轨迹移动 -> hover -> 按住 -> 抬起
    """
    def __init__(
        self,
        move_steps=(10, 14),
        move_time=(0.15, 0.28),
        hover=(0.04, 0.10),
        hold_mean=0.10,
        hold_jitter=0.02,
        gap=(0.08, 0.18),
    ):
        self.move_steps = move_steps
        self.move_time = move_time
        self.hover = hover
        self.hold_mean = hold_mean
        self.hold_jitter = hold_jitter
        self.gap = gap

    def click(self, hwnd: int, cx: int, cy: int, times: int = 1, long_hold: float | None = None):
        sx, sy = win32gui.ClientToScreen(hwnd, (cx, cy))

        steps = random.randint(*self.move_steps)
        total_time = random.uniform(*self.move_time)
        _move_mouse_like_human(int(sx), int(sy), steps=steps, total_time=total_time)

        time.sleep(random.uniform(*self.hover))

        for i in range(times):
            if long_hold is None:
                hold = max(0.03, random.gauss(self.hold_mean, self.hold_jitter))
            else:
                hold = long_hold
            _click_hold(hold)

            if i != times - 1:
                time.sleep(random.uniform(*self.gap))