import ctypes
import csv
import os
import random
import shutil
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import win32api
import win32gui

from core.capture_win32 import grab_client
from core.clicker_human import ForegroundBlock, HumanClicker
from core.vision import find_template, find_template_masked
from features import cod_instance_v2 as route_helpers
from features import herb_verification


COUNT_FIELDS = [
    "scene",
    "route_index",
    "count",
]


class HerbCountNotebook:
    def __init__(self, path: str, enabled: bool):
        self.path = Path(path)
        self.enabled = enabled
        self.counts = {}
        if not enabled:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        legacy_format = False
        if self.path.is_file() and self.path.stat().st_size > 0:
            with self.path.open("r", encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source, delimiter="\t")
                legacy_format = "count" not in (reader.fieldnames or [])
                for row in reader:
                    try:
                        key = (str(row.get("scene", "")), int(row["route_index"]))
                        if legacy_format:
                            self.counts[key] = self.counts.get(key, 0) + 1
                        else:
                            self.counts[key] = int(row["count"])
                    except (KeyError, TypeError, ValueError):
                        continue
            if legacy_format:
                backup = self.path.with_name(
                    f"{self.path.stem}_event_backup{self.path.suffix}"
                )
                if not backup.exists():
                    shutil.copy2(self.path, backup)
                print(f"[COUNT] converted event log to point totals; backup={backup}")
        self._save()

    def _save(self):
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(
                output,
                fieldnames=COUNT_FIELDS,
                delimiter="\t",
                lineterminator="\n",
            )
            writer.writeheader()
            for (scene, route_index), count in sorted(self.counts.items()):
                writer.writerow(
                    {
                        "scene": scene,
                        "route_index": route_index,
                        "count": count,
                    }
                )
        os.replace(temp_path, self.path)

    def record(self, scene: str, route_index: int):
        if not self.enabled:
            return
        key = (scene, route_index)
        self.counts[key] = self.counts.get(key, 0) + 1
        self._save()
        print(f"[COUNT] {scene}-{route_index} cumulative={self.counts[key]}")


class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", ctypes.wintypes.POINT),
    ]


def _load_route(path: str) -> list[tuple[int, int]]:
    route_path = Path(path)
    if not route_path.is_file():
        raise RuntimeError(f"采药路线文件不存在: {path}")

    points = []
    for line_no, raw in enumerate(route_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.replace(",", "|").split("|")
        if len(parts) != 2:
            raise RuntimeError(f"采药路线格式错误: {path}:{line_no}: {raw}")
        try:
            points.append((int(parts[0].strip()), int(parts[1].strip())))
        except ValueError as exc:
            raise RuntimeError(f"采药路线坐标不是整数: {path}:{line_no}: {raw}") from exc

    if not points:
        raise RuntimeError(f"采药路线中没有坐标: {path}")
    return points


def _load_template(path: str | None):
    if not path or not os.path.isfile(path):
        return None
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"无法读取模板: {path}")
    return image


def _cursor_handle() -> int:
    info = CURSORINFO()
    info.cbSize = ctypes.sizeof(CURSORINFO)
    if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
        return 0
    return int(info.hCursor or 0)


def _move_cursor_client(hwnd: int, point: tuple[int, int], duration: float):
    sx, sy = win32gui.ClientToScreen(hwnd, point)
    x0, y0 = win32gui.GetCursorPos()
    steps = max(2, int(duration / 0.012))
    bend_x = random.uniform(-12.0, 12.0)
    bend_y = random.uniform(-9.0, 9.0)
    for index in range(1, steps + 1):
        t = index / steps
        curve = 4.0 * t * (1.0 - t)
        x = round(x0 + (sx - x0) * t + bend_x * curve)
        y = round(y0 + (sy - y0) * t + bend_y * curve)
        win32api.SetCursorPos((x, y))
        time.sleep(duration / steps)


