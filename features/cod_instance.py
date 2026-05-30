import configparser
import os
import time
from dataclasses import dataclass
from typing import Any

import cv2
import keyboard

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
    "敦煌": "dunhuang",
    "嵩山": "songshan",
    "剑阁": "jiange",
    "无量山": "wuliangshan",
    "太湖": "taihu",
}


_LAST_NPC_CANDIDATE = {
    "path": None,
    "adopted": False,
}


def _load_cod_routes(path: str) -> dict[str, list[tuple[int, int]]]:
    parser = configparser.ConfigParser()
    parser.optionxform = str

    with open(path, "r", encoding="utf-8") as f:
        parser.read_file(f)

    if "反贼坐标" not in parser:
        raise RuntimeError(f"cod.ini 缺少 [反贼坐标] 段: {path}")

    routes: dict[str, list[tuple[int, int]]] = {}
    for map_name, raw_points in parser["反贼坐标"].items():
        points: list[tuple[int, int]] = []
        for token in raw_points.split("|"):
            token = token.strip()
            if not token:
                continue
            x_str, y_str = token.split(",", 1)
            points.append((int(x_str), int(y_str)))
        routes[map_name] = points

    if not routes:
        raise RuntimeError(f"cod.ini 中没有可用坐标: {path}")

    return routes


def _normalize_scene_routes(routes: dict[str, list[tuple[int, int]]], aliases: dict[str, str]) -> dict[str, list[tuple[int, int]]]:
    normalized: dict[str, list[tuple[int, int]]] = {}
    for raw_name, points in routes.items():
        scene_id = aliases.get(raw_name, raw_name)
        normalized[scene_id] = points
    return normalized


def _load_templates(paths: list[str]) -> list[Any]:
    templates = []
    for path in paths:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"模板加载失败: {path}")
        templates.append((path, img))
    return templates


def _load_named_templates(path_map: dict[str, str]) -> dict[str, Any]:
    templates: dict[str, Any] = {}
    for name, path in path_map.items():
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError(f"模板加载失败: {path}")
        templates[name] = img
    return templates


def _click_point(clicks: dict, name: str) -> tuple[int, int]:
    if name not in clicks:
        raise RuntimeError(f"配置缺少 clicks.{name}")
    x, y = clicks[name]
    return int(x), int(y)


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

    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"npc_candidate_{ts}.png")
    cv2.imwrite(path, crop)

    _LAST_NPC_CANDIDATE["path"] = path
    _LAST_NPC_CANDIDATE["adopted"] = False
    print(f"[NPC] 已保存候选模板: {path}")
    return path


def _maybe_adopt_latest_candidate(cfg: dict):
    adopt_key = str(cfg.get("npc_adopt_hotkey", "f7")).lower()
    src_path = _LAST_NPC_CANDIDATE.get("path")
    if not src_path or _LAST_NPC_CANDIDATE.get("adopted"):
        return

    if not keyboard.is_pressed(adopt_key):
        return

    adopt_dir = cfg.get("npc_template_dir", "templates")
    os.makedirs(adopt_dir, exist_ok=True)

    ts = time.strftime("%Y%m%d_%H%M%S")
    dst_path = os.path.join(adopt_dir, f"cod_npc_auto_{ts}.png")

    img = cv2.imread(src_path, cv2.IMREAD_COLOR)
    if img is None:
        print(f"[NPC] 收编失败，无法读取候选模板: {src_path}")
        return

    cv2.imwrite(dst_path, img)
    _LAST_NPC_CANDIDATE["adopted"] = True
    print(f"[NPC] 已收编新模板: {dst_path}")
    time.sleep(0.3)


def _press_alt_m(ctx: BotContext, hwnd: int):
    ctx.input.key_down(hwnd, "alt")
    ctx.clock.sleep(0.03)
    ctx.input.press(hwnd, "m", hold=0.05)
    ctx.clock.sleep(0.02)
    ctx.input.key_up(hwnd, "alt")


