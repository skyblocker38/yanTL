import argparse
import csv
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.clicker_human import HumanClicker
from core.hotkeys import RunControl, install_hotkeys
from core.input_win32 import InputController
from core.timing import HumanClock
from core.window import WindowBinder
from features.gather_herbs import _load_route, _travel_to_map_click
from features.macro_combat import BotContext
from features import cod_instance_v2 as coord_helpers


FIELDS = [
    "index",
    "click_x",
    "click_y",
    "game_x",
    "game_y",
    "before_x",
    "before_y",
    "stable",
    "elapsed_s",
    "recorded_at",
]


def _load_profile(path: str, profile: str) -> dict:
    with open(path, "r", encoding="utf-8") as source:
        profiles = yaml.safe_load(source) or {}
    if profile not in profiles:
        raise RuntimeError(f"找不到 profile: {profile}")
    return profiles[profile]


def _load_existing(path: Path) -> dict[int, dict[str, str]]:
    if not path.is_file():
        return {}
    rows = {}
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source, delimiter="\t"):
            try:
                rows[int(row["index"])] = row
            except (KeyError, TypeError, ValueError):
                continue
    return rows


def _save_rows(path: Path, rows: dict[int, dict[str, str]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for index in sorted(rows):
            writer.writerow(rows[index])
    os.replace(temp_path, path)


def _read_coord(ctx, hwnd: int, cfg: dict, digit_templates, attempts=5):
    for _ in range(max(1, attempts)):
        current = coord_helpers._read_current_coord(ctx, hwnd, cfg, digit_templates)
        if current is not None:
            return current
        ctx.clock.sleep(0.15)
    return None


def main():
    parser = argparse.ArgumentParser(description="Map map-panel clicks to settled game coordinates")
    parser.add_argument("--title", required=True, help="完整游戏窗口标题")
    parser.add_argument("--config", default="config/profiles.yaml")
    parser.add_argument("--profile", default="gather_herbs")
    parser.add_argument("--scene", default="shilin")
    parser.add_argument("--route", default=None, help="地图点击路线；默认读取 profile 配置")
    parser.add_argument("--output", default=None, help="映射 TSV；默认 config/<scene>_map_click_mapping.tsv")
    parser.add_argument("--from-index", type=int, default=1, help="起始序号，1-based")
    parser.add_argument("--to-index", type=int, default=0, help="结束序号，0 表示最后一点")
    args = parser.parse_args()

    cfg = _load_profile(args.config, args.profile)
    scene = str(args.scene).lower()
    configured_routes = cfg.get("map_click_route_files", {}) or {}
    route_path = str(args.route or configured_routes.get(scene) or f"config/{scene}_map_clicks.txt")
    output_path = Path(args.output or f"config/{scene}_map_click_mapping.tsv")
    points = _load_route(route_path)

    start_index = max(1, int(args.from_index))
    end_index = len(points) if int(args.to_index) <= 0 else min(len(points), int(args.to_index))
    if start_index > end_index:
        raise RuntimeError(f"无效序号范围: {start_index}..{end_index}")

    control = RunControl()
    install_hotkeys(control, start_pause_key="F8", stop_key="F9", alt_pause_key="pause")
    ctx = BotContext(
        binder=WindowBinder(args.title),
        input=InputController(),
        clock=HumanClock(jitter=float(cfg.get("jitter", 0.04))),
        control=control,
        config=cfg,
    )
    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.09)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.03)), float(cfg.get("hover_max", 0.09))),
    )
    hwnd = ctx.binder.ensure()
    digit_templates = coord_helpers._load_optional_templates(cfg.get("coord_templates", {}))
    if not digit_templates:
        raise RuntimeError("未加载到坐标数字模板")

    rows = _load_existing(output_path)
    print(f"[*] scene={scene}, route={route_path}, points={len(points)}")
    print(f"[*] range={start_index}..{end_index}, existing mappings={len(rows)}")
    print(f"[*] output={output_path}")
    print("[*] 按 F8 开始/暂停，按 F9 退出")

    for index in range(start_index, end_index + 1):
        while not control.running and not control.stop:
            ctx.clock.sleep(0.1)
        if control.stop:
            break

        click_point = points[index - 1]
        before = _read_coord(ctx, hwnd, cfg, digit_templates)
        started = time.monotonic()
        stable = _travel_to_map_click(
            ctx,
            hwnd,
            clicker,
            cfg,
            click_point,
            digit_templates,
            f"{scene}-{index}",
        )
        current = _read_coord(ctx, hwnd, cfg, digit_templates)
        elapsed = time.monotonic() - started

        rows[index] = {
            "index": str(index),
            "click_x": str(click_point[0]),
            "click_y": str(click_point[1]),
            "game_x": str(current[0]) if current else "",
            "game_y": str(current[1]) if current else "",
            "before_x": str(before[0]) if before else "",
            "before_y": str(before[1]) if before else "",
            "stable": "1" if stable else "0",
            "elapsed_s": f"{elapsed:.2f}",
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        _save_rows(output_path, rows)

        actual = f"({current[0]},{current[1]})" if current else "read-failed"
        print(
            f"[MAP] #{index} click=({click_point[0]},{click_point[1]}) "
            f"game={actual} stable={stable} elapsed={elapsed:.1f}s"
        )

    print(f"[DONE] saved mappings={len(rows)} -> {output_path}")


if __name__ == "__main__":
    main()
