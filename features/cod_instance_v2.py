import configparser
import os
import random
import re
import time
from dataclasses import dataclass
from glob import glob
from typing import Any

import cv2
import keyboard
import numpy as np

from core.capture_win32 import grab_client
from core.clicker_human import ForegroundBlock, HumanClicker
from core.vision import find_template, find_template_masked


@dataclass
class BotContext:
    binder: Any
    input: Any
    clock: Any
    control: Any
    config: dict


DEFAULT_SCENE_ALIASES = {
    "\u6566\u714c": "dunhuang",
    "\u5d69\u5c71": "songshan",
    "\u5251\u9601": "jiange",
    "\u65e0\u91cf\u5c71": "wuliangshan",
    "\u592a\u6e56": "taihu",
}


LAST_NPC_CANDIDATE = {
    "path": None,
    "adopted": False,
}

LAST_INSTANCE_KILL_DEBUG = {
    "ts": 0.0,
}


def _append_npc_score_log(
    cfg: dict,
    label: str,
    result: str,
    score: float,
    elapsed: float,
    attempts: int,
    mode: str,
    template_name: str = "",
):
    if not bool(cfg.get("npc_score_log_enabled", True)):
        return

    path = str(cfg.get("npc_score_log_path", "debug/npc_score_log.tsv"))
    out_dir = os.path.dirname(path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    exists = os.path.isfile(path)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"{ts}\t{label}\t{result}\t{score:.4f}\t{elapsed:.2f}\t{attempts}\t{mode}\t{template_name}\n"
    )
    with open(path, "a", encoding="utf-8") as f:
        if not exists:
            f.write("timestamp\tlabel\tresult\tscore\telapsed_s\tattempts\tmode\ttemplate\n")
        f.write(line)


def _load_cod_routes(path: str) -> dict[str, list[tuple[int, int]]]:
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
        raise RuntimeError(f"failed to decode cod.ini: {path}") from last_error

    section_name = "\u53cd\u8d3c\u5750\u6807"
    if section_name not in parser:
        raise RuntimeError(f"cod.ini missing [{section_name}] section: {path}")

    routes: dict[str, list[tuple[int, int]]] = {}
    for map_name, raw_points in parser[section_name].items():
        points: list[tuple[int, int]] = []
        for token in raw_points.split("|"):
            token = token.strip()
            if not token:
                continue
            x_str, y_str = token.split(",", 1)
            points.append((int(x_str), int(y_str)))
        routes[map_name] = points

    if not routes:
        raise RuntimeError(f"cod.ini has no usable routes: {path}")

    return routes


def _normalize_scene_routes(routes: dict[str, list[tuple[int, int]]], aliases: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    normalized: dict[str, list[tuple[int, int]]] = {}
    for raw_name, points in routes.items():
        normalized[aliases.get(raw_name, raw_name)] = points
    return normalized


def _load_templates(paths: list[str]) -> list[Any]:
    templates = []
    for path in paths:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"failed to load template: {path}")
        templates.append((path, img))
    return templates


def _discover_npc_templates(cfg: dict) -> list[str]:
    configured = list(cfg.get("templates", {}).get("npc", []) or [])
    if configured:
        return configured

    template_dir = cfg.get("npc_template_dir", "templates")
    patterns = [
        os.path.join(template_dir, "cod_npc*.png"),
        os.path.join(template_dir, "cod_npc_auto*.png"),
    ]

    discovered: list[str] = []
    for pattern in patterns:
        discovered.extend(glob(pattern))

    # preserve order, remove duplicates
    seen = set()
    ordered = []
    for path in sorted(discovered):
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        ordered.append(norm)
    return ordered


def _discover_interact_success_templates(cfg: dict) -> list[str]:
    configured = list(cfg.get("templates", {}).get("npc_interact_success", []) or [])
    if configured:
        return configured

    template_dir = cfg.get("npc_template_dir", "templates")
    if not os.path.isdir(template_dir):
        return []

    discovered = []
    for name in sorted(os.listdir(template_dir)):
        if not name.lower().endswith(".png"):
            continue
        if name.startswith("cod_npc_success"):
            discovered.append(os.path.join(template_dir, name))
    return discovered


def _load_named_templates(path_map: dict[str, str]) -> dict[str, Any]:
    templates: dict[str, Any] = {}
    for name, path in path_map.items():
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"failed to load template: {path}")
        templates[name] = img
    return templates


def _load_optional_templates(path_map: dict[str, str]) -> dict[str, Any]:
    templates: dict[str, Any] = {}
    for name, path in (path_map or {}).items():
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[COORD] Skip unreadable template: {path}")
            continue
        templates[str(name)] = img
    return templates


def _discover_instance_kill_templates(cfg: dict) -> dict[int, str]:
    route = cfg.get("instance_route", []) or []
    allowed_values = {
        int(point["target_kill"])
        for point in route
        if isinstance(point, dict) and "target_kill" in point
    }

    configured = cfg.get("templates", {}).get("instance_kill_counts", {}) or {}
    discovered: dict[int, str] = {}

    for key, path in configured.items():
        try:
            count = int(str(key))
        except ValueError:
            continue
        if allowed_values and count not in allowed_values:
            continue
        full_path = str(path)
        if os.path.isfile(full_path):
            discovered[count] = full_path

    candidate_dirs = [
        cfg.get("instance_kill_template_dir", "templates/instance_kill_counts"),
        cfg.get("npc_template_dir", "templates"),
        "templates",
    ]
    seen_dirs = set()
    for auto_dir in candidate_dirs:
        if not auto_dir:
            continue
        norm_dir = os.path.normpath(str(auto_dir))
        if norm_dir in seen_dirs:
            continue
        seen_dirs.add(norm_dir)

        if not os.path.isdir(auto_dir):
            continue

        for name in sorted(os.listdir(auto_dir)):
            if not name.lower().endswith(".png"):
                continue
            stem = os.path.splitext(name)[0].lower()
            count = None
            if stem.isdigit():
                count = int(stem)
            else:
                m = re.fullmatch(r"number(\d+)", stem)
                if m:
                    count = int(m.group(1))
            if count is None or count in discovered:
                continue
            if allowed_values and count not in allowed_values:
                continue
            discovered[count] = os.path.join(auto_dir, name)

    return discovered


def _load_instance_kill_templates(path_map: dict[int, str]) -> dict[int, Any]:
    templates: dict[int, Any] = {}
    for count, path in path_map.items():
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            print(f"[INSTANCE] Skip unreadable kill-count template: {path}")
            continue
        templates[int(count)] = img
    return templates


def _load_single_template(path: str | None):
    if not path:
        return None
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        print(f"[WARN] failed to load template: {path}")
        return None
    return img


def _click_point(clicks: dict, name: str) -> tuple[int, int]:
    if name not in clicks:
        raise RuntimeError(f"missing clicks.{name}")
    x, y = clicks[name]
    return int(x), int(y)


def _press_alt_m(ctx: BotContext, hwnd: int):
    ctx.input.key_down(hwnd, "alt")
    ctx.clock.sleep(0.03)
    ctx.input.press(hwnd, "m", hold=0.05)
    ctx.clock.sleep(0.02)
    ctx.input.key_up(hwnd, "alt")


def _save_npc_candidate(img, match, cfg: dict):
    crop_w = int(cfg.get("npc_candidate_width", 120))
    crop_h = int(cfg.get("npc_candidate_height", 40))

    x1 = max(0, int(match.x) - crop_w // 2)
    y1 = max(0, int(match.y) - crop_h // 2)
    x2 = min(img.shape[1], x1 + crop_w)
    y2 = min(img.shape[0], y1 + crop_h)
    crop = img[y1:y2, x1:x2]

    out_dir = cfg.get("npc_candidate_dir", "debug/npc_matches")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"npc_candidate_{time.strftime('%Y%m%d_%H%M%S')}.png")
    cv2.imwrite(path, crop)

    LAST_NPC_CANDIDATE["path"] = path
    LAST_NPC_CANDIDATE["adopted"] = False
    print(f"[NPC] Saved candidate template: {path}")


def _save_npc_search_debug(img, roi, cfg: dict, label: str):
    if not bool(cfg.get("npc_debug_save_search_roi", True)):
        return

    if roi is None:
        x1, y1 = 0, 0
        y2, x2 = img.shape[:2]
    else:
        x1, y1, x2, y2 = roi

    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return

    out_dir = cfg.get("npc_search_debug_dir", "debug/npc_search")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")

    crop_path = os.path.join(out_dir, f"{label}_{ts}_crop.png")
    cv2.imwrite(crop_path, crop)
    print(f"[NPC] Saved search ROI crop: {crop_path}")

    if bool(cfg.get("npc_use_yellow_mask", True)):
        lower_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_lower", [15, 80, 140]))
        upper_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_upper", [40, 255, 255]))
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower_hsv, upper_hsv)
        mask_path = os.path.join(out_dir, f"{label}_{ts}_mask.png")
        cv2.imwrite(mask_path, mask)
        print(f"[NPC] Saved search ROI mask: {mask_path}")


