import argparse
import configparser
import csv
import os
import sys
from collections import defaultdict
from typing import Any

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import features.cod_instance_v2 as cod


SECTION_NAME = "反贼坐标"


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _dist2(a: tuple[int, int], b: tuple[int, int]) -> int:
    dx = int(a[0]) - int(b[0])
    dy = int(a[1]) - int(b[1])
    return dx * dx + dy * dy


def _nearest_index(points: list[tuple[int, int]], target: tuple[int, int]) -> int:
    return min(range(len(points)), key=lambda i: _dist2(points[i], target))


def _read_entries(path: str) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _write_ini(path: str, routes: dict[str, list[tuple[int, int]]], map_order: list[str]):
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser[SECTION_NAME] = {}
    sec = parser[SECTION_NAME]

    keys = [m for m in map_order if m in routes]
    keys.extend([m for m in routes.keys() if m not in keys])
    for map_name in keys:
        pts = routes[map_name]
        sec[map_name] = "|".join(f"{x},{y}" for x, y in pts)

    with open(path, "w", encoding="utf-8") as f:
        parser.write(f)


def main():
    ap = argparse.ArgumentParser(description="Reorder map routes by mapping recorded entry coordinates to nearest configured points")
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--entries", default="debug/leader_instance_entries.tsv")
    ap.add_argument("--maps", default="jiange,wuliangshan")
    ap.add_argument("--output", default="debug/route_profile/cod_reordered_from_entries.ini")
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    cod_ini = cfg.get("cod_ini", "cod.ini")
    aliases = dict(cod.DEFAULT_SCENE_ALIASES)
    aliases.update(cfg.get("scene_aliases", {}) or {})
    routes = cod._normalize_scene_routes(cod._load_cod_routes(cod_ini), aliases)
    map_order = cfg.get("map_order") or list(routes.keys())

    target_maps = {m.strip() for m in str(args.maps).split(",") if m.strip()}
    entries = _read_entries(args.entries)

    by_map_coords: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for row in entries:
        m = str(row.get("from_map", "")).strip()
        if m not in target_maps:
            continue
        try:
            x = int(row.get("from_x", ""))
            y = int(row.get("from_y", ""))
        except ValueError:
            continue
        by_map_coords[m].append((x, y))

    out_routes = {k: list(v) for k, v in routes.items()}
    for map_name in sorted(target_maps):
        points = list(routes.get(map_name, []))
        seq = by_map_coords.get(map_name, [])
        if not points or not seq:
            print(f"[MAP] {map_name}: skipped (points={len(points)}, entries={len(seq)})")
            continue

        ordered_indices = []
        seen = set()
        for c in seq:
            idx = _nearest_index(points, c)
            if idx not in seen:
                seen.add(idx)
                ordered_indices.append(idx)

        remainder = [i for i in range(len(points)) if i not in seen]
        new_points = [points[i] for i in ordered_indices] + [points[i] for i in remainder]
        out_routes[map_name] = new_points

        print(
            f"[MAP] {map_name}: entries={len(seq)} mapped_unique={len(ordered_indices)} "
            f"total_points={len(points)}"
        )
        preview = ",".join(str(i + 1) for i in ordered_indices[:10])
        print(f"[MAP] {map_name}: first mapped indices={preview}")

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    _write_ini(args.output, out_routes, map_order)
    print(f"[DONE] wrote reordered ini: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
