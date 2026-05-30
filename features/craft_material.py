import random
from dataclasses import dataclass
from typing import Any

import win32api
import win32con

from core.clicker_human import ForegroundBlock, HumanClicker


@dataclass
class BotContext:
    binder: Any
    input: Any
    clock: Any
    control: Any
    config: dict


def run(ctx: BotContext):
    cfg = ctx.config or {}

    # Defaults for 搓材料
    click_x, click_y = tuple(cfg.get("craft_click", [408, 502]))
    wait_min = float(cfg.get("craft_wait_min", 200))
    wait_max = float(cfg.get("craft_wait_max", 210))
    click_times = int(cfg.get("craft_click_times", 1))

    if wait_min <= 0 or wait_max <= 0 or wait_max < wait_min:
        raise RuntimeError("Invalid craft wait range")

    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )

    print("[*] craft_material started: F8/Pause start-pause, F9 stop")
    print(f"[*] click=({click_x},{click_y}), wait=[{wait_min:.1f}, {wait_max:.1f}]s")

    def _post_click(hwnd: int, x: int, y: int):
        lp = win32api.MAKELONG(int(x), int(y))
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lp)
        ctx.clock.sleep(0.03)
        win32api.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lp)

    def _click_once(hwnd: int):
        # Primary path: same as existing stable features (foreground + human click)
        with ForegroundBlock(hwnd, max_wait=0.6):
            clicker.click(hwnd, int(click_x), int(click_y), times=click_times)
        # Fallback: add one background message click to improve hit rate
        _post_click(hwnd, int(click_x), int(click_y))

    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.2)
            continue

        hwnd = ctx.binder.ensure()
        _click_once(hwnd)
        print(f"[CRAFT] clicked at ({click_x},{click_y}) x{click_times}")

        wait_s = random.uniform(wait_min, wait_max)
        print(f"[CRAFT] waiting {wait_s:.1f}s")
        ctx.clock.sleep(wait_s)