def _save_npc_rejected_debug(hwnd: int, cfg: dict, label: str):
    img = grab_client(hwnd)
    roi = cfg.get("npc_label_roi") or cfg.get("npc_roi")
    if roi is not None:
        x1, y1, x2, y2 = tuple(int(v) for v in roi)
        crop = img[y1:y2, x1:x2]
    else:
        crop = img

    out_dir = cfg.get("npc_rejected_debug_dir", "debug/npc_rejected")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"{label}_{ts}.png")
    cv2.imwrite(path, crop)
    print(f"[NPC] Saved rejected detection: {path}")


def _save_interact_success_roi(hwnd: int, cfg: dict, label: str):
    roi = cfg.get("npc_interact_success_roi")
    if not roi:
        return None
    x1, y1, x2, y2 = [int(v) for v in roi]
    img = grab_client(hwnd)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    out_dir = cfg.get("npc_interact_debug_dir", "debug/npc_interact")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"{label}_{ts}.png")
    cv2.imwrite(path, crop)
    print(f"[NPC] Saved interact ROI: {path}")
    return path


def _wait_for_npc_confirmation(cfg: dict, label: str):
    if not bool(cfg.get("npc_confirm_mode", False)):
        return None

    correct_key = str(cfg.get("npc_confirm_correct_key", "f6")).lower()
    wrong_key = str(cfg.get("npc_confirm_wrong_key", "f7")).lower()
    skip_key = str(cfg.get("npc_confirm_skip_key", "f8")).lower()
    print(
        f"[NPC] Confirm result for {label}: "
        f"{correct_key.upper()}=correct, {wrong_key.upper()}=wrong/save, {skip_key.upper()}=skip"
    )

    while True:
        if keyboard.is_pressed(correct_key):
            time.sleep(0.25)
            print(f"[NPC] {label} confirmed correct")
            return True
        if keyboard.is_pressed(wrong_key):
            time.sleep(0.25)
            print(f"[NPC] {label} confirmed wrong")
            return False
        if keyboard.is_pressed(skip_key):
            time.sleep(0.25)
            print(f"[NPC] {label} skipped by user")
            return None
        time.sleep(0.05)


def _wait_for_interact_success(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    success_templates: list[Any],
    label: str,
):
    roi = cfg.get("npc_interact_success_roi")
    if not roi:
        return False
    roi = tuple(int(v) for v in roi)

    timeout = float(cfg.get("npc_interact_success_timeout", 6.0))
    interval = float(cfg.get("npc_interact_success_poll_interval", 0.5))
    threshold = float(cfg.get("npc_interact_success_threshold", 0.82))
    elapsed = 0.0

    # If no template configured yet, still keep the screenshot for later calibration.
    if not success_templates:
        _save_interact_success_roi(hwnd, cfg, f"{label}_no_template")
        return False

    while elapsed <= timeout and not ctx.control.stop:
        img = grab_client(hwnd)
        for path, tpl in success_templates:
            m = find_template(img, tpl, threshold=threshold, roi=roi)
            if m.ok:
                print(f"[NPC] Interact success matched {os.path.basename(path)} score={m.score:.3f}")
                if bool(cfg.get("npc_save_success_hit_debug", True)):
                    _save_interact_success_roi(hwnd, cfg, f"{label}_success")
                return True
        ctx.clock.sleep(interval)
        elapsed += interval
    if bool(cfg.get("npc_save_success_miss_debug", True)):
        _save_interact_success_roi(hwnd, cfg, f"{label}_miss")
    print(f"[NPC] Interact success not confirmed for {label}")
    return False


def _click_enter_instance(ctx: BotContext, hwnd: int, clicker: HumanClicker, cfg: dict):
    clicks = cfg.get("clicks", {})
    if "enter_instance" not in clicks:
        print("[INSTANCE] enter_instance click not configured")
        return False

    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "enter_instance")
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(float(cfg.get("enter_instance_click_wait", 0.5)))

        # optional confirm button if configured
        confirm = clicks.get("confirm_instance")
        if confirm and confirm != [0, 0]:
            cx, cy = int(confirm[0]), int(confirm[1])
            clicker.click(hwnd, cx, cy, times=1)
            ctx.clock.sleep(float(cfg.get("confirm_instance_click_wait", 0.5)))
    print("[INSTANCE] Clicked enter instance")
    return True


def _maybe_adopt_latest_candidate(cfg: dict):
    adopt_key = str(cfg.get("npc_adopt_hotkey", "f7")).lower()
    src_path = LAST_NPC_CANDIDATE.get("path")
    if not src_path or LAST_NPC_CANDIDATE.get("adopted"):
        return
    if not keyboard.is_pressed(adopt_key):
        return

    img = cv2.imread(src_path, cv2.IMREAD_COLOR)
    if img is None:
        print(f"[NPC] Failed to read candidate template: {src_path}")
        return

    out_dir = cfg.get("npc_template_dir", "templates")
    os.makedirs(out_dir, exist_ok=True)
    dst_path = os.path.join(out_dir, f"cod_npc_auto_{time.strftime('%Y%m%d_%H%M%S')}.png")
    cv2.imwrite(dst_path, img)
    LAST_NPC_CANDIDATE["adopted"] = True
    print(f"[NPC] Adopted new template: {dst_path}")
    time.sleep(0.3)


