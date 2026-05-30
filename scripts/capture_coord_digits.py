import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import keyboard

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capture_win32 import grab_client
from core.window import WindowBinder


WINDOW_TITLE_DEFAULT = "《新天龙八部》 0.08.0207 (原始一区:江湖梦)"


def crop_roi(hwnd: int, roi: tuple[int, int, int, int]):
    img = grab_client(hwnd)
    x1, y1, x2, y2 = roi
    return img[y1:y2, x1:x2]


def save_roi_image(img, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), img)


def main():
    parser = argparse.ArgumentParser(description="截取当前坐标区域，用于制作数字模板")
    parser.add_argument("--title", default=WINDOW_TITLE_DEFAULT, help="游戏窗口标题")
    parser.add_argument("--roi", default="894,33,948,46", help="坐标区域 ROI，格式 x1,y1,x2,y2")
    parser.add_argument("--output-dir", default="debug/coord_roi", help="输出目录")
    parser.add_argument("--prefix", default="coord_roi", help="文件名前缀")
    parser.add_argument("--hotkey", default="f6", help="截图热键")
    args = parser.parse_args()

    roi = tuple(int(v) for v in args.roi.split(","))
    if len(roi) != 4:
        raise RuntimeError("ROI must be x1,y1,x2,y2")

    binder = WindowBinder(args.title)
    hwnd = binder.ensure()

    output_dir = Path(args.output_dir)
    print("=" * 60)
    print("Current Coordinate Capture Tool")
    print("=" * 60)
    print(f"window: {args.title}")
    print(f"roi: {roi}")
    print(f"output: {output_dir.resolve()}")
    print(f"{args.hotkey.upper()} save | ESC exit")
    print("让右上角坐标稳定显示后按热键截图。")
    print("=" * 60)

    while True:
        if keyboard.is_pressed("esc"):
            print("[EXIT] user exit")
            break

        if keyboard.is_pressed(args.hotkey):
            hwnd = binder.ensure()
            crop = crop_roi(hwnd, roi)
            ts = time.strftime("%Y%m%d_%H%M%S")
            output_path = output_dir / f"{args.prefix}_{ts}.png"
            save_roi_image(crop, output_path)
            print(f"[SAVE] {output_path}")
            time.sleep(0.35)

        time.sleep(0.02)


if __name__ == "__main__":
    main()