def _find_leaf_by_color(image: np.ndarray, roi: tuple[int, int, int, int], cfg: dict):
    x1, y1, x2, y2 = roi
    view = image[y1:y2, x1:x2]
    if view.size == 0:
        return None, 0.0

    hsv = cv2.cvtColor(view, cv2.COLOR_BGR2HSV)
    lower = np.array(cfg.get("leaf_hsv_lower", [35, 110, 120]), dtype=np.uint8)
    upper = np.array(cfg.get("leaf_hsv_upper", [90, 255, 255]), dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    min_area = int(cfg.get("leaf_min_area", 5))
    max_area = int(cfg.get("leaf_max_area", 160))
    max_width = int(cfg.get("leaf_max_width", 24))
    max_height = int(cfg.get("leaf_max_height", 24))
    center_x = (x2 - x1) / 2.0
    center_y = (y2 - y1) / 2.0
    candidates = []

    count, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    for index in range(1, count):
        left, top, width, height, area = (int(v) for v in stats[index])
        if not (min_area <= area <= max_area):
            continue
        if width > max_width or height > max_height or width < 2 or height < 2:
            continue
        cx, cy = (float(v) for v in centroids[index])
        fill = area / float(max(1, width * height))
        if fill < float(cfg.get("leaf_min_fill", 0.18)):
            continue
        distance = ((cx - center_x) ** 2 + (cy - center_y) ** 2) ** 0.5
        score = fill + min(area, 40) / 100.0 - distance / 1000.0
        candidates.append((score, int(round(x1 + cx)), int(round(y1 + cy))))

    if not candidates:
        return None, 0.0
    score, cx, cy = max(candidates)
    return (cx, cy), float(score)


def _find_leaf(image: np.ndarray, leaf_template, cfg: dict):
    roi = tuple(int(v) for v in cfg.get("minimap_roi", [830, 25, 1020, 205]))
    if leaf_template is not None:
        if str(cfg.get("leaf_match_mode", "hsv")).lower() == "hsv":
            match = find_template_masked(
                image,
                leaf_template,
                threshold=float(cfg.get("leaf_template_threshold", 0.82)),
                roi=roi,
                lower_hsv=tuple(int(v) for v in cfg.get("leaf_hsv_lower", [35, 110, 120])),
                upper_hsv=tuple(int(v) for v in cfg.get("leaf_hsv_upper", [90, 255, 255])),
            )
        else:
            match = find_template(
                image,
                leaf_template,
                threshold=float(cfg.get("leaf_template_threshold", 0.82)),
                roi=roi,
            )
        return ((match.x, match.y), match.score) if match.ok else (None, match.score)
    return _find_leaf_by_color(image, roi, cfg)


def _wait_for_coordinate_stable(ctx, hwnd: int, cfg: dict, digit_templates: dict[str, Any], label: str):
    timeout = float(cfg.get("leaf_walk_max_wait", 30.0))
    interval = float(cfg.get("leaf_walk_coord_interval", 0.5))
    required = int(cfg.get("leaf_walk_stable_hits", 3))
    ctx.clock.sleep(float(cfg.get("leaf_walk_start_wait", 1.2)))
    elapsed = 0.0
    last_coord = None
    stable_hits = 0

    while elapsed <= timeout and not ctx.control.stop:
        current = route_helpers._read_current_coord(ctx, hwnd, cfg, digit_templates)
        if current is not None and current == last_coord:
            stable_hits += 1
        elif current is not None:
            stable_hits = 1
        else:
            stable_hits = 0
        last_coord = current
        if stable_hits >= required:
            print(f"[HERB] {label} stopped at {current}")
            return True
        ctx.clock.sleep(interval)
        elapsed += interval

    print(f"[HERB] {label} walk did not stabilize, continue search")
    return False


def _square_spiral_points(center, bounds, step: int):
    x1, y1, x2, y2 = bounds
    center_x = min(x2, max(x1, int(center[0])))
    center_y = min(y2, max(y1, int(center[1])))
    max_radius = max(center_x - x1, x2 - center_x, center_y - y1, y2 - center_y)
    seen = set()

    def add(point):
        if point not in seen:
            seen.add(point)
            points.append(point)

    points = []
    add((center_x, center_y))
    for radius in range(step, max_radius + step, step):
        left = max(x1, center_x - radius)
        right = min(x2, center_x + radius)
        top = max(y1, center_y - radius)
        bottom = min(y2, center_y + radius)

        xs = list(range(left, right + 1, step))
        ys = list(range(top, bottom + 1, step))
        if not xs or xs[-1] != right:
            xs.append(right)
        if not ys or ys[-1] != bottom:
            ys.append(bottom)

        for x in xs:
            add((x, top))
        for y in ys[1:]:
            add((right, y))
        for x in reversed(xs[:-1]):
            add((x, bottom))
        for y in reversed(ys[1:-1]):
            add((left, y))
    points.sort(
        key=lambda point: max(
            abs(point[0] - center_x),
            abs(point[1] - center_y),
        )
    )
    return points


def _search_sickle_cursor(ctx, hwnd: int, cfg: dict):
    x1, y1, x2, y2 = (int(v) for v in cfg.get("herb_search_roi", [400, 275, 615, 495]))
    configured_center = cfg.get("herb_center_click", [507, 384])
    center = (int(configured_center[0]), int(configured_center[1]))
    step = max(2, int(cfg.get("herb_search_step", 7)))
    points = _square_spiral_points(center, (x1, y1, x2, y2), step)
    max_seconds = float(cfg.get("herb_search_max_wait", 12.0))
    started = time.monotonic()
    confirm_hits = max(1, int(cfg.get("sickle_cursor_confirm_hits", 2)))
    target_handle = int(cfg.get("sickle_cursor_handle", 20908519))
    print(
        f"[HERB] square-expand cursor scan center={center}, roi=({x1},{y1},{x2},{y2}), "
        f"target_handle={target_handle}"
    )

    for point in points:
        if ctx.control.stop or time.monotonic() - started > max_seconds:
            break
        jittered = (
            min(x2, max(x1, point[0] + random.randint(-2, 2))),
            min(y2, max(y1, point[1] + random.randint(-2, 2))),
        )
        _move_cursor_client(
            hwnd,
            jittered,
            random.uniform(
                float(cfg.get("herb_cursor_move_min", 0.055)),
                float(cfg.get("herb_cursor_move_max", 0.10)),
            ),
        )
        hits = 0
        for _ in range(confirm_hits):
            time.sleep(float(cfg.get("cursor_probe_wait", 0.04)))
            handle = _cursor_handle()
            if handle == target_handle:
                hits += 1
            else:
                break
        if hits >= confirm_hits:
            print(f"[HERB] sickle cursor confirmed at {jittered}, handle={target_handle}")
            return jittered

    print("[HERB] sickle cursor not found")
    return None


def _wait_for_harvest_dialog(ctx, hwnd: int, template, verification_template, cfg: dict):
    if template is None:
        fallback_wait = float(cfg.get("harvest_fallback_wait", 5.0))
        interval = min(0.2, fallback_wait) if fallback_wait > 0 else 0.2
        elapsed = 0.0
        while elapsed < fallback_wait and not ctx.control.stop:
            image = grab_client(hwnd)
            if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template, image=image):
                elapsed = 0.0
                continue
            ctx.clock.sleep(interval)
            elapsed += interval
        return True

    roi = tuple(int(v) for v in cfg.get("harvest_dialog_roi", [300, 180, 850, 650]))
    threshold = float(cfg.get("harvest_dialog_threshold", 0.82))
    interval = float(cfg.get("harvest_dialog_poll_interval", 0.3))
    timeout = float(cfg.get("harvest_dialog_max_wait", 12.0))
    elapsed = 0.0
    while elapsed <= timeout and not ctx.control.stop:
        image = grab_client(hwnd)
        if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template, image=image):
            elapsed = 0.0
            continue
        match = find_template(image, template, threshold=threshold, roi=roi)
        if match.ok:
            print(f"[HERB] harvest dialog found score={match.score:.3f}")
            return True
        ctx.clock.sleep(interval)
        elapsed += interval
    print("[HERB] harvest dialog not found, skip pickup")
    return False