def _match_scene_template(ctx: BotContext, hwnd: int, scene_name: str, scene_templates: dict[str, Any], cfg: dict):
    tpl = scene_templates.get(scene_name)
    if tpl is None:
        print(f"[SCENE] No template configured for {scene_name}, skip verification")
        return True

    roi = cfg.get("scene_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    threshold = float(cfg.get("scene_threshold", 0.9))
    retries = int(cfg.get("scene_match_retries", 3))
    interval = float(cfg.get("scene_match_interval", 2.0))

    for attempt in range(1, retries + 1):
        img = grab_client(hwnd)
        match = find_template(img, tpl, threshold=threshold, roi=roi)
        if match.ok:
            print(f"[SCENE] Verified {scene_name} score={match.score:.3f}")
            return True
        print(f"[SCENE] Verify failed for {scene_name} score={match.score:.3f} ({attempt}/{retries})")
        if attempt < retries:
            ctx.clock.sleep(interval)

    return False


def _wait_for_scene_verification(ctx: BotContext, hwnd: int, scene_name: str, scene_templates: dict[str, Any], cfg: dict):
    tpl = scene_templates.get(scene_name)
    if tpl is None:
        print(f"[SCENE] No template configured for {scene_name}, skip verification")
        return True

    roi = cfg.get("scene_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    threshold = float(cfg.get("scene_threshold", 0.85))
    interval = float(cfg.get("scene_verify_poll_interval", 5))
    max_wait = float(cfg.get("scene_verify_max_wait", cfg.get("scene_travel_wait", 90)))

    elapsed = 0.0
    while not ctx.control.stop:
        img = grab_client(hwnd)
        match = find_template(img, tpl, threshold=threshold, roi=roi)
        if match.ok:
            print(f"[SCENE] Verified {scene_name} score={match.score:.3f} after {elapsed:.1f}s")
            return True

        if max_wait > 0 and elapsed >= max_wait:
            break

        wait_tail = f"{max_wait:.1f}s" if max_wait > 0 else "inf"
        print(f"[SCENE] Waiting for {scene_name}, score={match.score:.3f}, elapsed={elapsed:.1f}s/{wait_tail}")
        if max_wait > 0:
            sleep_for = min(interval, max_wait - elapsed)
            if sleep_for <= 0:
                break
        else:
            sleep_for = interval
        ctx.clock.sleep(sleep_for)
        elapsed += sleep_for

    return False


def _match_scene_once(hwnd: int, scene_name: str, scene_templates: dict[str, Any], cfg: dict) -> tuple[bool, float]:
    tpl = scene_templates.get(scene_name)
    if tpl is None:
        return False, 0.0

    roi = cfg.get("scene_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    threshold = float(cfg.get("scene_threshold", 0.85))
    img = grab_client(hwnd)
    match = find_template(img, tpl, threshold=threshold, roi=roi)
    return bool(match.ok), float(match.score)


def _wait_for_instance_entry_by_map_change(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    scene_templates: dict[str, Any],
    source_map: str,
    label: str,
) -> bool:
    enter_wait = float(cfg.get("enter_instance_wait", 5.0))
    print(f"[INSTANCE] Wait {enter_wait:.1f}s after enter click")
    ctx.clock.sleep(enter_wait)

    matched, score = _match_scene_once(hwnd, source_map, scene_templates, cfg)
    if matched:
        print(f"[INSTANCE] {label} map unchanged ({source_map}) score={score:.3f}")
        return False

    print(f"[INSTANCE] {label} map changed from {source_map}, entry confirmed (score={score:.3f})")
    return True


def _motion_roi_gray(hwnd: int, roi) -> Any:
    img = grab_client(hwnd)
    x1, y1, x2, y2 = roi
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    return cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)


def _mask_coord_text(img_bgr, cfg: dict):
    mode = str(cfg.get("coord_mask_mode", "gray")).lower()

    if mode == "hsv":
        lower = tuple(int(v) for v in cfg.get("coord_text_hsv_lower", [15, 0, 180]))
        upper = tuple(int(v) for v in cfg.get("coord_text_hsv_upper", [179, 80, 255]))
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        return cv2.inRange(hsv, lower, upper)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    threshold = int(cfg.get("coord_gray_threshold", 185))
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    return mask


def _extract_coord_groups(mask):
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    boxes = []
    for idx in range(1, num_labels):
        x, y, w, h, area = stats[idx]
        if area < 3 or h < 5 or w < 1:
            continue
        boxes.append((x, y, w, h))

    if not boxes:
        return []

    boxes.sort(key=lambda item: item[0])
    groups = [[boxes[0]]]
    for box in boxes[1:]:
        prev = groups[-1][-1]
        prev_right = prev[0] + prev[2]
        gap = box[0] - prev_right
        if gap >= 6:
            groups.append([box])
        else:
            groups[-1].append(box)
    return groups


def _normalize_binary_glyph(img, canvas_size=(24, 24), pad=2):
    if img is None or img.size == 0:
        return None

    ys, xs = (img > 0).nonzero()
    if len(xs) == 0 or len(ys) == 0:
        return None

    x1, x2 = xs.min(), xs.max() + 1
    y1, y2 = ys.min(), ys.max() + 1
    glyph = img[y1:y2, x1:x2]
    gh, gw = glyph.shape[:2]
    if gh <= 0 or gw <= 0:
        return None

    canvas_w, canvas_h = canvas_size
    usable_w = max(1, canvas_w - pad * 2)
    usable_h = max(1, canvas_h - pad * 2)
    scale = min(usable_w / gw, usable_h / gh)
    new_w = max(1, int(round(gw * scale)))
    new_h = max(1, int(round(gh * scale)))

    resized = cv2.resize(glyph, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
    _, resized = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)

    canvas = np.zeros((canvas_h, canvas_w), dtype=np.uint8)

    off_x = (canvas_w - new_w) // 2
    off_y = (canvas_h - new_h) // 2
    canvas[off_y:off_y + new_h, off_x:off_x + new_w] = resized
    return canvas


def _recognize_group_digits(mask, group_boxes, digit_templates: dict[str, Any], cfg: dict):
    if not group_boxes or not digit_templates:
        return None

    char_boxes = sorted(group_boxes, key=lambda item: item[0])
    digits = []
    for idx, box in enumerate(char_boxes, start=1):
        bx, by, bw, bh = box
        char = mask[by:by + bh, bx:bx + bw]
        if char.size == 0:
            return None
        norm_char = _normalize_binary_glyph(char)
        if norm_char is None:
            return None
        best_digit = None
        best_score = -1.0
        for digit, tpl in digit_templates.items():
            tpl_mask = _mask_coord_text(tpl, cfg)
            if cv2.countNonZero(tpl_mask) == 0:
                continue
            norm_tpl = _normalize_binary_glyph(tpl_mask)
            if norm_tpl is None:
                continue
            resized_bin = norm_char
            tpl_bin = norm_tpl

            # IoU is much better than plain template correlation for similar digits like 6/8.
            inter = cv2.countNonZero(cv2.bitwise_and(resized_bin, tpl_bin))
            union = cv2.countNonZero(cv2.bitwise_or(resized_bin, tpl_bin))
            iou = (inter / union) if union else 0.0

            # Keep a small correlation component as a tiebreaker.
            corr = float(cv2.matchTemplate(resized_bin, tpl_bin, cv2.TM_CCOEFF_NORMED)[0][0])
            score = iou * 0.85 + corr * 0.15
            if score > best_score:
                best_score = float(score)
                best_digit = digit
        if best_digit is None:
            return None
        if bool(cfg.get("coord_debug_digit_scores", False)):
            print(f"[COORD] digit#{idx} -> {best_digit} score={best_score:.3f}")
        digits.append(best_digit)
    return "".join(digits)


def _read_current_coord(ctx: BotContext, hwnd: int, cfg: dict, digit_templates: dict[str, Any]):
    roi = tuple(int(v) for v in cfg.get("current_coord_roi", [894, 33, 948, 46]))
    img = grab_client(hwnd)
    x1, y1, x2, y2 = roi
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return None

    mask = _mask_coord_text(crop, cfg)
    groups = _extract_coord_groups(mask)
    if len(groups) < 2:
        return None

    x_str = _recognize_group_digits(mask, groups[0], digit_templates, cfg)
    y_str = _recognize_group_digits(mask, groups[1], digit_templates, cfg)
    if not x_str or not y_str:
        return None

    try:
        return int(x_str), int(y_str)
    except ValueError:
        return None


def _save_coord_debug(crop, mask, label: str):
    out_dir = os.path.join("debug", "coord_read")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    crop_path = os.path.join(out_dir, f"{label}_{ts}_crop.png")
    mask_path = os.path.join(out_dir, f"{label}_{ts}_mask.png")
    cv2.imwrite(crop_path, crop)
    cv2.imwrite(mask_path, mask)
    print(f"[COORD] saved debug crop: {crop_path}")
    print(f"[COORD] saved debug mask: {mask_path}")


def _wait_for_target_coordinate(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    target: tuple[int, int],
    digit_templates: dict[str, Any],
    label: str,
    npc_templates: list[Any] | None = None,
):
    if not bool(cfg.get("coord_verify_enabled", True)):
        return False
    if not digit_templates:
        return False

    max_wait = float(cfg.get("coord_verify_max_wait", 30))
    interval = float(cfg.get("coord_verify_poll_interval", 2))
    tolerance = int(cfg.get("coord_tolerance", 3))
    elapsed = 0.0
    move_npc_hits = 0
    moving_npc = None
    scan_enabled = bool(cfg.get("npc_scan_during_move_enabled", False)) and bool(npc_templates)
    scan_min_elapsed = float(cfg.get("npc_scan_during_move_min_elapsed", 0.5))
    scan_threshold = float(cfg.get("npc_scan_during_move_threshold", cfg.get("npc_threshold", 0.82)))
    scan_plain_threshold = float(cfg.get("npc_scan_during_move_plain_threshold", cfg.get("npc_plain_threshold", scan_threshold)))
    scan_confirm_hits = int(cfg.get("npc_scan_during_move_confirm_hits", 2))

    while (max_wait <= 0 or elapsed <= max_wait) and not ctx.control.stop:
        roi = tuple(int(v) for v in cfg.get("current_coord_roi", [894, 33, 948, 46]))
        img = grab_client(hwnd)
        x1, y1, x2, y2 = roi
        crop = img[y1:y2, x1:x2]
        mask = _mask_coord_text(crop, cfg) if crop.size else None
        current = None
        if crop.size and mask is not None:
            groups = _extract_coord_groups(mask)
            if len(groups) >= 2:
                x_str = _recognize_group_digits(mask, groups[0], digit_templates, cfg)
                y_str = _recognize_group_digits(mask, groups[1], digit_templates, cfg)
                if x_str and y_str:
                    try:
                        current = (int(x_str), int(y_str))
                    except ValueError:
                        current = None

        if current is not None:
            dx = abs(current[0] - int(target[0]))
            dy = abs(current[1] - int(target[1]))
            print(f"[COORD] {label} current={current} target={target} delta=({dx},{dy})")
            if dx <= tolerance and dy <= tolerance:
                print(f"[COORD] {label} arrived by coordinate check")
                return True, None
        else:
            print(f"[COORD] {label} coordinate read failed, retry")
            if bool(cfg.get("coord_debug_on_fail", True)):
                _save_coord_debug(crop, mask, label)

        if scan_enabled and elapsed >= scan_min_elapsed:
            m = _scan_npc_once(img, npc_templates, cfg, threshold=scan_threshold, plain_threshold=scan_plain_threshold)
            if m is not None:
                move_npc_hits += 1
                moving_npc = m
                print(
                    f"[NPC] {label} moving-scan hit score={float(m.score):.3f} "
                    f"({move_npc_hits}/{scan_confirm_hits})"
                )
                if move_npc_hits >= scan_confirm_hits:
                    print(f"[NPC] {label} moving-scan confirmed, stop-and-confirm")
                    return False, moving_npc
            else:
                move_npc_hits = 0
                moving_npc = None

        sleep_for = interval if max_wait <= 0 else min(interval, max_wait - elapsed)
        if sleep_for <= 0 and max_wait > 0:
            break
        ctx.clock.sleep(sleep_for)
        elapsed += sleep_for

    print(f"[COORD] {label} coordinate check timed out")
    return False, moving_npc


def _wait_for_coordinate_stable(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    digit_templates: dict[str, Any],
    label: str,
) -> bool:
    timeout = float(cfg.get("npc_moving_coord_stable_timeout", 1.8))
    interval = float(cfg.get("npc_moving_coord_stable_interval", 0.3))
    stable_hits_required = int(cfg.get("npc_moving_coord_stable_hits", 2))

    elapsed = 0.0
    stable_hits = 0
    last_coord = None

    while elapsed <= timeout and not ctx.control.stop:
        cur = _read_current_coord(ctx, hwnd, cfg, digit_templates)
        if cur is None:
            stable_hits = 0
            last_coord = None
        else:
            if last_coord is not None and cur == last_coord:
                stable_hits += 1
            else:
                stable_hits = 1
            last_coord = cur
            print(f"[COORD] {label} stable-check current={cur} hits={stable_hits}/{stable_hits_required}")
            if stable_hits >= stable_hits_required:
                return True

        ctx.clock.sleep(interval)
        elapsed += interval

    print(f"[COORD] {label} stable-check timeout")
    return False


def _wait_for_motion_to_settle(ctx: BotContext, hwnd: int, cfg: dict, label: str):
    roi = tuple(int(v) for v in cfg.get("move_verify_roi", [320, 180, 704, 520]))
    interval = float(cfg.get("move_verify_poll_interval", 2.0))
    max_wait = float(cfg.get("move_to_xy_max_wait", cfg.get("move_to_xy_wait", 10)))
    threshold = float(cfg.get("move_still_threshold", 2.2))
    stable_required = int(cfg.get("move_stable_count", 2))
    min_wait = float(cfg.get("move_min_wait", 4.0))

    stable_count = 0
    elapsed = 0.0
    prev = None

    print(f"[MOVE] Waiting for arrival at {label}, max {max_wait:.1f}s")
    while elapsed <= max_wait and not ctx.control.stop:
        current = _motion_roi_gray(hwnd, roi)
        if current is None:
            ctx.clock.sleep(interval)
            elapsed += interval
            continue

        if prev is not None:
            diff = cv2.absdiff(current, prev)
            mean_diff = float(diff.mean())
            if elapsed >= min_wait and mean_diff <= threshold:
                stable_count += 1
                print(f"[MOVE] {label} looks stable diff={mean_diff:.2f} ({stable_count}/{stable_required})")
                if stable_count >= stable_required:
                    return True
            else:
                stable_count = 0
                print(f"[MOVE] {label} still moving diff={mean_diff:.2f}")

        prev = current
        ctx.clock.sleep(interval)
        elapsed += interval

    print(f"[MOVE] Arrival check timed out for {label}, continue anyway")
    return False


def _travel_to_scene(ctx: BotContext, hwnd: int, clicker: HumanClicker, cfg: dict, scene_name: str, scene_templates: dict[str, Any]):
    scene_clicks = cfg.get("scene_clicks", {})
    clicks = cfg.get("clicks", {})

    if scene_name not in scene_clicks:
        print(f"[SCENE] No scene click configured for {scene_name}, assume already there")
        return True

    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, "tab", hold=0.05)
        ctx.clock.sleep(1)

        _press_alt_m(ctx, hwnd)
        ctx.clock.sleep(float(cfg.get("open_map_wait", 1.5)))

        x, y = scene_clicks[scene_name]
        clicker.click(hwnd, int(x), int(y), times=1)
        ctx.clock.sleep(float(cfg.get("scene_click_wait", 1.5)))

        if "ditu_click" in clicks:
            x, y = _click_point(clicks, "ditu_click")
            clicker.click(hwnd, x, y, times=1)
            ctx.clock.sleep(float(cfg.get("scene_anchor_wait", 1.0)))

        if "confirm_btn" in clicks:
            x, y = _click_point(clicks, "confirm_btn")
            clicker.click(hwnd, x, y, times=1)

    print(f"[SCENE] Travel to {scene_name}, start verification polling")
    return _wait_for_scene_verification(ctx, hwnd, scene_name, scene_templates, cfg)


def _solve_linear_mapping(c1: tuple[int, int], p1: tuple[int, int], c2: tuple[int, int], p2: tuple[int, int]):
    x1, y1 = float(c1[0]), float(c1[1])
    x2, y2 = float(c2[0]), float(c2[1])
    px1, py1 = float(p1[0]), float(p1[1])
    px2, py2 = float(p2[0]), float(p2[1])
    if abs(x2 - x1) < 1e-9 or abs(y2 - y1) < 1e-9:
        return None
    sx = (px2 - px1) / (x2 - x1)
    bx = px1 - sx * x1
    sy = (py2 - py1) / (y2 - y1)
    by = py1 - sy * y1
    return sx, bx, sy, by


def _coord_to_map_click(coord: tuple[int, int], cfg: dict, cal: dict | None = None) -> tuple[int, int] | None:
    if cal is None:
        cal = cfg.get("map_click_calibration", {}) or {}
    c1 = cal.get("coord_1")
    p1 = cal.get("click_1")
    c2 = cal.get("coord_2")
    p2 = cal.get("click_2")
    if not (isinstance(c1, (list, tuple)) and isinstance(c2, (list, tuple)) and isinstance(p1, (list, tuple)) and isinstance(p2, (list, tuple))):
        return None
    if not (len(c1) == len(c2) == len(p1) == len(p2) == 2):
        return None

    solved = _solve_linear_mapping(
        (int(c1[0]), int(c1[1])),
        (int(p1[0]), int(p1[1])),
        (int(c2[0]), int(c2[1])),
        (int(p2[0]), int(p2[1])),
    )
    if solved is None:
        return None
    sx, bx, sy, by = solved
    x, y = int(coord[0]), int(coord[1])
    return int(round(sx * x + bx)), int(round(sy * y + by))


def _travel_to_coordinate(
    ctx: BotContext,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    coord: tuple[int, int],
    label: str,
    digit_templates: dict[str, Any] | None = None,
    move_mode: str | None = None,
    map_click_calibration: dict | None = None,
    npc_templates: list[Any] | None = None,
):
    clicks = cfg.get("clicks", {})
    target_x, target_y = coord
    method = str(move_mode or cfg.get("coord_move_method", "map_click")).lower()

    with ForegroundBlock(hwnd, max_wait=0.6):
        if bool(cfg.get("pre_route_press_i", True)):
            ctx.input.press(hwnd, "i", hold=float(cfg.get("pre_route_i_hold", 0.05)))
            ctx.clock.sleep(float(cfg.get("pre_route_i_wait", 0.2)))

        ctx.input.press(hwnd, "tab", hold=0.15)
        ctx.clock.sleep(float(cfg.get("open_route_wait", 1.0)))

        if method == "map_click":
            map_click = _coord_to_map_click(coord, cfg, cal=map_click_calibration)
            if map_click is None:
                print("[MOVE] map_click calibration missing/invalid, fallback to input mode")
                method = "input"
            else:
                mx, my = map_click
                clicker.click(hwnd, mx, my, times=1)
                ctx.clock.sleep(float(cfg.get("map_click_wait", 0.25)))
                if bool(cfg.get("map_click_press_move_btn", False)) and "move_btn" in clicks:
                    x, y = _click_point(clicks, "move_btn")
                    clicker.click(hwnd, x, y, times=1)
                    ctx.clock.sleep(float(cfg.get("map_click_move_btn_wait", 0.2)))

        if method != "map_click":
            if "coord_input" not in clicks or "move_btn" not in clicks:
                raise RuntimeError("missing clicks.coord_input or clicks.move_btn")
            x, y = _click_point(clicks, "coord_input")
            clicker.click(hwnd, x, y, times=1)
            ctx.clock.sleep(0.8)

            ctx.input.type_text(hwnd, str(target_x))
            ctx.clock.sleep(0.4)
            ctx.input.press(hwnd, "enter", hold=0.15)
            ctx.clock.sleep(0.4)
            ctx.input.type_text(hwnd, str(target_y))
            ctx.clock.sleep(0.4)

            x, y = _click_point(clicks, "move_btn")
            clicker.click(hwnd, x, y, times=1)
            ctx.clock.sleep(0.5)
        ctx.input.press(hwnd, "tab", hold=0.15)

    print(f"[MOVE] Travel to {label}: ({target_x},{target_y}) via {method}")
    coord_ok, moving_npc = _wait_for_target_coordinate(
        ctx,
        hwnd,
        cfg,
        coord,
        digit_templates or {},
        label,
        npc_templates=npc_templates,
    )
    if not coord_ok and not bool(cfg.get("coord_verify_enabled", True)):
        _wait_for_motion_to_settle(ctx, hwnd, cfg, label)
    return {"arrived": coord_ok, "moving_npc": moving_npc}


def _find_npc(ctx: BotContext, hwnd: int, templates: list[Any], cfg: dict, label: str = ""):
    threshold = float(cfg.get("npc_threshold", 0.82))
    plain_threshold = float(cfg.get("npc_plain_threshold", threshold))
    timeout = float(cfg.get("search_timeout", 12))
    interval = float(cfg.get("search_interval", 1.0))
    fast_fail_enabled = bool(cfg.get("npc_fast_fail_enabled", True))
    fast_fail_after = float(cfg.get("npc_fast_fail_after", 3.0))
    fast_fail_score_ceiling = float(cfg.get("npc_fast_fail_score_ceiling", 0.55))
    very_fast_fail_enabled = bool(cfg.get("npc_very_fast_fail_enabled", True))
    very_fast_fail_after = float(cfg.get("npc_very_fast_fail_after", 1.2))
    very_fast_fail_score_ceiling = float(cfg.get("npc_very_fast_fail_score_ceiling", 0.38))
    fast_fail_min_attempts = int(cfg.get("npc_fast_fail_min_attempts", 2))
    quick_scan_hard_cap_enabled = bool(cfg.get("npc_quick_scan_hard_cap_enabled", True))
    quick_scan_hard_cap_after = float(cfg.get("npc_quick_scan_hard_cap_after", 1.8))
    quick_scan_hard_cap_min_attempts = int(cfg.get("npc_quick_scan_hard_cap_min_attempts", 2))

    roi = cfg.get("npc_label_roi") or cfg.get("npc_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    lower_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_lower", [15, 80, 140]))
    upper_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_upper", [40, 255, 255]))
    use_yellow_mask = bool(cfg.get("npc_use_yellow_mask", True))

    elapsed = 0.0
    debug_saved = False
    best_seen = 0.0
    attempts = 0
    while elapsed <= timeout and not ctx.control.stop:
        attempts += 1
        _maybe_adopt_latest_candidate(cfg)
        img = grab_client(hwnd)
        if not debug_saved:
            _save_npc_search_debug(img, roi, cfg, "npc_search")
            debug_saved = True
        for path, tpl in templates:
            if use_yellow_mask:
                match = find_template_masked(
                    img,
                    tpl,
                    threshold=threshold,
                    roi=roi,
                    lower_hsv=lower_hsv,
                    upper_hsv=upper_hsv,
                )
            else:
                match = find_template(img, tpl, threshold=plain_threshold, roi=roi)
            best_seen = max(best_seen, float(match.score))

            if match.ok:
                mode = "masked" if use_yellow_mask else "plain"
                print(f"[NPC] Matched {os.path.basename(path)} via {mode} score={match.score:.3f}")
                # _save_npc_candidate(img, match, cfg)
                # _append_npc_score_log(
                #     cfg,
                #     label=label,
                #     result="success",
                #     score=float(match.score),
                #     elapsed=float(elapsed),
                #     attempts=int(attempts),
                #     mode=mode,
                #     template_name=os.path.basename(path),
                # )
                return match

            if use_yellow_mask and bool(cfg.get("npc_enable_plain_fallback", False)):
                plain_match = find_template(img, tpl, threshold=plain_threshold, roi=roi)
                best_seen = max(best_seen, float(plain_match.score))
                if plain_match.ok:
                    print(f"[NPC] Matched {os.path.basename(path)} via plain fallback score={plain_match.score:.3f}")
                    _save_npc_candidate(img, plain_match, cfg)
                    _append_npc_score_log(
                        cfg,
                        label=label,
                        result="success",
                        score=float(plain_match.score),
                        elapsed=float(elapsed),
                        attempts=int(attempts),
                        mode="plain_fallback",
                        template_name=os.path.basename(path),
                    )
                    return plain_match

        if (
            very_fast_fail_enabled
            and attempts >= fast_fail_min_attempts
            and elapsed >= very_fast_fail_after
            and best_seen <= very_fast_fail_score_ceiling
        ):
            print(
                f"[NPC] Very-fast-fail no target: attempts={attempts} elapsed={elapsed:.1f}s "
                f"best_score={best_seen:.3f} <= ceiling={very_fast_fail_score_ceiling:.3f}"
            )
            _append_npc_score_log(
                cfg,
                label=label,
                result="fail_very_fast",
                score=float(best_seen),
                elapsed=float(elapsed),
                attempts=int(attempts),
                mode="masked" if use_yellow_mask else "plain",
            )
            return None

        if (
            quick_scan_hard_cap_enabled
            and attempts >= quick_scan_hard_cap_min_attempts
            and elapsed >= quick_scan_hard_cap_after
        ):
            print(
                f"[NPC] Quick-cap no target: attempts={attempts} elapsed={elapsed:.1f}s "
                f"best_score={best_seen:.3f}"
            )
            _append_npc_score_log(
                cfg,
                label=label,
                result="fail_quick_cap",
                score=float(best_seen),
                elapsed=float(elapsed),
                attempts=int(attempts),
                mode="masked" if use_yellow_mask else "plain",
            )
            return None

        if (
            fast_fail_enabled
            and attempts >= fast_fail_min_attempts
            and elapsed >= fast_fail_after
            and best_seen <= fast_fail_score_ceiling
        ):
            print(
                f"[NPC] Fast-fail no target: attempts={attempts} elapsed={elapsed:.1f}s best_score={best_seen:.3f} "
                f"<= ceiling={fast_fail_score_ceiling:.3f}"
            )
            _append_npc_score_log(
                cfg,
                label=label,
                result="fail_fast",
                score=float(best_seen),
                elapsed=float(elapsed),
                attempts=int(attempts),
                mode="masked" if use_yellow_mask else "plain",
            )
            return None

        ctx.clock.sleep(interval)
        elapsed += interval

    _append_npc_score_log(
        cfg,
        label=label,
        result="fail_timeout",
        score=float(best_seen),
        elapsed=float(elapsed),
        attempts=int(attempts),
        mode="masked" if use_yellow_mask else "plain",
    )
    return None


