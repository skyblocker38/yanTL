# features/auto_plant.py
"""
自动种植功能
流程：
1. 点击稻草人
2. 点击早产位置
3. 点击槿麻位置
4. 等待生长时间
5. 随机顺序收取四个位置的菜
6. 循环
"""
import time
import random

from dataclasses import dataclass
from typing import Any

from core.clicker_human import HumanClicker, ForegroundBlock


@dataclass
class BotContext:
    binder: Any
    input: Any      # InputController（后台按键）
    clock: Any      # HumanClock
    control: Any    # RunControl
    config: dict


def _click_point(clicks: dict, key: str) -> tuple:
    """从配置中获取点击坐标"""
    pt = clicks.get(key)
    if not pt:
        raise RuntimeError(f"配置中缺少坐标: {key}")
    return tuple(pt)


def _random_wait(base=1.0, jitter=0.3):
    """随机等待时间"""
    wait_time = base + random.uniform(-jitter, jitter)
    time.sleep(max(0.5, wait_time))  # 最少等待0.1秒


def _plant_cycle(ctx: BotContext, hwnd: int, clicker: HumanClicker, clicks: dict, cfg: dict):
    """
    完整的种植循环
    """
    jitter = float(cfg.get("jitter", 0.2))
    
    print("\n" + "="*50)
    print("[种植] 开始新一轮种植循环")
    print("="*50)
    
    # ========== 阶段1: 种植 ==========
    print("\n[阶段1] 开始种植...")
    
    # 1. 点击稻草人
    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "daocaoren")
        clicker.click(hwnd, x, y, times=1)
        print("[种植] 已点击稻草人")
    _random_wait(2.0, jitter)
    
    # 2. 点击早产位置
    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "zaochan")
        clicker.click(hwnd, x, y, times=1)
        print("[种植] 已点击早产")
    _random_wait(2.0, jitter)
    
    # 3. 点击槿麻位置
    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "jinma")
        clicker.click(hwnd, x, y, times=1)
        print("[种植] 已点击槿麻")
    _random_wait(2.0, jitter)

    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, "esc", hold=0.05)
        print("[种植] 已按下esc自动寻路")
    _random_wait(2.0, jitter)
    
    print("[阶段1] 种植完成")
    
    # ========== 阶段2: 等待生长 ==========
    wait_time = float(cfg.get("wait_for_growth", 310))
    print(f"\n[阶段2] 等待作物生长 ({wait_time}秒)...")
    
    # 分段显示倒计时
    intervals = [60, 60, 60, 60, 60, 10]  # 60s * 5 + 10s = 310s
    remaining = wait_time
    
    for interval in intervals:
        if remaining <= 0:
            break
        
        wait = min(interval, remaining)
        ctx.clock.sleep(wait)
        remaining -= wait
        
        if remaining > 0:
            print(f"[等待] 剩余 {remaining:.0f} 秒...")
    
    print("[阶段2] 作物已成熟")
    
    # ========== 阶段3: 收菜 ==========
    print("\n[阶段3] 开始收菜...")
    
    # 生成随机收菜顺序
    harvest_order = [1, 2, 3, 4]
    random.shuffle(harvest_order)
    print(f"[收菜] 收菜顺序: {harvest_order}")
    
    for idx, pos_num in enumerate(harvest_order, 1):
        pos_key = f"shoucai{pos_num}"
        
        # 点击收菜位置
        with ForegroundBlock(hwnd, max_wait=0.6):
            x, y = _click_point(clicks, pos_key)
            clicker.click(hwnd, x, y, times=1)
            print(f"[收菜] ({idx}/4) 已点击 {pos_key}")
        
        # 等待8秒
        print(f"[收菜] 等待8秒...")
        ctx.clock.sleep(8.0)
        
        # 点击拾取位置
        with ForegroundBlock(hwnd, max_wait=0.6):
            x, y = _click_point(clicks, "shiqu")
            clicker.click(hwnd, x, y, times=1)
            print(f"[收菜] 已点击拾取")
        # 随机等待
        _random_wait(2.0, jitter)
    
    print("[阶段3] 收菜完成")
    print("\n" + "="*50)
    print("[种植] 本轮循环完成")
    print("="*50 + "\n")


def run(ctx: BotContext):
    """
    自动种植主循环
    """
    cfg = ctx.config
    clicks = cfg.get("clicks", {})
    
    # 人性化点击器
    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )
    
    print("="*60)
    print("[*] 自动种植功能已启动")
    print("[*] F8 暂停/继续，F9 退出")
    print("="*60)
    
    cycle_count = 0
    
    while not ctx.control.stop:
        # 检查是否暂停
        if not ctx.control.running:
            ctx.clock.sleep(0.5)
            continue
        
        # 确保窗口有效
        hwnd = ctx.binder.ensure()
        
        # 执行一轮种植循环
        cycle_count += 1
        print(f"\n{'#'*60}")
        print(f"# 第 {cycle_count} 轮种植循环")
        print(f"{'#'*60}")
        
        try:
            _plant_cycle(ctx, hwnd, clicker, clicks, cfg)
        except Exception as e:
            print(f"[ERR] 种植循环出错: {e}")
            print("[*] 等待10秒后重试...")
            ctx.clock.sleep(10)
            continue
    
    print("\n[*] 自动种植功能已停止")