def _wait_before_pickup(ctx, cfg: dict):
    delay = random.uniform(
        float(cfg.get("pickup_click_delay_min", 0.0)),
        float(cfg.get("pickup_click_delay_max", 2.0)),
    )
    print(f"[HERB] pickup button found, click delay={delay:.1f}s")
    time.sleep(delay)


def _match_mount_icon(hwnd: int, mount_template, cfg: dict):
    if mount_template is None:
        return None
    roi = tuple(int(v) for v in cfg.get("mount_icon_roi", [561, 63, 591, 92]))
    return find_template(
        grab_client(hwnd),
        mount_template,
        threshold=float(cfg.get("mount_icon_threshold", 0.85)),
        roi=roi,
    )


def _ensure_dismounted(ctx, hwnd: int, cfg: dict, mount_template) -> bool:
    if mount_template is None:
        print("[MOUNT] cannot confirm dismounted: mount template is not configured")
        return False

    match = _match_mount_icon(hwnd, mount_template, cfg)
    if match is not None and not match.ok:
        print(f"[MOUNT] confirmed dismounted score={match.score:.3f}")
        return True

    print(f"[MOUNT] mounted score={match.score:.3f}, press 0 to dismount")
    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, str(cfg.get("mount_key", "0")), hold=0.06)

    timeout = float(cfg.get("dismount_wait_max", 5.0))
    interval = float(cfg.get("dismount_poll_interval", 0.25))
    required = max(1, int(cfg.get("dismount_clear_hits", 2)))
    elapsed = 0.0
    clear_hits = 0
    while elapsed <= timeout and not ctx.control.stop:
        match = _match_mount_icon(hwnd, mount_template, cfg)
        if match is not None and not match.ok:
            clear_hits += 1
            if clear_hits >= required:
                print(f"[MOUNT] dismount confirmed after {elapsed:.1f}s")
                return True
        else:
            clear_hits = 0
        ctx.clock.sleep(interval)
        elapsed += interval

    print("[MOUNT] dismount confirmation timed out, skip this harvest")
    return False