def _scan_npc_once(img, templates: list[Any], cfg: dict, threshold: float | None = None, plain_threshold: float | None = None):
    if img is None:
        return None
    roi = cfg.get("npc_label_roi") or cfg.get("npc_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    use_yellow_mask = bool(cfg.get("npc_use_yellow_mask", True))
    lower_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_lower", [15, 80, 140]))
    upper_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_upper", [40, 255, 255]))
    masked_threshold = float(threshold if threshold is not None else cfg.get("npc_threshold", 0.82))
    plain_threshold_v = float(
        plain_threshold
        if plain_threshold is not None
        else cfg.get("npc_plain_threshold", cfg.get("npc_threshold", 0.82))
    )

    best_ok = None
    best_score = -1.0
    for _path, tpl in templates:
        if use_yellow_mask:
            m = find_template_masked(
                img,
                tpl,
                threshold=masked_threshold,
                roi=roi,
                lower_hsv=lower_hsv,
                upper_hsv=upper_hsv,
            )
        else:
            m = find_template(img, tpl, threshold=plain_threshold_v, roi=roi)

        if m.ok and float(m.score) > best_score:
            best_ok = m
            best_score = float(m.score)

        if use_yellow_mask and bool(cfg.get("npc_enable_plain_fallback", False)):
            p = find_template(img, tpl, threshold=plain_threshold_v, roi=roi)
            if p.ok and float(p.score) > best_score:
                best_ok = p
                best_score = float(p.score)

    return best_ok


def _execute_actions(ctx: BotContext, hwnd: int, clicker: HumanClicker, cfg: dict, actions: list[dict], tag: str):
    clicks = cfg.get("clicks", {})

    for index, action in enumerate(actions, start=1):
        if ctx.control.stop:
            break

        action_type = action.get("type")
        if action_type == "sleep":
            ctx.clock.sleep(float(action.get("duration", 1.0)))
            continue

        with ForegroundBlock(hwnd, max_wait=0.6):
            if action_type == "key":
                ctx.input.press(hwnd, action["key"], hold=float(action.get("hold", 0.05)))
            elif action_type == "combo":
                ctx.input.press_combo(
                    hwnd,
                    action["key"],
                    modifiers=action.get("modifiers", []),
                    hold=float(action.get("hold", 0.05)),
                )
            elif action_type == "text":
                ctx.input.type_text(hwnd, str(action["text"]))
            elif action_type == "click":
                if "point" in action:
                    x, y = _click_point(clicks, action["point"])
                else:
                    x, y = int(action["x"]), int(action["y"])
                clicker.click(
                    hwnd,
                    x,
                    y,
                    times=int(action.get("times", 1)),
                    long_hold=action.get("long_hold"),
                )
            else:
                raise RuntimeError(f"{tag} action not supported: {action_type}")

        gap = float(action.get("gap", 0.5))
        print(f"[{tag}] Action {index}/{len(actions)}: {action_type}")
        ctx.clock.sleep(gap)


def _mask_blue_digits(img_bgr, cfg: dict):
    lower = tuple(int(v) for v in cfg.get("instance_kill_hsv_lower", [90, 80, 80]))
    upper = tuple(int(v) for v in cfg.get("instance_kill_hsv_upper", [135, 255, 255]))
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv, lower, upper)


