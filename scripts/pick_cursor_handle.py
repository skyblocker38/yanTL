import argparse
import ctypes
import threading
import time
from ctypes import wintypes

import keyboard


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", wintypes.POINT),
    ]


def read_cursor():
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)
    if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
        return 0, (0, 0)
    return int(info.hCursor or 0), (int(info.ptScreenPos.x), int(info.ptScreenPos.y))


def main():
    parser = argparse.ArgumentParser(description="Read the current Windows cursor handle")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Print every handle change in addition to F6 samples",
    )
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()

    stop = threading.Event()

    def sample():
        handle, point = read_cursor()
        print(f"[F6] handle={handle} hex={handle:#x} screen={point}")

    keyboard.add_hotkey("f6", sample)
    keyboard.add_hotkey("f9", stop.set)
    print("[*] Put the cursor on normal ground and press F6, then on the herb and press F6")
    print("[*] Press F9 to exit")

    last_handle = None
    try:
        while not stop.is_set():
            if args.watch:
                handle, point = read_cursor()
                if handle != last_handle:
                    print(f"[CHANGE] handle={handle} hex={handle:#x} screen={point}")
                    last_handle = handle
            time.sleep(max(0.01, args.interval))
    finally:
        keyboard.unhook_all_hotkeys()


if __name__ == "__main__":
    main()
