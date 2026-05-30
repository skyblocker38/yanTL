import time
import win32api
import win32con
import ctypes
from ctypes import wintypes

# 定义 SendInput 所需的结构体
LONG = ctypes.c_long
DWORD = ctypes.c_ulong
ULONG_PTR = ctypes.POINTER(DWORD)
WORD = ctypes.c_ushort

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", DWORD), ("union", _INPUT_UNION)]

# 常量
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008


def to_vk(key: str | int) -> int:
    """支持 '1'/'A'/'space'/'esc' 等，或直接传 VK int。"""
    if isinstance(key, int):
        return key

    k = key.lower()
    if len(k) == 1:
        return ord(k.upper())

    mapping = {
        "space": win32con.VK_SPACE,
        "enter": win32con.VK_RETURN,
        "esc": win32con.VK_ESCAPE,
        "tab": win32con.VK_TAB,
        "shift": win32con.VK_SHIFT,
        "ctrl": win32con.VK_CONTROL,
        "alt": win32con.VK_MENU,
        "up": win32con.VK_UP,
        "down": win32con.VK_DOWN,
        "left": win32con.VK_LEFT,
        "right": win32con.VK_RIGHT,
        "f1": win32con.VK_F1,
        "f2": win32con.VK_F2,
        "f3": win32con.VK_F3,
        "f4": win32con.VK_F4,
        "f5": win32con.VK_F5,
        "f6": win32con.VK_F6,
        "f7": win32con.VK_F7,
        "f8": win32con.VK_F8,
        "f9": win32con.VK_F9,
        "f10": win32con.VK_F10,
        "f11": win32con.VK_F11,
        "f12": win32con.VK_F12,
    }
    if k not in mapping:
        raise ValueError(f"未知按键名: {key}")
    return mapping[k]


class InputController:
    """后台输入：向指定 hwnd 投递按键消息。"""

    def press(self, hwnd: int, key: str | int, hold: float = 0.05):
        vk = to_vk(key)
        scan_code = win32api.MapVirtualKey(vk, 0)
        lparam_down = (scan_code << 16) | 1
        lparam_up = (scan_code << 16) | 0xC0000001
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, lparam_down)
        time.sleep(hold)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, lparam_up)

    def press_combo(self, hwnd: int, key: str | int, modifiers: list = None, hold: float = 0.05):
        """按下组合键，使用 SendInput（全局输入，会更新系统键盘状态）"""
        modifiers = modifiers or []
        mod_vks = [to_vk(m) for m in modifiers]
        key_vk = to_vk(key)
        
        # 使用 SendInput 发送按键
        inputs = []
        
        # 按下修饰键
        for mod_vk in mod_vks:
            ki = KEYBDINPUT(mod_vk, 0, 0, 0, None)
            inp = INPUT(INPUT_KEYBOARD, _INPUT_UNION(ki=ki))
            inputs.append(inp)
        
        # 按下主键
        ki = KEYBDINPUT(key_vk, 0, 0, 0, None)
        inp = INPUT(INPUT_KEYBOARD, _INPUT_UNION(ki=ki))
        inputs.append(inp)
        
        # 发送按下事件
        arr = (INPUT * len(inputs))(*inputs)
        ctypes.windll.user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))
        time.sleep(hold)
        
        # 释放按键（主键 + 修饰键逆序）
        inputs = []
        
        # 释放主键
        ki = KEYBDINPUT(key_vk, 0, KEYEVENTF_KEYUP, 0, None)
        inp = INPUT(INPUT_KEYBOARD, _INPUT_UNION(ki=ki))
        inputs.append(inp)
        
        # 释放修饰键
        for mod_vk in reversed(mod_vks):
            ki = KEYBDINPUT(mod_vk, 0, KEYEVENTF_KEYUP, 0, None)
            inp = INPUT(INPUT_KEYBOARD, _INPUT_UNION(ki=ki))
            inputs.append(inp)
        
        # 发送释放事件
        arr = (INPUT * len(inputs))(*inputs)
        ctypes.windll.user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))

    def key_down(self, hwnd: int, key: str | int):
        vk = to_vk(key)
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)

    def key_up(self, hwnd: int, key: str | int):
        vk = to_vk(key)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)

    def type_text(self, hwnd: int, text: str, gap: float = 0.01):
        """
        用 WM_CHAR 输入文本（稳定，不会按键连发）
        """
        for ch in text:
            win32api.PostMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
            time.sleep(gap)

    def key_press(self, hwnd: int, vk_name: str, hold: float = 0.02):
        """
        如果你已经有 press() 就不用这个；这里只是示意。
        """
        self.press(hwnd, vk_name, hold=hold)