def _save_instance_kill_debug(crop, mask, cfg: dict, label: str):
    if not bool(cfg.get("instance_kill_debug_save", False)):
        return

    now = time.time()
    interval = float(cfg.get("instance_kill_debug_interval", 1.0))
    if now - float(LAST_INSTANCE_KILL_DEBUG["ts"]) < interval:
        return
    LAST_INSTANCE_KILL_DEBUG["ts"] = now

    out_dir = cfg.get("instance_kill_debug_dir", "debug/instance_kill")
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    ms = int((now - int(now)) * 1000)
    suffix = f"{label}_{ts}_{ms:03d}" if label else f"{ts}_{ms:03d}"
    cv2.imwrite(os.path.join(out_dir, f"{suffix}_crop.png"), crop)
    cv2.imwrite(os.path.join(out_dir, f"{suffix}_mask.png"), mask)


def _read_instance_kill_count(
    hwnd: int,
    cfg: dict,
    kill_templates: dict[int, Any],
    label: str = "",
) -> tuple[int | None, float, float]:
    roi = cfg.get("instance_kill_roi", [552, 80, 568, 96])
    x1, y1, x2, y2 = (int(v) for v in roi)

    img = grab_client(hwnd)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return None, 0.0

    use_blue_mask = bool(cfg.get("instance_kill_use_blue_mask", True))
    target = _mask_blue_digits(crop, cfg) if use_blue_mask else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _save_instance_kill_debug(crop, target, cfg, label)
    target_h, target_w = target.shape[:2]
    min_target_nonzero = int(cfg.get("instance_kill_min_nonzero_pixels_target", 6))
    target_nonzero = int(cv2.countNonZero(target))
    if target_nonzero < min_target_nonzero:
        return None, 0.0, 0.0

    best_value = None
    best_score = -1.0
    second_best = -1.0
    min_tpl_nonzero = int(cfg.get("instance_kill_min_nonzero_pixels_template", 6))

    for value, tpl in kill_templates.items():
        probe = _mask_blue_digits(tpl, cfg) if use_blue_mask else cv2.cvtColor(tpl, cv2.COLOR_BGR2GRAY)
        if int(cv2.countNonZero(probe)) < min_tpl_nonzero:
            continue
        th, tw = probe.shape[:2]
        if th > target_h or tw > target_w:
            continue
        result = cv2.matchTemplate(target, probe, cv2.TM_CCOEFF_NORMED)
        score = float(result.max())
        if score > second_best:
            second_best = score
        if score > best_score:
            second_best = best_score
            best_score = score
            best_value = int(value)

    threshold = float(cfg.get("instance_kill_threshold", 0.70))
    margin = float(best_score - max(second_best, 0.0))
    min_margin = float(cfg.get("instance_kill_min_score_margin", 0.03))
    if best_value is not None and margin < min_margin:
        return None, max(best_score, 0.0), max(margin, 0.0)
    if best_value is None or best_score < threshold:
        return None, max(best_score, 0.0), max(margin, 0.0)
    return best_value, best_score, max(margin, 0.0)


