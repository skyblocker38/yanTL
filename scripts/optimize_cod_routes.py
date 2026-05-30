import argparse
import configparser
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


def _as_point(v) -> tuple[int, int] | None:
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        return None
    return int(v[0]), int(v[1])


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = int(a[0]) - int(b[0])
    dy = int(a[1]) - int(b[1])
    return dx * dx + dy * dy


def _optimize(points: list[tuple[int, int]], start_anchor: tuple[int, int] | None, end_anchor: tuple[int, int] | None):
    if len(points) <= 2:
        return list(points)
    if start_anchor is None and end_anchor is None:
        return list(points)

    remaining = list(points)
    ordered: list[tuple[int, int]] = []
    fixed_end = None

    if end_anchor is not None and remaining:
        fixed_end = min(remaining, key=lambda p: _dist2(p, end_anchor))
        remaining.remove(fixed_end)

    if remaining:
        if start_anchor is not None:
            first = min(remaining, key=lambda p: _dist2(p, start_anchor))
            remaining.remove(first)
            ordered.append(first)
        else:
            ordered.append(remaining.pop(0))

    while remaining:
        current = ordered[-1]
        nxt = min(remaining, key=lambda p: _dist2(p, current))
        remaining.remove(nxt)
        ordered.append(nxt)

    if fixed_end is not None:
        ordered.append(fixed_end)
    return ordered


def _normalize(routes: dict[str, list[tuple[int, int]]], aliases: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for raw_name, points in routes.items():
        out[aliases.get(raw_name, raw_name)] = list(points)
    return out


def _write_ini(path: str, routes: dict[str, list[tuple[int, int]]], map_order: list[str]):
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser[SECTION_NAME] = {}
    sec = parser[SECTION_NAME]

    ordered_keys = [m for m in map_order if m in routes]
    ordered_keys.extend([m for m in routes.keys() if m not in ordered_keys])
    for map_name in ordered_keys:
        points = routes[map_name]
        sec[map_name] = "|".join(f"{x},{y}" for x, y in points)

    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


def main():
    ap = argparse.ArgumentParser(description="Optimize cod.ini patrol coordinate order and save to a new ini")
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--input", default=None, help="input ini path; defaults to profile.cod_ini")
    ap.add_argument("--output", default="cod_optimized.ini")
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    in_path = args.input or cfg.get("cod_ini", "cod.ini")
    routes_raw = _load_ini_routes(in_path)

    aliases = dict(DEFAULT_SCENE_ALIASES)
    aliases.update(cfg.get("scene_aliases", {}) or {})
    routes = _normalize(routes_raw, aliases)

    map_order = cfg.get("map_order") or list(routes.keys())
    entry_points = cfg.get("map_entry_points", {}) or {}
    transition_points = cfg.get("map_transition_points", {}) or {}

    optimized: dict[str, list[tuple[int, int]]] = {}
    for i, map_name in enumerate(map_order):
        points = list(routes.get(map_name, []))
        if not points:
            continue
        start_anchor = _as_point(entry_points.get(map_name))
        next_map = map_order[(i + 1) % len(map_order)] if map_order else None
        key = f"{map_name}->{next_map}" if next_map else None
        end_anchor = _as_point(transition_points.get(key)) if key else None
        optimized[map_name] = _optimize(points, start_anchor, end_anchor)
        print(
            f"[ROUTE] {map_name}: points={len(points)} start_anchor={start_anchor} "
            f"end_anchor={end_anchor}"
        )

    for map_name, points in routes.items():
        if map_name not in optimized:
            optimized[map_name] = points

    out_path = args.output
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    _write_ini(out_path, optimized, map_order)
    print(f"[DONE] wrote optimized routes: {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()

