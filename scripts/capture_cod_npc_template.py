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


def save_center_crop(hwnd: int, width: int, height: int, output_dir: str, prefix: str):
    img = grab_client(hwnd)
    img_h, img_w = img.shape[:2]

    cx = img_w // 2
    cy = img_h // 2

    x1 = max(0, cx - width // 2)
    y1 = max(0, cy - height // 2)
    x2 = min(img_w, x1 + width)
    y2 = min(img_h, y1 + height)

    crop = img[y1:y2, x1:x2]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{prefix}_{ts}.png"
    cv2.imwrite(str(path), crop)

    print(f"[SAVE] {path}")
    print(f"[ROI] center=({cx},{cy}) rect=({x1},{y1},{x2},{y2}) size={x2-x1}x{y2-y1}")


def save_offset_crop(hwnd: int, width: int, height: int, offset_x: int, offset_y: int, output_dir: str, prefix: str):
    img = grab_client(hwnd)
    img_h, img_w = img.shape[:2]

    base_cx = img_w // 2
    base_cy = img_h // 2
    cx = base_cx + offset_x
    cy = base_cy + offset_y

    x1 = max(0, cx - width // 2)
    y1 = max(0, cy - height // 2)
    x2 = min(img_w, x1 + width)
    y2 = min(img_h, y1 + height)

    crop = img[y1:y2, x1:x2]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"{prefix}_{ts}.png"
    cv2.imwrite(str(path), crop)

    print(f"[SAVE] {path}")
    print(
        f"[ROI] screen_center=({base_cx},{base_cy}) "
        f"target_center=({cx},{cy}) offset=({offset_x},{offset_y}) "
        f"rect=({x1},{y1},{x2},{y2}) size={x2-x1}x{y2-y1}"
    )


def main():
    parser = argparse.ArgumentParser(description="固定尺寸截取屏幕中心附近的造反恶贼名字模板")
    parser.add_argument("--title", default=WINDOW_TITLE_DEFAULT, help="游戏窗口标题")
    parser.add_argument("--width", type=int, default=160, help="截取宽度，默认 160")
    parser.add_argument("--height", type=int, default=50, help="截取高度，默认 50")
    parser.add_argument("--output-dir", default="templates", help="输出目录，默认 templates")
    parser.add_argument("--prefix", default="cod_npc", help="文件名前缀，默认 cod_npc")
    parser.add_argument("--hotkey", default="f6", help="截图热键，默认 F6")
    parser.add_argument("--offset-x", type=int, default=140, help="相对屏幕中心的水平偏移，向右为正，默认 140")
    parser.add_argument("--offset-y", type=int, default=-120, help="相对屏幕中心的垂直偏移，向下为正，默认 -120")
    args = parser.parse_args()

    binder = WindowBinder(args.title)
    hwnd = binder.ensure()

    print("=" * 60)
    print("造反恶贼模板截取工具")
    print("=" * 60)
    print(f"窗口: {args.title}")
    print(f"截图尺寸: {args.width}x{args.height}")
    print(f"偏移: ({args.offset_x},{args.offset_y})")
    print(f"输出目录: {Path(args.output_dir).resolve()}")
    print(f"热键: {args.hotkey.upper()} 保存截图")
    print("退出: ESC")
    print("-" * 60)
    print("使用方法: 让“造反恶贼”四个字尽量出现在屏幕中心，然后按热键截图。")
    print("=" * 60)

    while True:
        if keyboard.is_pressed("esc"):
            print("[EXIT] 用户退出")
            break

        if keyboard.is_pressed(args.hotkey):
            hwnd = binder.ensure()
            save_offset_crop(
                hwnd,
                args.width,
                args.height,
                args.offset_x,
                args.offset_y,
                args.output_dir,
                args.prefix,
            )
            time.sleep(0.35)

        time.sleep(0.02)


if __name__ == "__main__":
    main()
