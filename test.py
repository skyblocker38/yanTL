import pygetwindow as gw

for w in gw.getAllTitles():
    if w.strip():
        print(w)


# click_auto_move_test.py
# import time
# import ctypes

# import keyboard
# import win32gui
# import win32con
# import win32api

# # ====== 改这里 ======
# WINDOW_TITLE = "《新天龙八部》 0.07.7309 (原始一区:江湖梦)"
# AUTO_MOVE_XY = (958, 225)  # 你的 clicks.auto_move
# # ====================

# def my_time_sleep(sleep_time: float, flag: bool):
#     t = time.time()
#     while flag:
#         if time.time() - t > sleep_time:
#             return 0

# def click_client(hwnd: int, x: int, y: int, double: bool = False, gap=0.08):
#     lp = win32api.MAKELONG(x, y)
#     win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
#     my_time_sleep(0.1, True)
#     win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)
#     if double:
#         time.sleep(gap)
#         win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, 0, lp)
#         time.sleep(0.1)
#         win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)

# def main():
#     # DPI aware（避免 Windows 缩放导致坐标漂）
#     ctypes.windll.user32.SetProcessDPIAware()

#     hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
#     if hwnd == 0:
#         raise RuntimeError(f"找不到窗口（标题需完全一致）: {WINDOW_TITLE}")

#     print(f"绑定窗口 hwnd={hwnd}")
#     l, t, r, b = win32gui.GetClientRect(hwnd)
#     print(f"client_size={(r-l)}x{(b-t)}")
#     print(f"将测试点击 auto_move at client={AUTO_MOVE_XY}")
#     print("把游戏保持打开（可在后台），按 F6 点击一次；按 ESC 退出")

#     last = 0.0
#     while True:
#         if keyboard.is_pressed("esc"):
#             break

#         if keyboard.is_pressed("f6") and time.time() - last > 0.25:
#             last = time.time()

#             # 如果最小化，先恢复（否则客户区可能异常）
#             if win32gui.IsIconic(hwnd):
#                 win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
#                 time.sleep(0.2)

#             l, t, r, b = win32gui.GetClientRect(hwnd)
#             w, h = (r-l), (b-t)
#             x, y = AUTO_MOVE_XY
#             print(f"[F6] click auto_move client=({x},{y})  client_size=({w}x{h})")
#             click_client(hwnd, x, y)

#         time.sleep(0.01)

#     print("退出")

# if __name__ == "__main__":
#     main()