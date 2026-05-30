import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.window import WindowBinder
from core.input_win32 import InputController
from core.timing import HumanClock
from core.clicker_human import HumanClicker

import features.cod_instance_v2 as cod


@dataclass
class _DummyControl:
    running: bool = True
    stop: bool = False


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    dx = float(a[0] - b[0])
    dy = float(a[1] - b[1])
    return (dx * dx + dy * dy) ** 0.5


def _pair_key(i: int, j: int) -> str:
    return f"{i}->{j}"


def _edge_cost(costs: dict[str, float], points: list[tuple[int, int]], i: int, j: int) -> float:
    key = _pair_key(i, j)
    if key in costs:
        return float(costs[key])
    rev = _pair_key(j, i)
    if rev in costs:
        return float(costs[rev])
    return _dist(points[i], points[j]) * 0.2


def _route_cost(route: list[int], costs: dict[str, float], points: list[tuple[int, int]]) -> float:
    if len(route) <= 1:
        return 0.0
    total = 0.0
    for a, b in zip(route[:-1], route[1:]):
        total += _edge_cost(costs, points, a, b)
    return total


def _nearest_neighbor_route(
    points: list[tuple[int, int]],
    costs: dict[str, float],
    start_idx: int,
    end_idx: int | None,
) -> list[int]:
    n = len(points)
    unvisited = set(range(n))
    unvisited.discard(start_idx)
    if end_idx is not None:
        unvisited.discard(end_idx)

    route = [start_idx]
    while unvisited:
        cur = route[-1]
        nxt = min(
            unvisited,
            key=lambda j: _edge_cost(costs, points, cur, j),
        )
        route.append(nxt)
        unvisited.remove(nxt)

    if end_idx is not None and end_idx != start_idx:
        route.append(end_idx)
    return route


def _two_opt_directed(
    route: list[int],
    costs: dict[str, float],
    points: list[tuple[int, int]],
    fix_start: bool = True,
    fix_end: bool = False,
    max_passes: int = 6,
) -> list[int]:
    if len(route) < 4:
        return route

    start_i = 1 if fix_start else 0
    end_i = len(route) - 1 if fix_end else len(route)

    best = list(route)
    best_cost = _route_cost(best, costs, points)

    for _ in range(max_passes):
        improved = False
        for i in range(start_i, end_i - 2):
            for j in range(i + 1, end_i - 1):
                cand = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                c = _route_cost(cand, costs, points)
                if c + 1e-6 < best_cost:
                    best = cand
                    best_cost = c
                    improved = True
        if not improved:
            break
    return best


def _find_map_end_anchor(cfg: dict, map_name: str) -> tuple[int, int] | None:
    transition_points = cfg.get("map_transition_points", {}) or {}
    map_order = cfg.get("map_order") or []
    if map_name not in map_order:
        return None
    next_map = map_order[(map_order.index(map_name) + 1) % len(map_order)] if map_order else None
    if not next_map:
        return None
    key = f"{map_name}->{next_map}"
    val = transition_points.get(key)
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        return None
    return int(val[0]), int(val[1])


def _write_ini_with_map_replaced(
    src_ini: str,
    dst_ini: str,
    map_name: str,
    new_points: list[tuple[int, int]],
    aliases: dict[str, str],
):
    routes_raw = cod._load_cod_routes(src_ini)
    raw_key = None
    for k in routes_raw.keys():
        if aliases.get(k, k) == map_name:
            raw_key = k
            break
    if raw_key is None:
        raw_key = map_name
        routes_raw[raw_key] = []

    routes_raw[raw_key] = list(new_points)

    import configparser

    parser = configparser.ConfigParser()
    parser.optionxform = str
    sec_name = "反贼坐标"
    parser[sec_name] = {}
    sec = parser[sec_name]
    for k, pts in routes_raw.items():
        sec[k] = "|".join(f"{x},{y}" for x, y in pts)

    with open(dst_ini, "w", encoding="utf-8") as f:
        parser.write(f)


