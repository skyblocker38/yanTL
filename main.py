import argparse
import yaml

from core.window import WindowBinder
from core.input_win32 import InputController
from core.timing import HumanClock
from core.hotkeys import RunControl, install_hotkeys

from features.macro_combat import BotContext
import features.macro_combat as macro_combat
import features.recover_autofarm as recover_autofarm
import features.recover_autocombat as recover_autocombat
import features.auto_plant as auto_plant
import features.cod_instance_v2 as cod_instance
import features.craft_material as craft_material
import features.kill_switch_combat as kill_switch_combat
import features.gather_herbs as gather_herbs
import features.record_herb_coords as record_herb_coords

FEATURES = {
  "macro_combat": macro_combat.run,
  "recover_autofarm": recover_autofarm.run,
  "recover_autocombat": recover_autocombat.run,
  "auto_plant": auto_plant.run,
  "cod_instance": cod_instance.run,
  "craft_material": craft_material.run,
  "kill_switch_combat": kill_switch_combat.run,
  "gather_herbs": gather_herbs.run,
  "record_herb_coords": record_herb_coords.run,
}


def load_profiles(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="目标窗口标题（完全一致）")
    parser.add_argument("--mode", default="macro_basic", choices=FEATURES.keys())
    parser.add_argument("--profile", default="default", help="profiles.yaml 里的 profile 名称")
    parser.add_argument("--config", default="config/profiles.yaml", help="配置文件路径")
    parser.add_argument("--scene", default=None, choices=["xueyuan", "huanglong", "moya", "gaochang", "qingyuan", "shilin"], help="目标场景")
    parser.add_argument("--from-index", type=int, default=1, help="采药路线起始点编号，1-based，默认 1")
    parser.add_argument("--enable-count", action="store_true", help="开启采药成功次数累计记录")
    parser.add_argument("--count-file", default=None, help="采药计数笔记本路径")
    parser.add_argument(
        "--sickle-handle",
        type=lambda value: int(value, 0),
        default=None,
        help="采药小镰刀光标句柄，支持十进制或 0x 十六进制",
    )
    args = parser.parse_args()

    profiles = load_profiles(args.config)
    if args.profile not in profiles:
        raise RuntimeError(f"找不到 profile: {args.profile}，可用: {list(profiles.keys())}")

    profile = profiles[args.profile]

    if args.scene:
        profile["scene"] = args.scene
    if args.mode == "gather_herbs":
        profile["route_start_index"] = args.from_index
        profile["herb_count_enabled"] = args.enable_count
        if args.count_file:
            profile["herb_count_notebook"] = args.count_file
        if args.sickle_handle is not None:
            profile["sickle_cursor_handle"] = args.sickle_handle

    binder = WindowBinder(args.title)
    input_ctl = InputController()
    clock = HumanClock(jitter=float(profile.get("jitter", 0.10)))

    control = RunControl()
    install_hotkeys(control, start_pause_key="F8", stop_key="F9", alt_pause_key="pause")

    ctx = BotContext(
        binder=binder,
        input=input_ctl,
        clock=clock,
        control=control,
        config=profile,
    )

    print(f"[*] title={args.title} | mode={args.mode} | profile={args.profile}")
    print("[*] 按 F8 或 Pause 开始/暂停，按 F9 退出")
    FEATURES[args.mode](ctx)


if __name__ == "__main__":
    main()
