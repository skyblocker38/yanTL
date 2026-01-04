import time
import win32api
import win32con


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
    }
    if k not in mapping:
        raise ValueError(f"未知按键名: {key}")
    return mapping[k]


class InputController:
    """后台输入：向指定 hwnd 投递按键消息。"""

    def press(self, hwnd: int, key: str | int, hold: float = 0.05):
        vk = to_vk(key)
        win32api.PostMessage(hwnd, win32con.WM_KEYDOWN, vk, 0)
        time.sleep(hold)
        win32api.PostMessage(hwnd, win32con.WM_KEYUP, vk, 0)

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