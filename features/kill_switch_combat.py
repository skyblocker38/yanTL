from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from core.capture_win32 import grab_client


@dataclass
class BotContext:
    binder: Any
    input: Any
    clock: Any
    control: Any
    config: dict


def _longest_true_run(values) -> int:
    best = 0
    current = 0
    for value in values:
        if value:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _has_monster_hp(hwnd: int, cfg: dict) -> tuple[bool, int, int]:
    x1, y1, x2, y2 = [int(v) for v in cfg.get("monster_hp_roi", [276, 23, 404, 34])]
    img = grab_client(hwnd)
    h, w = img.shape[:2]
    x1 = max(0, min(x1, w))
    x2 = max(0, min(x2, w))
    y1 = max(0, min(y1, h))
    y2 = max(0, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return False, 0, 0

    crop = img[y1:y2, x1:x2]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    lower1 = np.array(cfg.get("monster_hp_red_lower_1", [0, 80, 80]), dtype=np.uint8)
    upper1 = np.array(cfg.get("monster_hp_red_upper_1", [12, 255, 255]), dtype=np.uint8)
    lower2 = np.array(cfg.get("monster_hp_red_lower_2", [170, 80, 80]), dtype=np.uint8)
    upper2 = np.array(cfg.get("monster_hp_red_upper_2", [179, 255, 255]), dtype=np.uint8)
    hsv_mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)

    b, g, r = cv2.split(crop)
    red_delta = int(cfg.get("monster_hp_red_delta", 35))
    red_min = int(cfg.get("monster_hp_red_min_value", 90))
    bgr_mask = ((r >= red_min) & (r > g + red_delta) & (r > b + red_delta)).astype(np.uint8) * 255
    mask = hsv_mask | bgr_mask

    red_pixels = int(cv2.countNonZero(mask))
    min_column_pixels = int(cfg.get("monster_hp_min_red_pixels_per_column", 3))
    min_run_columns = int(cfg.get("monster_hp_min_red_run_columns", 2))
    red_per_column = np.count_nonzero(mask, axis=0)
    red_run_columns = _longest_true_run(red_per_column >= min_column_pixels)
    return red_run_columns >= min_run_columns, red_pixels, red_run_columns


def run(ctx: BotContext):
    cfg = ctx.config
    attack_key = str(cfg.get("attack_key", "a"))
    switch_key = str(cfg.get("switch_target_key", "s"))
    attack_gap = float(cfg.get("attack_gap", 0.5))
    switch_gap = float(cfg.get("switch_target_gap", 0.25))
    switch_settle = float(cfg.get("switch_target_settle", 0.6))
    key_hold = float(cfg.get("combat_key_hold", 0.06))
    log_interval = int(cfg.get("hp_debug_log_interval", 20))
    empty_confirm_hits = int(cfg.get("monster_hp_empty_confirm_hits", 3))

    print("[*] kill_switch_combat started: F8/Pause start-pause, F9 stop")
    print(f"[*] hp_roi={cfg.get('monster_hp_roi', [276, 23, 404, 34])}")

    ticks = 0
    empty_hits = 0
    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.05)
            continue

        hwnd = ctx.binder.ensure()
        has_hp, red_pixels, red_run_columns = _has_monster_hp(hwnd, cfg)
        ticks += 1
        if log_interval > 0 and ticks % log_interval == 1:
            print(
                f"[COMBAT] hp_red_pixels={red_pixels}, red_run_columns={red_run_columns}, "
                f"has_hp={has_hp}, "
                f"empty_hits={empty_hits}/{empty_confirm_hits}"
            )

        if has_hp:
            empty_hits = 0
            ctx.input.press(hwnd, attack_key, hold=key_hold)
            ctx.clock.sleep(attack_gap)
        else:
            empty_hits += 1
            if empty_hits < empty_confirm_hits:
                ctx.clock.sleep(switch_gap)
                continue
            ctx.input.press(hwnd, switch_key, hold=key_hold)
            empty_hits = 0
            ctx.clock.sleep(switch_settle)
