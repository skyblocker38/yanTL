import argparse
import configparser
import os
from typing import Any

import yaml


SECTION_NAME = "反贼坐标"


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _read_ini_routes(path: str) -> dict[str, list[tuple[int, int]]]:
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


def _slice_points(points: list[tuple[int, int]], start_idx: int | None, end_idx: int | None) -> list[tuple[int, int]]:
    if not points:
        return []
    start = 1 if start_idx is None else max(1, int(start_idx))
    end = len(points) if end_idx is None or int(end_idx) <= 0 else min(len(points), int(end_idx))
    if start > end:
        raise RuntimeError(f"invalid range: from-index={start} > to-index={end}")
    return points[start - 1 : end]


def main():
    ap = argparse.ArgumentParser(description="Create a dedicated cod_instance test bundle (INI + YAML) for one map")
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--map", required=True, help="map key, e.g. taihu")
    ap.add_argument("--from-index", type=int, default=1, help="1-based start index in map route")
    ap.add_argument("--to-index", type=int, default=0, help="1-based end index (0 means all remaining)")
    ap.add_argument("--wait-hour", action="store_true", help="keep wait_until_hour_on_start=true in test profile")
    ap.add_argument("--output-dir", default="debug/test_runs")
    ap.add_argument("--name", default="", help="optional test name suffix")
    ap.add_argument("--title", default='《新天龙八部》 0.08.0207 (原始一区:江湖梦)')
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    base_cfg = dict(all_cfg[args.profile])

    cod_ini = str(base_cfg.get("cod_ini", "cod.ini"))
    routes = _read_ini_routes(cod_ini)
    map_name = str(args.map)
    if map_name not in routes:
        raise RuntimeError(f"map not found in {cod_ini}: {map_name}")

    selected_points = _slice_points(routes[map_name], args.from_index, args.to_index)
    if not selected_points:
        raise RuntimeError(f"no points selected for map={map_name}")

    os.makedirs(args.output_dir, exist_ok=True)
    suffix = f"_{args.name}" if args.name else ""
    ini_out = os.path.join(args.output_dir, f"cod_test_{map_name}{suffix}.ini")
    yaml_out = os.path.join(args.output_dir, f"profiles_cod_test_{map_name}{suffix}.yaml")
    test_profile_name = f"{args.profile}_test_{map_name}{suffix}".replace("-", "_")

    _write_ini(ini_out, {map_name: selected_points})

    test_cfg = dict(base_cfg)
    test_cfg["cod_ini"] = ini_out.replace("\\", "/")
    test_cfg["map_order"] = [map_name]
    test_cfg["start_map"] = map_name
    if not args.wait_hour:
        test_cfg["wait_until_hour_on_start"] = False

    out_yaml_obj = {test_profile_name: test_cfg}
    with open(yaml_out, "w", encoding="utf-8") as f:
        yaml.safe_dump(out_yaml_obj, f, allow_unicode=True, sort_keys=False)

    yaml_out_cli = yaml_out.replace("\\", "/")
    print(f"[DONE] test ini   : {os.path.abspath(ini_out)}")
    print(f"[DONE] test yaml  : {os.path.abspath(yaml_out)}")
    print(f"[DONE] test profile: {test_profile_name}")
    print(f"[INFO] map={map_name} points={len(selected_points)} range={args.from_index}..{args.to_index or 'end'}")
    print("[RUN]")
    print(
        f'python main.py --title "{args.title}" --mode cod_instance '
        f"--profile {test_profile_name} --config {yaml_out_cli}"
    )


if __name__ == "__main__":
    main()