def _ensure_mounted(ctx, hwnd: int, cfg: dict, mount_template, verification_template) -> bool:
    if mount_template is None:
        print("[MOUNT] mount template is not configured, skip mount check")
        return False

    match = _match_mount_icon(hwnd, mount_template, cfg)
    if match is not None and match.ok:
        print(f"[MOUNT] already mounted score={match.score:.3f}")
        return True

    print(f"[MOUNT] not mounted score={match.score if match is not None else 0.0:.3f}, press 0")
    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, str(cfg.get("mount_key", "0")), hold=0.06)

    timeout = float(cfg.get("mount_wait_max", 10.0))
    interval = float(cfg.get("mount_poll_interval", 0.3))
    elapsed = 0.0
    while elapsed <= timeout and not ctx.control.stop:
        image = grab_client(hwnd)
        if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template, image=image):
            elapsed = 0.0
            continue
        roi = tuple(int(v) for v in cfg.get("mount_icon_roi", [561, 63, 591, 92]))
        match = find_template(
            image,
            mount_template,
            threshold=float(cfg.get("mount_icon_threshold", 0.85)),
            roi=roi,
        )
        if match.ok:
            print(f"[MOUNT] mount icon appeared score={match.score:.3f} after {elapsed:.1f}s")
            return True
        ctx.clock.sleep(interval)
        elapsed += interval

    print("[MOUNT] mount icon wait timed out, continue anyway")
    return False


def _harvest_once(
    ctx,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    digit_templates,
    harvest_template,
    verification_template,
    mount_template,
):
    settle = random.uniform(
        float(cfg.get("leaf_arrival_settle_min", 2.0)),
        float(cfg.get("leaf_arrival_settle_max", 3.0)),
    )
    ctx.clock.sleep(settle)
    if not _ensure_dismounted(ctx, hwnd, cfg, mount_template):
        return False
    with ForegroundBlock(hwnd, max_wait=0.6):
        sickle_point = _search_sickle_cursor(ctx, hwnd, cfg)
        if sickle_point is None:
            return False
        clicker.click(hwnd, sickle_point[0], sickle_point[1], times=1)
        print(f"[HERB] clicked herb at {sickle_point}")

    if not _wait_for_harvest_dialog(ctx, hwnd, harvest_template, verification_template, cfg):
        return False
    _wait_before_pickup(ctx, cfg)
    pickup = cfg.get("pickup_all_click")
    if not isinstance(pickup, (list, tuple)) or len(pickup) != 2:
        print("[HERB] pickup_all_click is not configured")
        return False
    with ForegroundBlock(hwnd, max_wait=0.6):
        clicker.click(hwnd, int(pickup[0]), int(pickup[1]), times=1)
    print(f"[HERB] clicked pickup all at ({pickup[0]},{pickup[1]})")
    ctx.clock.sleep(random.uniform(0.5, 0.9))
    return True


