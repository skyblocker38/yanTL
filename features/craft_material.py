import random
from dataclasses import dataclass
from typing import Any

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

    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.2)
            continue

        hwnd = ctx.binder.ensure()
        wait_s = random.uniform(wait_min, wait_max)
        print(f"[CRAFT] waiting {wait_s:.1f}s")
        ctx.clock.sleep(wait_s)

        if ctx.control.stop or not ctx.control.running:
            continue

        with ForegroundBlock(hwnd, max_wait=0.8):
            clicker.click(hwnd, int(click_x), int(click_y), times=click_times)
        print(f"[CRAFT] clicked at ({click_x},{click_y}) x{click_times}")

