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

FEATURES = {
  "macro_combat": macro_combat.run,
  "recover_autofarm": recover_autofarm.run,
  "recover_autocombat": recover_autocombat.run,
  "auto_plant": auto_plant.run,
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
    parser.add_argument("--scene", default=None, choices=["xueyuan", "huanglong"], help="世界地图目标场景")
    args = parser.parse_args()

    profiles = load_profiles(args.config)
    if args.profile not in profiles:
        raise RuntimeError(f"找不到 profile: {args.profile}，可用: {list(profiles.keys())}")

    profile = profiles[args.profile]

    if args.scene:
        profile["scene"] = args.scene

    binder = WindowBinder(args.title)
    input_ctl = InputController()
    clock = HumanClock(jitter=float(profile.get("jitter", 0.10)))

    control = RunControl()
    install_hotkeys(control, start_pause_key="F8", stop_key="F9")

    ctx = BotContext(
        binder=binder,
        input=input_ctl,
        clock=clock,
        control=control,
        config=profile,
    )

    print(f"[*] title={args.title} | mode={args.mode} | profile={args.profile}")
    print("[*] 按 F8 开始/暂停，按 F9 退出")
    FEATURES[args.mode](ctx)


if __name__ == "__main__":
    main()