def _harvest_at_center(
    ctx,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    harvest_template,
    verification_template,
    mount_template,
):
    wait_min = float(cfg.get("arrival_action_wait_min", 0.3))
    wait_max = float(cfg.get("arrival_action_wait_max", 0.6))
    ctx.clock.sleep(random.uniform(wait_min, wait_max))

    if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template):
        if ctx.control.stop:
            return False

    if not _ensure_dismounted(ctx, hwnd, cfg, mount_template):
        return False

    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, str(cfg.get("stealth_key", "4")), hold=0.06)
        ctx.clock.sleep(
            random.uniform(
                float(cfg.get("stealth_settle_min", 1.0)),
                float(cfg.get("stealth_settle_max", 2.0)),
            )
        )
        sickle_point = _search_sickle_cursor(ctx, hwnd, cfg)
        if sickle_point is None:
            fallback = cfg.get("herb_center_click", [507, 384])
            if not bool(cfg.get("sickle_fallback_center_click", False)):
                print("[HERB] sickle cursor not found, skip harvest click")
                return False
            sickle_point = (int(fallback[0]), int(fallback[1]))
            print(f"[HERB] sickle cursor not found, fallback click={sickle_point}")
        clicker.click(hwnd, sickle_point[0], sickle_point[1], times=1)
    print(f"[HERB] confirmed dismounted, pressed 4 and clicked herb at {sickle_point}")

    if not _wait_for_harvest_dialog(ctx, hwnd, harvest_template, verification_template, cfg):
        return False
    _wait_before_pickup(ctx, cfg)
    pickup = cfg.get("pickup_all_click")
    if not isinstance(pickup, (list, tuple)) or len(pickup) != 2:
        raise RuntimeError("pickup_all_click must contain x and y")
    with ForegroundBlock(hwnd, max_wait=0.6):
        clicker.click(hwnd, int(pickup[0]), int(pickup[1]), times=1)
    print(f"[HERB] clicked pickup all at ({pickup[0]},{pickup[1]})")
    ctx.clock.sleep(random.uniform(0.5, 0.9))
    return True


def _travel_to_map_click(ctx, hwnd: int, clicker: HumanClicker, cfg: dict, point, digit_templates, label: str):
    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, "tab", hold=0.15)
        ctx.clock.sleep(float(cfg.get("open_route_wait", 0.8)))
        clicker.click(hwnd, int(point[0]), int(point[1]), times=1)
        ctx.clock.sleep(float(cfg.get("direct_map_click_wait", 0.35)))
        ctx.input.press(hwnd, "tab", hold=0.15)
    print(f"[MOVE] {label} direct map click=({point[0]},{point[1]})")
    return _wait_for_coordinate_stable(ctx, hwnd, cfg, digit_templates, label)


