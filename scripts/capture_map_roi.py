"""
截取地图ROI区域的脚本
用于调试和制作地图模板

使用方法:
    python scripts/capture_map_roi.py --title "游戏窗口标题"
    
    脚本会每隔一段时间自动截取一次，或者按回车手动截取
"""

import sys
import os
import time
import cv2
import argparse
import msvcrt

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.window import WindowBinder
from core.capture_win32 import grab_client


def save_map_roi(hwnd, roi, name_prefix="map"):
    """
    截取并保存地图ROI区域
    
    Args:
        hwnd: 窗口句柄
        roi: ROI区域 (x1, y1, x2, y2)
        name_prefix: 文件名前缀
    """
    # 创建debug目录
    os.makedirs("debug", exist_ok=True)
    
    # 截取游戏窗口
    img = grab_client(hwnd)
    
    # 提取ROI区域
    x1, y1, x2, y2 = roi
    roi_img = img[y1:y2, x1:x2]
    
    # 生成文件名（带时间戳）
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"debug/{name_prefix}_roi_{timestamp}.png"
    
    # 保存图片
    cv2.imwrite(filename, roi_img)
    
    print(f"[✓] 已保存地图ROI截图: {filename}")
    print(f"    ROI区域: {roi}")
    print(f"    图片尺寸: {roi_img.shape[1]}x{roi_img.shape[0]} (宽x高)")
    
    return filename


def main():
    parser = argparse.ArgumentParser(description="截取地图ROI区域")
    parser.add_argument("--title", type=str, required=True, help="游戏窗口标题")
    parser.add_argument("--roi", type=str, default="867,15,955,29", 
                        help="ROI区域，格式: x1,y1,x2,y2 (默认: 867,15,955,29)")
    parser.add_argument("--prefix", type=str, default="map", 
                        help="文件名前缀 (默认: map)")
    parser.add_argument("--mode", type=str, choices=["manual", "auto"], default="manual",
                        help="模式: manual=按回车截取, auto=自动定时截取 (默认: manual)")
    parser.add_argument("--interval", type=int, default=5,
                        help="自动模式下的截取间隔(秒) (默认: 5)")
    
    args = parser.parse_args()
    
    # 解析ROI
    roi = tuple(map(int, args.roi.split(",")))
    if len(roi) != 4:
        print("[错误] ROI格式错误，应为: x1,y1,x2,y2")
        return
    
    print("=" * 60)
    print("地图ROI截取工具")
    print("=" * 60)
    print(f"游戏窗口: {args.title}")
    print(f"ROI区域: {roi} (x1={roi[0]}, y1={roi[1]}, x2={roi[2]}, y2={roi[3]})")
    print(f"ROI尺寸: {roi[2]-roi[0]}x{roi[3]-roi[1]} (宽x高)")
    print(f"运行模式: {args.mode}")
    print("-" * 60)
    
    if args.mode == "manual":
        print("操作说明:")
        print("  [回车键] - 截取当前地图ROI并保存")
        print("  [q]     - 退出脚本")
    else:
        print(f"自动截取模式 - 每 {args.interval} 秒自动截取一次")
        print("  [Ctrl+C] - 退出脚本")
    
    print("=" * 60)
    
    # 绑定窗口
    try:
        binder = WindowBinder(args.title)
        hwnd = binder.ensure()
        print(f"[✓] 已绑定窗口 (hwnd={hwnd})\n")
    except Exception as e:
        print(f"[错误] 无法绑定窗口: {e}")
        return
    
    # 主循环
    capture_count = 0
    
    try:
        if args.mode == "manual":
            # 手动模式
            while True:
                print("按 [回车] 截取，按 [q] 退出...", end="\r")
                
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    
                    if key == b'\r':  # 回车
                        capture_count += 1
                        prefix = f"{args.prefix}_{capture_count}"
                        save_map_roi(hwnd, roi, name_prefix=prefix)
                        print()
                    
                    elif key in (b'q', b'Q'):  # q 或 Q
                        print("\n[退出] 用户按下 q 键")
                        break
                
                time.sleep(0.1)
        
        else:
            # 自动模式
            print("自动截取开始...\n")
            last_capture = 0
            
            while True:
                current_time = time.time()
                
                if current_time - last_capture >= args.interval:
                    capture_count += 1
                    prefix = f"{args.prefix}_{capture_count}"
                    save_map_roi(hwnd, roi, name_prefix=prefix)
                    print()
                    last_capture = current_time
                
                time.sleep(0.5)
    
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
    
    print(f"\n总共截取了 {capture_count} 张图片")


if __name__ == "__main__":
    main()