def _wait_for_instance_kill_target(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    kill_templates: dict[int, Any],
    target: int,
    label: str,
    max_wait: float | None = None,
) -> bool:
    if max_wait is None:
        max_wait = float(cfg.get("instance_kill_max_wait", 30))
    interval = float(cfg.get("instance_kill_poll_interval", 0.8))
    confirm_hits = int(cfg.get("instance_kill_confirm_hits", 2))
    min_accept_elapsed = float(cfg.get("instance_kill_min_accept_elapsed", 2.0))
    max_over_target = int(cfg.get("instance_kill_max_over_target", 3))
    hit_streak = 0

    elapsed = 0.0
    while elapsed <= max_wait and not ctx.control.stop:
        current, score, margin = _read_instance_kill_count(hwnd, cfg, kill_templates, label=label)
        if current is None:
            hit_streak = 0
            print(f"[INSTANCE] {label} kill-count unreadable score={score:.3f} margin={margin:.3f}, retry")
        else:
            print(f"[INSTANCE] {label} kill-count={current}, target={target}, score={score:.3f}, margin={margin:.3f}")
            if current >= target and current <= target + max_over_target and elapsed >= min_accept_elapsed:
                hit_streak += 1
                print(f"[INSTANCE] {label} kill target hit streak: {hit_streak}/{confirm_hits}")
                if hit_streak >= confirm_hits:
                    return True
            else:
                if current > target + max_over_target:
                    print(
                        f"[INSTANCE] {label} ignore suspicious high count {current} "
                        f"(target={target}, max_over={max_over_target})"
                    )
                hit_streak = 0
        ctx.clock.sleep(interval)
        elapsed += interval

    print(f"[INSTANCE] {label} kill target wait timed out: target={target}")
    return False


def _default_instance_route() -> list[dict[str, Any]]:
    return [
        {"name": "instance-1", "x": 98, "y": 80, "target_kill": 2},
        {"name": "instance-2", "x": 108, "y": 41, "target_kill": 6},
        {"name": "instance-3", "x": 100, "y": 25, "target_kill": 10},
        {"name": "instance-4", "x": 58, "y": 23, "target_kill": 15},
        {"name": "instance-5", "x": 28, "y": 24, "target_kill": 20},
        {"name": "instance-6", "x": 41, "y": 79, "target_kill": 25},
        {"name": "instance-7", "x": 24, "y": 100},
    ]


def _wait_for_return_scene(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    scene_templates: dict[str, Any],
    source_map: str,
    label: str,
) -> bool:
    interval = float(cfg.get("instance_return_poll_interval", 1.0))
    max_wait = float(cfg.get("instance_return_max_wait", 0))
    elapsed = 0.0

    while not ctx.control.stop:
        matched, score = _match_scene_once(hwnd, source_map, scene_templates, cfg)
        if matched:
            print(f"[INSTANCE] {label} returned to {source_map} score={score:.3f}")
            return True

        print(f"[INSTANCE] {label} waiting return to {source_map}, score={score:.3f}")
        ctx.clock.sleep(interval)
        elapsed += interval
        if max_wait > 0 and elapsed >= max_wait:
            print(f"[INSTANCE] {label} return-scene wait timed out at {elapsed:.1f}s")
            return False
    return False


def _wait_for_instance_end_marker(ctx: BotContext, hwnd: int, cfg: dict, end_template, label: str) -> bool:
    if end_template is None:
        print("[INSTANCE] End marker template not loaded, skip marker wait")
        return False

    roi = cfg.get("instance_end_roi", [449, 132, 561, 158])
    roi = tuple(int(v) for v in roi)
    threshold = float(cfg.get("instance_end_threshold", 0.90))
    interval = float(cfg.get("instance_end_poll_interval", 0.5))
    max_wait = float(cfg.get("instance_end_max_wait", 120))

    elapsed = 0.0
    while elapsed <= max_wait and not ctx.control.stop:
        img = grab_client(hwnd)
        m = find_template(img, end_template, threshold=threshold, roi=roi)
        if m.ok:
            print(f"[INSTANCE] {label} end-marker detected score={m.score:.3f} at {elapsed:.1f}s")
            return True
        ctx.clock.sleep(interval)
        elapsed += interval

    print(f"[INSTANCE] {label} end-marker wait timed out ({max_wait:.1f}s)")
    return False


def _watch_instance_end_and_return(
    ctx: BotContext,
    hwnd: int,
    cfg: dict,
    clicker: HumanClicker,
    end_template,
    scene_templates: dict[str, Any],
    source_map: str,
    label: str,
) -> bool:
    # Optional anti-occlusion key before last-stage detection.
    if bool(cfg.get("instance_last_press_f12", True)):
        with ForegroundBlock(hwnd, max_wait=0.6):
            ctx.input.press(hwnd, "f12", hold=float(cfg.get("npc_f12_hold", 0.05)))
        ctx.clock.sleep(float(cfg.get("npc_f12_wait", 0.5)))

    interval = float(cfg.get("instance_last_watch_interval", 0.5))
    max_wait = float(cfg.get("instance_last_watch_max_wait", cfg.get("instance_return_max_wait", 0)))
    elapsed = 0.0
    i_pressed = False

    end_roi = tuple(int(v) for v in cfg.get("instance_end_roi", [449, 132, 561, 158]))
    end_threshold = float(cfg.get("instance_end_threshold", 0.90))

    while not ctx.control.stop:
        # First priority: if we are already back on source map, we are done.
        matched_scene, scene_score = _match_scene_once(hwnd, source_map, scene_templates, cfg)
        if matched_scene:
            if not i_pressed:
                with ForegroundBlock(hwnd, max_wait=0.6):
                    ctx.input.press(hwnd, "i", hold=float(cfg.get("instance_start_follow_hold", 0.05)))
                ctx.clock.sleep(float(cfg.get("instance_start_follow_wait", 0.3)))
                print(f"[INSTANCE] {label} returned map detected, pressed I (late)")
            print(f"[INSTANCE] {label} return confirmed score={scene_score:.3f}")
            return True

        # End marker is now a helper signal, not a blocking gate.
        if (not i_pressed) and end_template is not None:
            img = grab_client(hwnd)
            m = find_template(img, end_template, threshold=end_threshold, roi=end_roi)
            if m.ok:
                with ForegroundBlock(hwnd, max_wait=0.6):
                    ctx.input.press(hwnd, "i", hold=float(cfg.get("instance_start_follow_hold", 0.05)))
                ctx.clock.sleep(float(cfg.get("instance_start_follow_wait", 0.3)))
                i_pressed = True
                print(f"[INSTANCE] {label} end-marker detected score={m.score:.3f}, pressed I")

        if max_wait > 0 and elapsed >= max_wait:
            print(f"[INSTANCE] {label} last-stage watch timeout at {elapsed:.1f}s")
            return False

        if int(elapsed * 10) % int(max(1, round(5.0 / max(interval, 0.1))) * 1) == 0:
            print(f"[INSTANCE] {label} watching end/return... elapsed={elapsed:.1f}s")

        ctx.clock.sleep(interval)
        elapsed += interval

    return False