def _gather_visible_leaves(
    ctx,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    label: str,
    digit_templates,
    leaf_template,
    harvest_template,
    verification_template,
    mount_template,
    on_harvest=None,
):
    max_herbs = max(1, int(cfg.get("max_herbs_per_route_point", 6)))
    gathered = 0
    needs_mount_restore = False

    for attempt in range(1, max_herbs + 1):
        if ctx.control.stop:
            break
        if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template):
            if ctx.control.stop:
                break

        leaf_point, leaf_score = _find_leaf(grab_client(hwnd), leaf_template, cfg)
        if leaf_point is None:
            print(f"[HERB] {label} no minimap leaf, score={leaf_score:.3f}, move on")
            if needs_mount_restore:
                _ensure_mounted(ctx, hwnd, cfg, mount_template, verification_template)
                needs_mount_restore = False
            break

        print(
            f"[HERB] {label} minimap leaf #{attempt} at {leaf_point}, "
            f"score={leaf_score:.3f}"
        )
        leaf_offset = cfg.get("leaf_click_offset", [3, 3])
        if not isinstance(leaf_offset, (list, tuple)) or len(leaf_offset) != 2:
            leaf_offset = [3, 3]
        leaf_click = (
            int(leaf_point[0]) + int(leaf_offset[0]),
            int(leaf_point[1]) + int(leaf_offset[1]),
        )
        with ForegroundBlock(hwnd, max_wait=0.6):
            clicker.click(hwnd, leaf_click[0], leaf_click[1], times=1)
        print(
            f"[HERB] {label} clicked minimap leaf at {leaf_click} "
            f"offset=({leaf_offset[0]},{leaf_offset[1]})"
        )
        _wait_for_coordinate_stable(ctx, hwnd, cfg, digit_templates, f"{label}-leaf-{attempt}")
        leaf_settle = random.uniform(
            float(cfg.get("leaf_arrival_settle_min", 2.0)),
            float(cfg.get("leaf_arrival_settle_max", 3.0)),
        )
        print(f"[HERB] {label} leaf arrival settle {leaf_settle:.1f}s")
        ctx.clock.sleep(leaf_settle)

        harvested = _harvest_at_center(
            ctx,
            hwnd,
            clicker,
            cfg,
            harvest_template,
            verification_template,
            mount_template,
        )
        needs_mount_restore = True
        if not harvested:
            print(f"[HERB] {label} leaf #{attempt} no pickup window, stop this point")
            _ensure_mounted(ctx, hwnd, cfg, mount_template, verification_template)
            needs_mount_restore = False
            break

        gathered += 1
        if on_harvest is not None:
            on_harvest()
        if attempt < max_herbs:
            print(f"[HERB] {label} rescan minimap before mounting")
            ctx.clock.sleep(
                random.uniform(
                    float(cfg.get("leaf_rescan_wait_min", 0.5)),
                    float(cfg.get("leaf_rescan_wait_max", 0.9)),
                )
            )
    else:
        print(f"[HERB] {label} reached per-point limit={max_herbs}")
        if needs_mount_restore and not ctx.control.stop:
            _ensure_mounted(ctx, hwnd, cfg, mount_template, verification_template)

    print(f"[HERB] {label} gathered={gathered}")
    return gathered


