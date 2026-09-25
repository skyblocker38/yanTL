import os
from pathlib import Path

import cv2

from core.capture_win32 import grab_client
from core.vision import find_template
from features import cod_instance_v2 as coord_helpers
from features import herb_verification


def _load_existing_points(path: Path) -> set[tuple[int, int]]:
    points = set()
    if not path.is_file():
        return points
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        parts = raw.strip().replace(",", "|").split("|")
        if len(parts) != 2:
            continue
        try:
            points.add((int(parts[0].strip()), int(parts[1].strip())))
        except ValueError:
            continue
    return points


def _read_coord_with_retry(ctx, hwnd: int, cfg: dict, digit_templates):
    attempts = max(1, int(cfg.get("record_coord_read_attempts", 5)))
    interval = float(cfg.get("record_coord_read_interval", 0.15))
    for _ in range(attempts):
        current = coord_helpers._read_current_coord(ctx, hwnd, cfg, digit_templates)
        if current is not None:
            return current
        ctx.clock.sleep(interval)
    return None


def run(ctx):
    cfg = ctx.config or {}
    scene = str(cfg.get("scene", "shilin")).lower()
    templates_cfg = cfg.get("templates", {}) or {}
    template_path = str(templates_cfg.get("pickup_all_button", "templates/pickup_all.png"))
    if not os.path.isfile(template_path):
        raise RuntimeError(f"缺少全部拾取按钮模板: {template_path}")
    template = cv2.imread(template_path, cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"无法读取全部拾取按钮模板: {template_path}")

    output_files = cfg.get("record_output_files", {}) or {}
    output_path = Path(output_files.get(scene) or f"config/{scene}_recorded.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_existing_points(output_path)
    digit_templates = coord_helpers._load_optional_templates(cfg.get("coord_templates", {}))
    verification_template = herb_verification.load_template(cfg)
    if not digit_templates:
        raise RuntimeError("坐标记录模式未加载到坐标数字模板")

    roi_cfg = cfg.get("pickup_button_roi")
    roi = tuple(int(v) for v in roi_cfg) if isinstance(roi_cfg, (list, tuple)) and len(roi_cfg) == 4 else None
    threshold = float(cfg.get("pickup_button_threshold", 0.85))
    interval = float(cfg.get("pickup_button_poll_interval", 0.2))
    clear_hits_required = max(1, int(cfg.get("pickup_button_clear_hits", 2)))
    armed = True
    clear_hits = 0

    print("[*] record_herb_coords started: F8/Pause start-pause, F9 stop")
    print(f"[*] scene={scene}, output={output_path}")
    print(f"[*] loaded existing points={len(existing)}")

    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.2)
            continue

        hwnd = ctx.binder.ensure()
        image = grab_client(hwnd)
        if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template, image=image):
            continue
        match = find_template(image, template, threshold=threshold, roi=roi)

        if match.ok:
            clear_hits = 0
            if armed:
                current = _read_coord_with_retry(ctx, hwnd, cfg, digit_templates)
                if current is None:
                    print(f"[RECORD] pickup button score={match.score:.3f}, coordinate read failed")
                elif current in existing and bool(cfg.get("record_deduplicate", True)):
                    print(f"[RECORD] duplicate coordinate {current}, skipped")
                    armed = False
                else:
                    with output_path.open("a", encoding="utf-8", newline="\n") as output:
                        output.write(f"{current[0]}|{current[1]}\n")
                    existing.add(current)
                    armed = False
                    print(
                        f"[RECORD] saved #{len(existing)} coordinate={current} "
                        f"button_score={match.score:.3f} -> {output_path}"
                    )
        else:
            clear_hits += 1
            if clear_hits >= clear_hits_required:
                if not armed:
                    print("[RECORD] pickup window closed, armed for next herb")
                armed = True
                clear_hits = clear_hits_required

        ctx.clock.sleep(interval)

    print("[*] record_herb_coords stopped")
