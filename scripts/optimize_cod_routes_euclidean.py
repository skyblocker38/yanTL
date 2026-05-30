import argparse
import configparser
import math
import os
from typing import Any

import yaml


SECTION_NAME = "反贼坐标"
DEFAULT_SCENE_ALIASES = {
    "敦煌": "dunhuang",
    "嵩山": "songshan",
    "剑阁": "jiange",
    "无量山": "wuliangshan",
    "太湖": "taihu",
}


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_ini_routes(path: str) -> dict[str, list[tuple[int, int]]]:
    parser = configparser.ConfigParser()
    parser.optionxform = str

    read_ok = False
    last_error = None
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            with open(path, "r", encoding=encoding) as f:
                parser.read_file(f)
            read_ok = True
            break
        except UnicodeDecodeError as exc:
            last_error = exc
            parser = configparser.ConfigParser()
            parser.optionxform = str

    if not read_ok:
        raise RuntimeError(f"failed to decode ini: {path}") from last_error
    if SECTION_NAME not in parser:
        raise RuntimeError(f"ini missing [{SECTION_NAME}] section: {path}")

    routes: dict[str, list[tuple[int, int]]] = {}
    for map_name, raw_points in parser[SECTION_NAME].items():
        points: list[tuple[int, int]] = []
        for token in raw_points.split("|"):
            token = token.strip()
            if not token:
                continue
            x_str, y_str = token.split(",", 1)
            points.append((int(x_str), int(y_str)))
        routes[map_name] = points
    return routes


def _write_ini(path: str, routes: dict[str, list[tuple[int, int]]]):
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser[SECTION_NAME] = {}
    sec = parser[SECTION_NAME]
    for map_name, points in routes.items():
        sec[map_name] = "|".join(f"{x},{y}" for x, y in points)
    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


def _normalize(routes: dict[str, list[tuple[int, int]]], aliases: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for raw_name, points in routes.items():
        out[aliases.get(raw_name, raw_name)] = list(points)
    return out


def _dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    dx = float(a[0] - b[0])
    dy = float(a[1] - b[1])
    return math.hypot(dx, dy)


def _path_len(path: list[tuple[int, int]]) -> float:
    if len(path) <= 1:
        return 0.0
    total = 0.0
    for i in range(len(path) - 1):
        total += _dist(path[i], path[i + 1])
    return total


def _nearest_neighbor_open(
    points: list[tuple[int, int]],
    start_anchor: tuple[int, int] | None,
    end_anchor: tuple[int, int] | None,
) -> list[tuple[int, int]]:
    if not points:
        return []

    remaining = list(points)
    route: list[tuple[int, int]] = []

    fixed_end = None
    if end_anchor is not None and remaining:
        fixed_end = min(remaining, key=lambda p: _dist(p, end_anchor))
        remaining.remove(fixed_end)

    if remaining:
        if start_anchor is not None:
            first = min(remaining, key=lambda p: _dist(p, start_anchor))
            remaining.remove(first)
            route.append(first)
        else:
            route.append(remaining.pop(0))

    while remaining:
        cur = route[-1]
        nxt = min(remaining, key=lambda p: _dist(cur, p))
        remaining.remove(nxt)
        route.append(nxt)

    if fixed_end is not None:
        route.append(fixed_end)
    return route


def _two_opt_open(path: list[tuple[int, int]], fix_start: bool = True, fix_end: bool = True) -> list[tuple[int, int]]:
    n = len(path)
    if n < 4:
        return list(path)

    best = list(path)
    best_len = _path_len(best)
    start_i = 1 if fix_start else 0
    end_i = n - 1 if fix_end else n

    improved = True
    while improved:
        improved = False
        for i in range(start_i, end_i - 2):
            for j in range(i + 1, end_i - 1):
                cand = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                clen = _path_len(cand)
                if clen + 1e-9 < best_len:
                    best = cand
                    best_len = clen
                    improved = True
    return best


def _as_point(v) -> tuple[int, int] | None:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    return int(v[0]), int(v[1])


def main():
    ap = argparse.ArgumentParser(description="Optimize cod routes by Euclidean distance (ignore terrain)")
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--input", default=None, help="input ini path, default from profile.cod_ini")
    ap.add_argument("--output", default="cod_euclidean.ini")
    ap.add_argument("--map", default="", help="optimize only one map, e.g. taihu")
    ap.add_argument("--entry", default="", help="override start anchor x,y")
    ap.add_argument("--exit", dest="exit_anchor", default="", help="override end anchor x,y")
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    in_path = args.input or cfg.get("cod_ini", "cod.ini")
    raw_routes = _load_ini_routes(in_path)
    aliases = dict(DEFAULT_SCENE_ALIASES)
    aliases.update(cfg.get("scene_aliases", {}) or {})
    routes = _normalize(raw_routes, aliases)

    map_order = cfg.get("map_order") or list(routes.keys())
    map_filter = str(args.map).strip()
    targets = [map_filter] if map_filter else map_order

    def _parse_anchor(s: str) -> tuple[int, int] | None:
        if not s:
            return None
        x, y = s.split(",", 1)
        return int(x.strip()), int(y.strip())

    out_routes = dict(routes)
    for i, map_name in enumerate(map_order):
        if map_name not in targets:
            continue
        points = list(routes.get(map_name, []))
        if len(points) <= 2:
            continue

        entry_anchor = _parse_anchor(args.entry)
        if entry_anchor is None:
            entry_anchor = _as_point((cfg.get("map_entry_points", {}) or {}).get(map_name))

        exit_anchor = _parse_anchor(args.exit_anchor)
        if exit_anchor is None:
            nxt = map_order[(i + 1) % len(map_order)] if map_order else None
            key = f"{map_name}->{nxt}" if nxt else ""
            exit_anchor = _as_point((cfg.get("map_transition_points", {}) or {}).get(key))

        baseline = _path_len(points)
        route0 = _nearest_neighbor_open(points, entry_anchor, exit_anchor)
        route1 = _two_opt_open(route0, fix_start=entry_anchor is not None, fix_end=exit_anchor is not None)
        optimized = _path_len(route1)
        out_routes[map_name] = route1
        gain = (baseline - optimized) / baseline * 100.0 if baseline > 0 else 0.0
        print(
            f"[MAP] {map_name}: points={len(points)} baseline={baseline:.1f} "
            f"optimized={optimized:.1f} gain={gain:.2f}%"
        )

    # write with map_order first
    write_order = [m for m in map_order if m in out_routes]
    write_order.extend([m for m in out_routes.keys() if m not in write_order])
    ordered_out = {m: out_routes[m] for m in write_order}

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    _write_ini(args.output, ordered_out)
    print(f"[DONE] wrote euclidean-optimized routes: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()

