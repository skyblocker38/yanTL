import time
import keyboard
import win32gui

WINDOW_TITLE = "《新天龙八部》 0.07.7507 (原始一区:江湖梦)"  # 必须完全匹配
# WINDOW_TITLE = "《新天龙八部》 0.07.7507 (怀旧二区:天下第一)"  # 必须完全匹配

def get_hwnd(title: str) -> int:
    hwnd = win32gui.FindWindow(None, title)
    if hwnd == 0:
        raise RuntimeError(f"找不到窗口: {title}")
    return hwnd

def main():
    hwnd = get_hwnd(WINDOW_TITLE)
    print(f"已绑定窗口 hwnd={hwnd}")
    print("把鼠标移到目标位置，按 F6 打印坐标；按 ESC 退出")

    while True:
        if keyboard.is_pressed("esc"):
            break

        if keyboard.is_pressed("f6"):
            # 取鼠标屏幕坐标
            sx, sy = win32gui.GetCursorPos()

            # 转换为客户区坐标
            cx, cy = win32gui.ScreenToClient(hwnd, (sx, sy))

            # 顺便打印窗口客户区尺寸，方便 sanity check
            l, t, r, b = win32gui.GetClientRect(hwnd)
            w, h = r - l, b - t

            print(f"[F6] screen=({sx},{sy})  client=({cx},{cy})  client_size=({w}x{h})")
            time.sleep(0.25)  # 防止长按连发

        time.sleep(0.01)

if __name__ == "__main__":
    main()