def _run_instance_timeout_recovery(
    ctx: BotContext,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    digit_templates: dict[str, Any],
    route: list[dict[str, Any]],
    instance_calibration: dict | None,
    start_index: int,
    end_index: int,
):
    if not route:
        return

    start_from = max(1, min(int(start_index), len(route)))
    end_at = max(start_from, min(int(end_index), len(route)))
    hold_secs = float(cfg.get("instance_timeout_recover_hold", 5.0))
    arrive_settle = float(cfg.get("instance_timeout_recover_arrive_settle", 2.0))

    print(
        f"[INSTANCE] Timeout recovery: restart from point {start_from} to {end_at}, "
        f"arrive_settle={arrive_settle:.1f}s hold={hold_secs:.1f}s"
    )
    for index in range(start_from, end_at + 1):
        if ctx.control.stop:
            break
        point = route[index - 1]
        coord = (int(point["x"]), int(point["y"]))
        label = str(point.get("name", f"instance-{index}"))

        _travel_to_coordinate(
            ctx,
            hwnd,
            clicker,
            cfg,
            coord,
            f"{label}-recovery",
            digit_templates,
            move_mode=str(cfg.get("instance_coord_move_method", "input")),
            map_click_calibration=instance_calibration,
        )

        if arrive_settle > 0:
            ctx.clock.sleep(arrive_settle)
        with ForegroundBlock(hwnd, max_wait=0.6):
            ctx.input.press(hwnd, "k", hold=float(cfg.get("instance_stop_follow_hold", 0.05)))
        ctx.clock.sleep(float(cfg.get("instance_stop_follow_wait", 0.3)))
        print(f"[INSTANCE] {label} recovery reached, pressed K")

        ctx.clock.sleep(hold_secs)
        with ForegroundBlock(hwnd, max_wait=0.6):
            ctx.input.press(hwnd, "i", hold=float(cfg.get("instance_start_follow_hold", 0.05)))
        ctx.clock.sleep(float(cfg.get("instance_start_follow_wait", 0.3)))
        print(f"[INSTANCE] {label} recovery hold done, pressed I")


def _run_dungeon_route(
    ctx: BotContext,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    digit_templates: dict[str, Any],
    instance_kill_templates: dict[int, Any],
    instance_end_template,
    scene_templates: dict[str, Any],
    source_map: str,
):
    route = cfg.get("instance_route", []) or _default_instance_route()
    instance_calibration = cfg.get("instance_map_click_calibration")
    if not route:
        print("[INSTANCE] No instance route configured, skipping instance flow")
        return
    if not instance_kill_templates:
        print("[INSTANCE] No kill-count templates loaded, skipping instance flow")
        return

    print(f"[INSTANCE] Start route with {len(route)} points")
    route_len = len(route)
    timeout_streak = 0
    index = 1
    while index <= route_len:
        point = route[index - 1]
        if ctx.control.stop:
            break

        coord = (int(point["x"]), int(point["y"]))
        label = str(point.get("name", f"instance-{index}"))
        is_last = index == route_len

        _travel_to_coordinate(
            ctx,
            hwnd,
            clicker,
            cfg,
            coord,
            label,
            digit_templates,
            move_mode=str(cfg.get("instance_coord_move_method", "input")),
            map_click_calibration=instance_calibration,
        )

        settle_min = float(cfg.get("instance_arrive_settle_min", 2.0))
        settle_max = float(cfg.get("instance_arrive_settle_max", 3.0))
        settle_for = random.uniform(min(settle_min, settle_max), max(settle_min, settle_max))
        print(f"[INSTANCE] {label} arrived, settle {settle_for:.1f}s before stop follow")
        ctx.clock.sleep(settle_for)

        with ForegroundBlock(hwnd, max_wait=0.6):
            ctx.input.press(hwnd, "k", hold=float(cfg.get("instance_stop_follow_hold", 0.05)))
        ctx.clock.sleep(float(cfg.get("instance_stop_follow_wait", 0.3)))
        print(f"[INSTANCE] {label} reached, pressed K to stop follow")

        if is_last:
            _watch_instance_end_and_return(
                ctx,
                hwnd,
                cfg,
                clicker,
                instance_end_template,
                scene_templates,
                source_map,
                label,
            )
            break

        if "target_kill" not in point:
            print(f"[INSTANCE] {label} missing target_kill, skip kill wait")
        else:
            target_kill = int(point["target_kill"])
            point_max_wait = float(point.get("max_wait", cfg.get("instance_kill_max_wait", 30)))
            ok = _wait_for_instance_kill_target(
                ctx,
                hwnd,
                cfg,
                instance_kill_templates,
                target_kill,
                label,
                max_wait=point_max_wait,
            )
            if ok:
                timeout_streak = 0
            else:
                timeout_streak += 1
                print(f"[INSTANCE] {label} timeout streak={timeout_streak}")
                if (
                    bool(cfg.get("instance_timeout_recover_enabled", True))
                    and timeout_streak >= int(cfg.get("instance_timeout_recover_streak", 2))
                ):
                    recover_start = int(cfg.get("instance_timeout_recover_from_index", 1))
                    _run_instance_timeout_recovery(
                        ctx,
                        hwnd,
                        clicker,
                        cfg,
                        digit_templates,
                        route,
                        instance_calibration,
                        start_index=recover_start,
                        end_index=index,
                    )
                    timeout_streak = 0
                    index += 1
                    continue

        with ForegroundBlock(hwnd, max_wait=0.6):
            ctx.input.press(hwnd, "i", hold=float(cfg.get("instance_start_follow_hold", 0.05)))
        ctx.clock.sleep(float(cfg.get("instance_start_follow_wait", 0.3)))
        print(f"[INSTANCE] {label} done, pressed I to start follow")
        index += 1

    exit_wait = float(cfg.get("instance_exit_wait", 0))
    if exit_wait > 0:
        print(f"[INSTANCE] Route finished, wait {exit_wait:.1f}s for exit")
        ctx.clock.sleep(exit_wait)


def _seconds_until_next_hour(now=None) -> int:
    now = now or time.localtime()
    return (59 - now.tm_min) * 60 + (60 - now.tm_sec)


def _wait_until_next_hour(ctx: BotContext, cfg: dict):
    if not bool(cfg.get("wait_until_hour_on_start", True)):
        return

    remaining = _seconds_until_next_hour()
    if remaining <= 0:
        return

    print(f"[START] Waiting at first coordinate for next hour: {remaining}s")
    while remaining > 0 and not ctx.control.stop:
        _maybe_adopt_latest_candidate(cfg)

        if not ctx.control.running:
            ctx.clock.sleep(0.2)
            continue

        chunk = min(remaining, 5)
        if remaining <= 60 or remaining % 60 == 0:
            print(f"[START] {remaining}s remaining")
        ctx.clock.sleep(chunk)
        remaining -= chunk

    if not ctx.control.stop:
        print("[START] Top of the hour reached, begin scanning")


