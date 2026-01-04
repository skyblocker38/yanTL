from dataclasses import dataclass
from typing import Any


@dataclass
class BotContext:
    binder: Any         # WindowBinder
    input: Any          # InputController
    clock: Any          # HumanClock
    control: Any        # RunControl
    config: dict        # profile config


def run(ctx: BotContext):
    """
    macro_basic:
      - 反复执行 profile.macro 列表里的动作
      - 每个动作格式：{type, key, hold, gap}
    """
    profile = ctx.config
    macro = profile.get("macro", [])
    if not macro:
        raise RuntimeError("配置里没有 macro 动作列表")

    print("[*] macro_basic 已启动：F8 暂停/继续，F9 退出")
    hwnd = None

    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.05)
            continue

        hwnd = ctx.binder.ensure()

        for step in macro:
            if ctx.control.stop or not ctx.control.running:
                break

            if step.get("type") != "key":
                continue

            key = step.get("key")
            hold = float(step.get("hold", 0.05))
            gap = float(step.get("gap", 0.20))

            ctx.input.press(hwnd, key, hold=hold)
            ctx.clock.sleep(gap)

        ctx.clock.sleep(float(profile.get("loop_gap", 0.05)))