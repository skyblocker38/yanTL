import argparse
import csv
import os
import sys
import time
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import cv2
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.capture_win32 import grab_client
from core.window import WindowBinder
from core.vision import find_template
import features.cod_instance_v2 as cod


def _load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _detect_scene_from_image(
    img,
    cfg: dict,
    scene_templates: dict[str, Any],
    scene_threshold_override: float | None = None,
) -> tuple[str | None, float]:
    if img is None:
        return None, 0.0
    roi = cfg.get("scene_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)
    threshold = float(scene_threshold_override if scene_threshold_override is not None else cfg.get("scene_threshold", 0.85))

    best_name = None
    best_score = -1.0
    for name, tpl in scene_templates.items():
        m = find_template(img, tpl, threshold=threshold, roi=roi)
        if float(m.score) > best_score:
            best_score = float(m.score)
            best_name = name if m.ok else best_name

    if best_name is None:
        return None, max(best_score, 0.0)
    return best_name, best_score


def _append_row(path: str, row: dict[str, Any]):
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    exists = os.path.isfile(path)
    fieldnames = [
        "event_time",
        "prev_sample_time",
        "from_map",
        "from_x",
        "from_y",
        "scene_score",
        "detected_state",
    ]
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser(description="Record leader's dungeon-entry coordinates while you are a team member")
    ap.add_argument("--title", required=True)
    ap.add_argument("--config", default="config/profiles_cod_v3.yaml")
    ap.add_argument("--profile", default="cod_instance_default")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--out", default="debug/leader_instance_entries.tsv")
    ap.add_argument("--scene-threshold", type=float, default=None, help="override scene template threshold, e.g. 0.98")
    args = ap.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    binder = WindowBinder(args.title)
    dummy_ctx = SimpleNamespace()

    scene_templates = cod._load_named_templates(cfg.get("templates", {}).get("scenes", {}))
    tracked_maps = set(scene_templates.keys())
    digit_templates = cod._load_optional_templates(cfg.get("coord_templates", {}))

    print(f"[*] tracking maps={sorted(tracked_maps)}")
    print(f"[*] interval={args.interval:.2f}s out={args.out}")
    print("[*] press Ctrl+C to stop")

    inside_instance = False
    prev = None

    try:
        while True:
            hwnd = binder.ensure()
            img = grab_client(hwnd)
            scene, scene_score = _detect_scene_from_image(
                img,
                cfg,
                scene_templates,
                scene_threshold_override=args.scene_threshold,
            )
            coord = cod._read_current_coord(dummy_ctx, hwnd, cfg, digit_templates)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            state = scene if scene in tracked_maps else "instance_or_other"
            print(f"[TRACK] t={now} scene={state} coord={coord} score={scene_score:.3f}")

            if prev is not None:
                prev_scene = prev["scene"]
                curr_scene = scene
                prev_in_maps = prev_scene in tracked_maps
                curr_in_maps = curr_scene in tracked_maps

                if (not inside_instance) and prev_in_maps and (not curr_in_maps):
                    px, py = ("", "")
                    if isinstance(prev.get("coord"), tuple) and len(prev["coord"]) == 2:
                        px, py = prev["coord"]
                    row = {
                        "event_time": now,
                        "prev_sample_time": prev["time"],
                        "from_map": prev_scene or "",
                        "from_x": px,
                        "from_y": py,
                        "scene_score": f"{prev.get('score', 0.0):.4f}",
                        "detected_state": "enter_instance",
                    }
                    _append_row(args.out, row)
                    inside_instance = True
                    print(f"[REC] enter_instance from {row['from_map']} ({row['from_x']},{row['from_y']})")

                if inside_instance and curr_in_maps:
                    inside_instance = False
                    print(f"[REC] returned_to_outside map={curr_scene}, armed for next detection")

            prev = {
                "time": now,
                "scene": scene,
                "coord": coord,
                "score": scene_score,
            }
            time.sleep(max(0.2, float(args.interval)))

    except KeyboardInterrupt:
        print("\n[*] stopped by user")


if __name__ == "__main__":
    main()
