import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capture_win32 import grab_client
from core.clicker_human import HumanClicker
from core.hotkeys import RunControl
from core.input_win32 import InputController
from core.timing import HumanClock
from core.window import WindowBinder
from features.cod_instance import _match_scene_template, _travel_to_scene


WINDOW_TITLE_DEFAULT = "《新天龙八部》 0.08.0207 (原始一区:江湖梦)"


def load_profile(config_path: str, profile_name: str) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if profile_name not in data:
        raise RuntimeError(f"找不到 profile: {profile_name}")
    return data[profile_name]


def save_roi(hwnd: int, roi: tuple[int, int, int, int], output_path: str):
    img = grab_client(hwnd)
    x1, y1, x2, y2 = roi
    crop = img[y1:y2, x1:x2]

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    import cv2

    cv2.imwrite(str(output), crop)
    print(f"[SAVE] {output}")


def main():
    parser = argparse.ArgumentParser(description="测试反贼模块的场景传送，并截取地图名模板")
    parser.add_argument("--title", default=WINDOW_TITLE_DEFAULT, help="游戏窗口标题")
    parser.add_argument("--config", default="config/profiles_cod_v2.yaml", help="配置文件路径")
    parser.add_argument("--profile", default="cod_instance_default", help="profile 名称")
    parser.add_argument("--save-to-templates", action="store_true", help="成功进入场景后直接覆盖保存到 templates.scenes 对应路径")
    args = parser.parse_args()

    cfg = load_profile(args.config, args.profile)

    binder = WindowBinder(args.title)
    input_ctl = InputController()
    clock = HumanClock(jitter=float(cfg.get("jitter", 0.10)))
    control = RunControl()
    control.running = True

    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )

    scene_templates_cfg = cfg.get("templates", {}).get("scenes", {})
    scene_roi = tuple(int(v) for v in cfg.get("scene_roi", [867, 15, 955, 29]))

    ctx = SimpleNamespace(
        binder=binder,
        input=input_ctl,
        clock=clock,
        control=control,
        config=cfg,
    )
    hwnd = binder.ensure()

    print(f"[*] 测试窗口: {args.title}")
    print(f"[*] 测试顺序: {cfg.get('map_order', [])}")
    print(f"[*] ROI: {scene_roi}")

    for scene_name in cfg.get("map_order", []):
        print("\n" + "=" * 60)
        print(f"[TEST] 开始测试场景: {scene_name}")
        print("=" * 60)

        ok = _travel_to_scene(ctx, hwnd, clicker, cfg, scene_name, {})
        if not ok:
            print(f"[TEST] 场景 {scene_name} 传送流程返回失败")
            continue

        template_target = scene_templates_cfg.get(scene_name)
        if args.save_to_templates and template_target:
            output_path = template_target
        else:
            output_path = f"debug/scene_templates/{scene_name}.png"

        save_roi(hwnd, scene_roi, output_path)

        if template_target and Path(template_target).exists():
            from features.cod_instance import _load_named_templates

            templates = _load_named_templates({scene_name: template_target})
            verified = _match_scene_template(ctx, hwnd, scene_name, templates, cfg)
            print(f"[VERIFY] {scene_name}: {'PASS' if verified else 'FAIL'}")
        else:
            print(f"[VERIFY] {scene_name}: 已截图，等待下轮使用模板校验")


if __name__ == "__main__":
    main()