def _match_scene_template(ctx: BotContext, hwnd: int, scene_name: str, scene_templates: dict[str, Any], cfg: dict):
    tpl = scene_templates.get(scene_name)
    if tpl is None:
        print(f"[SCENE] 未配置地图 {scene_name} 的模板，跳过到达校验")
        return True

    roi = cfg.get("scene_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    threshold = float(cfg.get("scene_threshold", 0.85))
    retries = int(cfg.get("scene_match_retries", 3))
    interval = float(cfg.get("scene_match_interval", 2.0))

    for attempt in range(1, retries + 1):
        img = grab_client(hwnd)
        match = find_template(img, tpl, threshold=threshold, roi=roi)
        if match.ok:
            print(f"[SCENE] 已进入 {scene_name} score={match.score:.3f}")
            return True

        print(f"[SCENE] {scene_name} 校验失败 score={match.score:.3f} ({attempt}/{retries})")
        if attempt < retries:
            ctx.clock.sleep(interval)

    return False


def _travel_to_scene(ctx: BotContext, hwnd: int, clicker: HumanClicker, cfg: dict, scene_name: str, scene_templates: dict[str, Any]):
    scene_clicks = cfg.get("scene_clicks", {})
    clicks = cfg.get("clicks", {})

    if scene_name not in scene_clicks:
        print(f"[SCENE] 未配置地图 {scene_name} 的传送坐标，默认已在当前地图")
        return

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

    wait_time = float(cfg.get("scene_travel_wait", 15))
    print(f"[SCENE] 前往地图 {scene_name}，等待 {wait_time:.1f}s")
    ctx.clock.sleep(wait_time)
    return _match_scene_template(ctx, hwnd, scene_name, scene_templates, cfg)


def _travel_to_coordinate(ctx: BotContext, hwnd: int, clicker: HumanClicker, cfg: dict, coord: tuple[int, int], label: str):
    clicks = cfg.get("clicks", {})
    if "coord_input" not in clicks or "move_btn" not in clicks:
        raise RuntimeError("配置缺少坐标输入所需的 clicks.coord_input / clicks.move_btn")

    target_x, target_y = coord

    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, "tab", hold=0.15)
        ctx.clock.sleep(float(cfg.get("open_route_wait", 1.0)))

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

    wait_time = float(cfg.get("move_to_xy_wait", 10))
    print(f"[MOVE] 前往 {label}: ({target_x},{target_y})，等待 {wait_time:.1f}s")
    ctx.clock.sleep(wait_time)


def _find_npc(ctx: BotContext, hwnd: int, templates: list[Any], cfg: dict):
    threshold = float(cfg.get("npc_threshold", 0.82))
    timeout = float(cfg.get("search_timeout", 12))
    interval = float(cfg.get("search_interval", 1.0))

    roi = cfg.get("npc_label_roi") or cfg.get("npc_roi")
    if roi is not None:
        roi = tuple(int(v) for v in roi)

    lower_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_lower", [15, 80, 140]))
    upper_hsv = tuple(int(v) for v in cfg.get("npc_text_hsv_upper", [40, 255, 255]))
    use_yellow_mask = bool(cfg.get("npc_use_yellow_mask", True))

    elapsed = 0.0
    while elapsed <= timeout and not ctx.control.stop:
        _maybe_adopt_latest_candidate(cfg)
        img = grab_client(hwnd)
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
                match = find_template(img, tpl, threshold=threshold, roi=roi)
            if match.ok:
                print(f"[NPC] 找到造反恶贼模板 {os.path.basename(path)} score={match.score:.3f}")
                _save_npc_candidate(img, match, cfg)
                return match
        ctx.clock.sleep(interval)
        elapsed += interval

    return None


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
                raise RuntimeError(f"{tag} 动作不支持: {action_type}")

        gap = float(action.get("gap", 0.5))
        print(f"[{tag}] 执行动作 {index}/{len(actions)}: {action_type}")
        ctx.clock.sleep(gap)


def _run_dungeon_route(ctx: BotContext, hwnd: int, clicker: HumanClicker, cfg: dict):
    waypoints = cfg.get("dungeon_waypoints", [])
    if not waypoints:
        print("[INSTANCE] 未配置副本内坐标，跳过副本路线")
        return

    print(f"[INSTANCE] 开始副本路线，共 {len(waypoints)} 个点")
    for index, point in enumerate(waypoints, start=1):
        if ctx.control.stop:
            break

        coord = (int(point["x"]), int(point["y"]))
        label = point.get("name", f"副本点{index}")
        _travel_to_coordinate(ctx, hwnd, clicker, cfg, coord, label)

        wait_time = float(point.get("fight_wait", cfg.get("fight_wait", 20)))
        print(f"[INSTANCE] {label} 清怪等待 {wait_time:.1f}s")
        ctx.clock.sleep(wait_time)

        actions = point.get("actions", [])
        if actions:
            _execute_actions(ctx, hwnd, clicker, cfg, actions, tag="INSTANCE")

    exit_wait = float(cfg.get("instance_exit_wait", 30))
    print(f"[INSTANCE] 路线完成，等待副本退出 {exit_wait:.1f}s")
    ctx.clock.sleep(exit_wait)