def _handle_coordinate(
    ctx: BotContext,
    hwnd: int,
    clicker: HumanClicker,
    cfg: dict,
    npc_templates,
    scene_templates: dict[str, Any],
    digit_templates: dict[str, Any],
    instance_kill_templates: dict[int, Any],
    instance_end_template,
    map_name: str,
    index: int,
    coord: tuple[int, int],
    do_travel: bool = True,
):
    moving_npc_match = None
    if do_travel:
        travel_result = _travel_to_coordinate(
            ctx,
            hwnd,
            clicker,
            cfg,
            coord,
            f"{map_name}-{index}",
            digit_templates,
            npc_templates=npc_templates,
        )
        moving_npc_match = travel_result.get("moving_npc") if isinstance(travel_result, dict) else None

    f12_done = False

    npc_match = None
    if moving_npc_match is not None:
        quick_click_x = int(moving_npc_match.x + int(cfg.get("npc_click_offset_x", 0)))
        quick_click_y = int(moving_npc_match.y + int(cfg.get("npc_click_offset_y", 28)))
        with ForegroundBlock(hwnd, max_wait=0.6):
            clicker.click(
                hwnd,
                quick_click_x,
                quick_click_y,
                times=int(cfg.get("npc_moving_quick_click_times", 1)),
            )
        print(f"[NPC] {map_name}-{index} moving-scan quick click at ({quick_click_x}, {quick_click_y})")
        ctx.clock.sleep(float(cfg.get("npc_moving_quick_click_wait", 0.15)))

        coord_stable = _wait_for_coordinate_stable(
            ctx,
            hwnd,
            cfg,
            digit_templates,
            f"{map_name}-{index}",
        )
        if coord_stable:
            if bool(cfg.get("npc_press_f12_before_search", True)):
                with ForegroundBlock(hwnd, max_wait=0.6):
                    ctx.input.press(hwnd, "f12", hold=float(cfg.get("npc_f12_hold", 0.05)))
                ctx.clock.sleep(float(cfg.get("npc_f12_wait", 0.5)))
                f12_done = True

            static_timeout = float(cfg.get("npc_moving_static_confirm_timeout", 1.2))
            static_interval = float(cfg.get("npc_moving_static_confirm_interval", 0.3))
            elapsed = 0.0
            while elapsed <= static_timeout and not ctx.control.stop:
                img = grab_client(hwnd)
                m = _scan_npc_once(img, npc_templates, cfg)
                if m is not None:
                    npc_match = m
                    print(f"[NPC] {map_name}-{index} static-confirm after moving-scan score={float(m.score):.3f}")
                    break
                ctx.clock.sleep(static_interval)
                elapsed += static_interval
        else:
            print(f"[NPC] {map_name}-{index} coordinate not stable after moving-scan")
        if npc_match is None:
            print(f"[NPC] {map_name}-{index} moving-scan not confirmed in static check")

    if npc_match is None:
        if bool(cfg.get("npc_press_f12_before_search", True)) and not f12_done:
            with ForegroundBlock(hwnd, max_wait=0.6):
                ctx.input.press(hwnd, "f12", hold=float(cfg.get("npc_f12_hold", 0.05)))
            ctx.clock.sleep(float(cfg.get("npc_f12_wait", 0.5)))
        npc_match = _find_npc(ctx, hwnd, npc_templates, cfg, label=f"{map_name}-{index}")
    if npc_match is None:
        print(f"[NPC] {map_name}-{index} not found by template search")
    else:
        print(f"[NPC] {map_name}-{index} matched candidate at ({npc_match.x}, {npc_match.y})")

    auto_mode = not bool(cfg.get("npc_confirm_mode", False))
    if auto_mode:
        if npc_match is None:
            return False
        confirm = True
        print(f"[NPC] {map_name}-{index} auto mode: proceed with template match")
    else:
        confirm = _wait_for_npc_confirmation(cfg, f"{map_name}-{index}")

    if confirm is True:
        if npc_match is None:
            print(f"[NPC] {map_name}-{index} confirmed but no template match was available")
            return True

        click_x = int(npc_match.x + int(cfg.get("npc_click_offset_x", 0)))
        click_y = int(npc_match.y + int(cfg.get("npc_click_offset_y", 28)))
        with ForegroundBlock(hwnd, max_wait=0.6):
            clicker.click(hwnd, click_x, click_y, times=int(cfg.get("npc_click_times", 1)))
        print(f"[NPC] Click at ({click_x}, {click_y})")
        ctx.clock.sleep(float(cfg.get("npc_interact_wait", 2.0)))

        dialogue_actions = cfg.get("dialogue_actions", [])
        if dialogue_actions:
            _execute_actions(ctx, hwnd, clicker, cfg, dialogue_actions, tag="DIALOG")

        entered = _click_enter_instance(ctx, hwnd, clicker, cfg)
        if not entered:
            return False

        entry_ok = _wait_for_instance_entry_by_map_change(
            ctx,
            hwnd,
            cfg,
            scene_templates,
            map_name,
            f"{map_name}-{index}",
        )
        if not entry_ok:
            return False

        _run_dungeon_route(
            ctx,
            hwnd,
            clicker,
            cfg,
            digit_templates,
            instance_kill_templates,
            instance_end_template,
            scene_templates,
            map_name,
        )

        cooldown = float(cfg.get("post_instance_cooldown", 3))
        print(f"[LOOP] Cooldown {cooldown:.1f}s")
        ctx.clock.sleep(cooldown)
        return True
    if confirm is False:
        _save_npc_rejected_debug(hwnd, cfg, f"{map_name}-{index}")
        return False
    return False


def run(ctx: BotContext):
    cfg = ctx.config
    cod_ini_path = cfg.get("cod_ini", "cod.ini")
    scene_aliases = dict(DEFAULT_SCENE_ALIASES)
    scene_aliases.update(cfg.get("scene_aliases", {}))
    routes = _normalize_scene_routes(_load_cod_routes(cod_ini_path), scene_aliases)

    map_order = cfg.get("map_order") or list(routes.keys())
    start_map = cfg.get("start_map")
    if start_map:
        if start_map not in map_order:
            raise RuntimeError(f"start_map not found in map_order: {start_map}")
        start_idx = map_order.index(start_map)
        map_order = map_order[start_idx:] + map_order[:start_idx]
    npc_template_paths = _discover_npc_templates(cfg)
    if not npc_template_paths:
        raise RuntimeError("No NPC templates found. Add templates.npc or put cod_npc*.png under templates/")
    npc_templates = _load_templates(npc_template_paths)
    scene_templates = _load_named_templates(cfg.get("templates", {}).get("scenes", {}))
    digit_templates = _load_optional_templates(cfg.get("coord_templates", {}))
    instance_kill_template_paths = _discover_instance_kill_templates(cfg)
    instance_kill_templates = _load_instance_kill_templates(instance_kill_template_paths)
    instance_end_template_path = cfg.get("templates", {}).get("instance_end", "templates/end.png")
    instance_end_template = _load_single_template(instance_end_template_path)

    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )

    print(f"[*] cod_instance start | maps={map_order}")
    print(f"[*] loaded npc templates: {len(npc_template_paths)}")
    print(f"[*] loaded coord templates: {len(digit_templates)}")
    print(f"[*] loaded instance kill templates: {len(instance_kill_templates)}")
    print(f"[*] instance end template: {'loaded' if instance_end_template is not None else 'missing'}")
    print("[*] F8 pause/resume, F9 stop")
    print(f"[*] After an NPC match, press {str(cfg.get('npc_adopt_hotkey', 'F7')).upper()} to adopt the latest candidate template")

    startup_prepared = False
    skip_first_point_once = False
    skip_scene_once_for = None

    while not ctx.control.stop:
        _maybe_adopt_latest_candidate(cfg)
        if not ctx.control.running:
            ctx.clock.sleep(0.1)
            continue

        hwnd = ctx.binder.ensure()

        if not startup_prepared and map_order:
            first_map = map_order[0]
            first_points = routes.get(first_map, [])
            if first_points:
                print(f"[START] Move to first map first coordinate: {first_map}-1")
                ok = _travel_to_scene(ctx, hwnd, clicker, cfg, first_map, scene_templates)
                if ok:
                    _travel_to_coordinate(ctx, hwnd, clicker, cfg, first_points[0], f"{first_map}-1", digit_templates)
                    _wait_until_next_hour(ctx, cfg)
                    if ctx.control.stop:
                        break
                    _handle_coordinate(
                        ctx,
                        hwnd,
                        clicker,
                        cfg,
                        npc_templates,
                        scene_templates,
                        digit_templates,
                        instance_kill_templates,
                        instance_end_template,
                        first_map,
                        1,
                        first_points[0],
                        do_travel=False,
                    )
                    skip_first_point_once = True
                    skip_scene_once_for = first_map
                else:
                    print(f"[START] Failed to verify first map {first_map}")
            startup_prepared = True

        for map_name in map_order:
            if ctx.control.stop:
                break

            if map_name not in routes:
                print(f"[WARN] Map missing from cod.ini: {map_name}")
                continue

            print(f"[MAP] Patrol {map_name} with {len(routes[map_name])} coordinates")
            if skip_scene_once_for == map_name:
                print(f"[MAP] Already in {map_name}, skip world-map transfer once")
                skip_scene_once_for = None
            else:
                ok = _travel_to_scene(ctx, hwnd, clicker, cfg, map_name, scene_templates)
                if not ok:
                    print(f"[MAP] Failed to verify map {map_name}, skip")
                    continue

            for index, coord in enumerate(routes[map_name], start=1):
                if ctx.control.stop:
                    break

                while not ctx.control.running and not ctx.control.stop:
                    _maybe_adopt_latest_candidate(cfg)
                    ctx.clock.sleep(0.1)

                if skip_first_point_once and map_name == map_order[0] and index == 1:
                    skip_first_point_once = False
                    continue

                _handle_coordinate(
                    ctx,
                    hwnd,
                    clicker,
                    cfg,
                    npc_templates,
                    scene_templates,
                    digit_templates,
                    instance_kill_templates,
                    instance_end_template,
                    map_name,
                    index,
                    coord,
                    do_travel=True,
                )
