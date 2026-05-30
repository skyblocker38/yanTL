import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.window import WindowBinder
from core.input_win32 import InputController
from core.timing import HumanClock
from core.clicker_human import HumanClicker, ForegroundBlock
import features.cod_instance_v2 as cod


@dataclass
class _Control:
    running: bool = True
    stop: bool = False


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _solve_linear(p1x: float, p1y: float, p2x: float, p2y: float) -> tuple[float, float]:
    if abs(p2x - p1x) < 1e-9:
        raise RuntimeError("invalid calibration: x values are identical")
    scale = (p2y - p1y) / (p2x - p1x)
    bias = p1y - scale * p1x
    return scale, bias


def _to_click(
    coord: tuple[int, int],
    sx: float,
    bx: float,
    sy: float,
    by: float,
) -> tuple[int, int]:
    x, y = coord
    cx = int(round(sx * float(x) + bx))
    cy = int(round(sy * float(y) + by))
    return cx, cy


def main():
    ap = argparse.ArgumentParser(description="Test taihu patrol by direct map-panel click mapping")
    ap.add_argument("--title", required=True)
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--map", default="taihu")
    ap.add_argument("--from-index", type=int, default=1)
    ap.add_argument("--to-index", type=int, default=0, help="0 means all")
    ap.add_argument("--c1", default="119,59:366,210", help="coord_x,coord_y:click_x,click_y")
    ap.add_argument("--c2", default="237,273:580,598", help="coord_x,coord_y:click_x,click_y")
    ap.add_argument("--travel-scene", action="store_true")
    ap.add_argument("--click-move-btn", action="store_true", help="click configured move_btn after map click")
    ap.add_argument("--map-click-wait", type=float, default=0.25)
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    def _parse_pair(s: str):
        left, right = s.split(":", 1)
        x, y = left.split(",", 1)
        cx, cy = right.split(",", 1)
        return (int(x.strip()), int(y.strip())), (int(cx.strip()), int(cy.strip()))

    (x1, y1), (cx1, cy1) = _parse_pair(args.c1)
    (x2, y2), (cx2, cy2) = _parse_pair(args.c2)
    sx, bx = _solve_linear(float(x1), float(cx1), float(x2), float(cx2))
    sy, by = _solve_linear(float(y1), float(cy1), float(y2), float(cy2))
    print(f"[MAP-CLICK] calib x: click_x={sx:.6f}*x+{bx:.3f}")
    print(f"[MAP-CLICK] calib y: click_y={sy:.6f}*y+{by:.3f}")

    aliases = dict(cod.DEFAULT_SCENE_ALIASES)
    aliases.update(cfg.get("scene_aliases", {}) or {})
    routes = cod._normalize_scene_routes(cod._load_cod_routes(cfg.get("cod_ini", "cod.ini")), aliases)
    map_name = str(args.map)
    if map_name not in routes:
        raise RuntimeError(f"map not found in cod_ini: {map_name}")

    points_all = list(routes[map_name])
    start_idx = max(1, int(args.from_index))
    end_idx = len(points_all) if int(args.to_index) <= 0 else min(len(points_all), int(args.to_index))
    if start_idx > end_idx:
        raise RuntimeError(f"invalid range: {start_idx}..{end_idx}")
    points = points_all[start_idx - 1 : end_idx]
    print(f"[*] map={map_name} points={len(points)} range={start_idx}..{end_idx}")

    binder = WindowBinder(args.title)
    input_ctl = InputController()
    clock = HumanClock(jitter=float(cfg.get("jitter", 0.10)))
    control = _Control()
    ctx = cod.BotContext(binder=binder, input=input_ctl, clock=clock, control=control, config=cfg)
    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )

    hwnd = binder.ensure()
    scene_templates = cod._load_named_templates(cfg.get("templates", {}).get("scenes", {}))
    digit_templates = cod._load_optional_templates(cfg.get("coord_templates", {}))
    clicks = cfg.get("clicks", {})

    if args.travel_scene:
        ok = cod._travel_to_scene(ctx, hwnd, clicker, cfg, map_name, scene_templates)
        if not ok:
            raise RuntimeError(f"failed to verify scene: {map_name}")

    success = 0
    failed = 0
    for idx, coord in enumerate(points, start=start_idx):
        tx, ty = int(coord[0]), int(coord[1])
        mx, my = _to_click((tx, ty), sx, bx, sy, by)
        label = f"{map_name}-{idx}"

        with ForegroundBlock(hwnd, max_wait=0.6):
            if bool(cfg.get("pre_route_press_i", True)):
                ctx.input.press(hwnd, "i", hold=float(cfg.get("pre_route_i_hold", 0.05)))
                ctx.clock.sleep(float(cfg.get("pre_route_i_wait", 0.2)))

            ctx.input.press(hwnd, "tab", hold=0.15)
            ctx.clock.sleep(float(cfg.get("open_route_wait", 1.0)))
            clicker.click(hwnd, mx, my, times=1)
            ctx.clock.sleep(float(args.map_click_wait))

            if args.click_move_btn and "move_btn" in clicks:
                bxm, bym = cod._click_point(clicks, "move_btn")
                clicker.click(hwnd, bxm, bym, times=1)
                ctx.clock.sleep(0.2)

            ctx.input.press(hwnd, "tab", hold=0.15)

        print(f"[MAP-CLICK] {label} coord=({tx},{ty}) click=({mx},{my})")
        ok = cod._wait_for_target_coordinate(ctx, hwnd, cfg, (tx, ty), digit_templates, label)
        if ok:
            success += 1
        else:
            failed += 1

    print(f"[RESULT] done map={map_name} success={success} failed={failed}")


if __name__ == "__main__":
    main()