def run(ctx):
    cfg = ctx.config or {}
    scene = str(cfg.get("scene", "shilin")).lower()
    route_type = str(cfg.get("route_type", "game_coordinate")).lower()
    if route_type == "client_map_click":
        route_files = cfg.get("map_click_route_files", {}) or {}
        route_file = str(route_files.get(scene) or f"config/{scene}_map_clicks.txt")
    else:
        route_files = cfg.get("route_files", {}) or {}
        route_file = str(route_files.get(scene) or f"config/{scene}.txt")
    route = _load_route(route_file)
    start_index = int(cfg.get("route_start_index", 1))
    if not 1 <= start_index <= len(route):
        raise RuntimeError(
            f"采药路线起始点超出范围: {start_index}，有效范围为 1..{len(route)}"
        )
    digit_templates = route_helpers._load_optional_templates(cfg.get("coord_templates", {}))
    templates_cfg = cfg.get("templates", {}) or {}
    leaf_template = _load_template(templates_cfg.get("herb_leaf"))
    harvest_template = _load_template(templates_cfg.get("harvest_dialog"))
    mount_template = _load_template(templates_cfg.get("mount_icon"))
    verification_template = herb_verification.load_template(cfg)
    gather_method = str(cfg.get("gather_method", "leaf_search")).lower()
    center_require_leaf = bool(cfg.get("center_click_require_leaf", True))
    if gather_method == "center_click" and center_require_leaf and leaf_template is None:
        raise RuntimeError("中心点击采药已启用小地图检查，但缺少模板: templates/herb_leaf.png")
    move_mode = str(cfg.get("coord_move_method", "map_click")).lower()
    calibrations = cfg.get("map_click_calibrations", {}) or {}
    map_click_calibration = calibrations.get(scene)
    if move_mode == "map_click" and route_helpers._coord_to_map_click(route[0], cfg, map_click_calibration) is None:
        raise RuntimeError(
            f"采药模式缺少 {scene} 的地图点击标定，请配置 "
            f"map_click_calibrations.{scene} 的两个坐标点"
        )
    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.09)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.03)), float(cfg.get("hover_max", 0.09))),
    )
    count_notebook = HerbCountNotebook(
        str(cfg.get("herb_count_notebook", "logs/herb_count_notebook.tsv")),
        bool(cfg.get("herb_count_enabled", False)),
    )

    print("[*] gather_herbs started: F8/Pause start-pause, F9 stop")
    print(f"[*] scene={scene}, route={route_file}, points={len(route)}")
    print(f"[*] first cycle starts at point {start_index}")
    print(f"[*] route_type={route_type}")
    print(f"[*] movement={move_mode}")
    print(f"[*] gather_method={gather_method}")
    print(f"[*] leaf detector={'template' if leaf_template is not None else 'HSV color'}")
    if count_notebook.enabled:
        print(f"[*] herb count enabled: file={count_notebook.path}")
    if not digit_templates:
        raise RuntimeError("采药模式未加载到坐标数字模板")

    cycle = 0
    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.2)
            continue
        cycle += 1
        hwnd = ctx.binder.ensure()
        print(f"[ROUTE] start cycle {cycle}")

        cycle_start_index = start_index if cycle == 1 else 1
        cycle_route = route[cycle_start_index - 1 :]
        for index, coord in enumerate(cycle_route, start=cycle_start_index):
            if ctx.control.stop:
                break

            if herb_verification.pause_until_resumed(ctx, hwnd, cfg, verification_template):
                if ctx.control.stop:
                    break
            while not ctx.control.running and not ctx.control.stop:
                ctx.clock.sleep(0.2)
            if ctx.control.stop:
                break

            label = f"{scene}-{index}"

            def record_harvest():
                count_notebook.record(scene, index)

            if route_type == "client_map_click":
                _travel_to_map_click(ctx, hwnd, clicker, cfg, coord, digit_templates, label)
            else:
                route_helpers._travel_to_coordinate(
                    ctx,
                    hwnd,
                    clicker,
                    cfg,
                    coord,
                    label,
                    digit_templates,
                    move_mode=move_mode,
                    map_click_calibration=map_click_calibration,
                )
            if gather_method == "center_click":
                if center_require_leaf:
                    _gather_visible_leaves(
                        ctx,
                        hwnd,
                        clicker,
                        cfg,
                        label,
                        digit_templates,
                        leaf_template,
                        harvest_template,
                        verification_template,
                        mount_template,
                        on_harvest=record_harvest,
                    )
                else:
                    success = _harvest_at_center(
                        ctx,
                        hwnd,
                        clicker,
                        cfg,
                        harvest_template,
                        verification_template,
                        mount_template,
                    )
                    if success:
                        record_harvest()
                    print(f"[HERB] {label} {'completed' if success else 'no pickup window'}")
                continue
            if not bool(cfg.get("leaf_detection_enabled", False)):
                print(f"[HERB] {label} movement-only test, skip leaf detection")
                continue
            image = grab_client(hwnd)
            leaf_point, score = _find_leaf(image, leaf_template, cfg)
            if leaf_point is None:
                print(f"[HERB] {label} no leaf, score={score:.3f}")
                continue

            print(f"[HERB] {label} leaf found at {leaf_point}, score={score:.3f}")
            with ForegroundBlock(hwnd, max_wait=0.6):
                clicker.click(hwnd, leaf_point[0], leaf_point[1], times=1)
            _wait_for_coordinate_stable(ctx, hwnd, cfg, digit_templates, label)
            success = _harvest_once(
                ctx,
                hwnd,
                clicker,
                cfg,
                digit_templates,
                harvest_template,
                verification_template,
                mount_template,
            )
            if success:
                record_harvest()

        if not bool(cfg.get("repeat_route", True)):
            print("[ROUTE] route completed")
            return

    print("[*] gather_herbs stopped")