def run(ctx: BotContext):
    cfg = ctx.config
    cod_ini_path = cfg.get("cod_ini", "cod.ini")
    scene_aliases = dict(DEFAULT_SCENE_ALIASES)
    scene_aliases.update(cfg.get("scene_aliases", {}))
    routes = _normalize_scene_routes(_load_cod_routes(cod_ini_path), scene_aliases)

    map_order = cfg.get("map_order") or list(routes.keys())
    npc_template_paths = cfg.get("templates", {}).get("npc", [])
    if not npc_template_paths:
        raise RuntimeError("请先在配置中填写 templates.npc 模板路径")
    npc_templates = _load_templates(npc_template_paths)
    scene_templates = _load_named_templates(cfg.get("templates", {}).get("scenes", {}))

    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )

    print(f"[*] cod_instance 启动 | maps={map_order}")
    print("[*] F8 暂停/继续，F9 退出")
    print(f"[*] 命中 NPC 后按 {str(cfg.get('npc_adopt_hotkey', 'F7')).upper()} 可收编最近一次候选模板")

    while not ctx.control.stop:
        _maybe_adopt_latest_candidate(cfg)
        if not ctx.control.running:
            ctx.clock.sleep(0.1)
            continue

        hwnd = ctx.binder.ensure()

        for map_name in map_order:
            if ctx.control.stop:
                break

            if map_name not in routes:
                print(f"[WARN] cod.ini 中没有地图 {map_name}，跳过")
                continue

            print(f"[MAP] 开始巡逻地图: {map_name}，共 {len(routes[map_name])} 个坐标")
            ok = _travel_to_scene(ctx, hwnd, clicker, cfg, map_name, scene_templates)
            if not ok:
                print(f"[MAP] 未能确认进入地图 {map_name}，跳过这张地图")
                continue

            for index, coord in enumerate(routes[map_name], start=1):
                if ctx.control.stop:
                    break

                while not ctx.control.running and not ctx.control.stop:
                    _maybe_adopt_latest_candidate(cfg)
                    ctx.clock.sleep(0.1)

                _travel_to_coordinate(ctx, hwnd, clicker, cfg, coord, f"{map_name}-{index}")
                npc_match = _find_npc(ctx, hwnd, npc_templates, cfg)
                if npc_match is None:
                    print(f"[NPC] {map_name}-{index} 未找到造反恶贼，继续下一个坐标")
                    continue

                click_x = int(npc_match.x + int(cfg.get("npc_click_offset_x", 0)))
                click_y = int(npc_match.y + int(cfg.get("npc_click_offset_y", 28)))
                with ForegroundBlock(hwnd, max_wait=0.6):
                    clicker.click(hwnd, click_x, click_y, times=int(cfg.get("npc_click_times", 1)))
                print(f"[NPC] 点击 NPC 位置 ({click_x}, {click_y})")
                ctx.clock.sleep(float(cfg.get("npc_interact_wait", 2.0)))

                dialogue_actions = cfg.get("dialogue_actions", [])
                if dialogue_actions:
                    _execute_actions(ctx, hwnd, clicker, cfg, dialogue_actions, tag="DIALOG")
                else:
                    print("[DIALOG] 未配置对话动作，默认只点击 NPC")

                enter_wait = float(cfg.get("enter_instance_wait", 8))
                print(f"[INSTANCE] 等待进入副本 {enter_wait:.1f}s")
                ctx.clock.sleep(enter_wait)

                _run_dungeon_route(ctx, hwnd, clicker, cfg)

                cooldown = float(cfg.get("post_instance_cooldown", 3))
                print(f"[LOOP] 本次副本结束，冷却 {cooldown:.1f}s")
                ctx.clock.sleep(cooldown)