def main():
    ap = argparse.ArgumentParser(description="Measure real travel-time matrix for one map and build optimized route")
    ap.add_argument("--title", required=True)
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--map", required=True, help="normalized map name, e.g. taihu")
    ap.add_argument("--from-index", type=int, default=1, help="1-based")
    ap.add_argument("--to-index", type=int, default=0, help="1-based, 0 means all")
    ap.add_argument("--entry", default="", help="entry anchor x,y (optional)")
    ap.add_argument("--exit", dest="exit_anchor", default="", help="exit anchor x,y (optional)")
    ap.add_argument("--mode", choices=["sampled", "full"], default="sampled")
    ap.add_argument("--k-neighbors", type=int, default=6, help="only for sampled mode")
    ap.add_argument("--out-dir", default="debug/route_profile")
    ap.add_argument("--out-prefix", default="")
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    aliases = dict(cod.DEFAULT_SCENE_ALIASES)
    aliases.update(cfg.get("scene_aliases", {}) or {})
    routes = cod._normalize_scene_routes(cod._load_cod_routes(cfg.get("cod_ini", "cod.ini")), aliases)

    map_name = str(args.map)
    if map_name not in routes:
        raise RuntimeError(f"map not found in routes: {map_name}")
    points_full = list(routes[map_name])
    start_idx = max(1, int(args.from_index))
    end_idx = len(points_full) if int(args.to_index) <= 0 else min(len(points_full), int(args.to_index))
    if start_idx > end_idx:
        raise RuntimeError(f"invalid index range: {start_idx}..{end_idx}")
    points = points_full[start_idx - 1 : end_idx]
    if len(points) < 2:
        raise RuntimeError("need at least 2 points for profiling")

    binder = WindowBinder(args.title)
    input_ctl = InputController()
    clock = HumanClock(jitter=float(cfg.get("jitter", 0.10)))
    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )
    control = _DummyControl(running=True, stop=False)
    ctx = cod.BotContext(binder=binder, input=input_ctl, clock=clock, control=control, config=cfg)

    scene_templates = cod._load_named_templates(cfg.get("templates", {}).get("scenes", {}))
    digit_templates = cod._load_optional_templates(cfg.get("coord_templates", {}))

    hwnd = binder.ensure()
    print(f"[*] Profiling map={map_name}, points={len(points)} range={start_idx}..{end_idx}")
    ok = cod._travel_to_scene(ctx, hwnd, clicker, cfg, map_name, scene_templates)
    if not ok:
        raise RuntimeError(f"failed to verify scene: {map_name}")

    costs: dict[str, float] = {}
    current = 0
    cod._travel_to_coordinate(ctx, hwnd, clicker, cfg, points[current], f"profile-{map_name}-1", digit_templates)
    print("[*] Reached profiling start point")

    pairs: list[tuple[int, int]] = []
    if args.mode == "full":
        for i in range(len(points)):
            for j in range(i + 1, len(points)):
                pairs.append((i, j))
    else:
        k = max(1, int(args.k_neighbors))
        seen = set()
        for i in range(len(points)):
            candidates = sorted(
                (j for j in range(len(points)) if j != i),
                key=lambda j: _dist(points[i], points[j]),
            )[:k]
            for j in candidates:
                a, b = (i, j) if i < j else (j, i)
                if (a, b) not in seen:
                    seen.add((a, b))
                    pairs.append((a, b))
        print(f"[*] sampled pairs={len(pairs)} (k={k})")

    for i, j in pairs:
        if current != i:
            cod._travel_to_coordinate(ctx, hwnd, clicker, cfg, points[i], f"profile-{map_name}-{i+1}", digit_templates)
            current = i

        t0 = time.perf_counter()
        cod._travel_to_coordinate(ctx, hwnd, clicker, cfg, points[j], f"profile-{map_name}-{i+1}->{j+1}", digit_templates)
        tij = time.perf_counter() - t0
        costs[_pair_key(i, j)] = tij
        print(f"[TIME] {i+1}->{j+1} = {tij:.2f}s")

        t1 = time.perf_counter()
        cod._travel_to_coordinate(ctx, hwnd, clicker, cfg, points[i], f"profile-{map_name}-{j+1}->{i+1}", digit_templates)
        tji = time.perf_counter() - t1
        costs[_pair_key(j, i)] = tji
        print(f"[TIME] {j+1}->{i+1} = {tji:.2f}s")
        current = i

    def _parse_anchor(s: str) -> tuple[int, int] | None:
        if not s:
            return None
        x, y = s.split(",", 1)
        return int(x.strip()), int(y.strip())

    entry_anchor = _parse_anchor(args.entry)
    if entry_anchor is None:
        v = (cfg.get("map_entry_points", {}) or {}).get(map_name)
        if isinstance(v, (list, tuple)) and len(v) == 2:
            entry_anchor = (int(v[0]), int(v[1]))

    exit_anchor = _parse_anchor(args.exit_anchor)
    if exit_anchor is None:
        exit_anchor = _find_map_end_anchor(cfg, map_name)

    start_node = min(range(len(points)), key=lambda i: _dist(points[i], entry_anchor)) if entry_anchor else 0
    end_node = min(range(len(points)), key=lambda i: _dist(points[i], exit_anchor)) if exit_anchor else None
    if end_node == start_node:
        end_node = None

    route0 = _nearest_neighbor_route(points, costs, start_node, end_node)
    route1 = _two_opt_directed(route0, costs, points, fix_start=True, fix_end=end_node is not None)
    est0 = _route_cost(route0, costs, points)
    est1 = _route_cost(route1, costs, points)

    ordered_points = [points[i] for i in route1]

    os.makedirs(args.out_dir, exist_ok=True)
    suffix = args.out_prefix or f"{map_name}_{time.strftime('%Y%m%d_%H%M%S')}"
    json_path = os.path.join(args.out_dir, f"route_profile_{suffix}.json")
    ini_path = os.path.join(args.out_dir, f"cod_profiled_{suffix}.ini")

    payload = {
        "map": map_name,
        "source_cod_ini": cfg.get("cod_ini", "cod.ini"),
        "index_range": [start_idx, end_idx],
        "entry_anchor": entry_anchor,
        "exit_anchor": exit_anchor,
        "points": points,
        "costs": costs,
        "route_initial_indices": route0,
        "route_optimized_indices": route1,
        "route_initial_est_seconds": est0,
        "route_optimized_est_seconds": est1,
        "route_optimized_points": ordered_points,
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    _write_ini_with_map_replaced(
        src_ini=cfg.get("cod_ini", "cod.ini"),
        dst_ini=ini_path,
        map_name=map_name,
        new_points=ordered_points,
        aliases=aliases,
    )

    print(f"[DONE] profile json: {os.path.abspath(json_path)}")
    print(f"[DONE] optimized ini: {os.path.abspath(ini_path)}")
    print(f"[RESULT] est initial={est0:.1f}s | est optimized={est1:.1f}s")
    print(f"[RESULT] optimized route points={len(ordered_points)}")


if __name__ == "__main__":
    main()
