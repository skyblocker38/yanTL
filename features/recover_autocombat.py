# features/recover_autocombat.py
"""
recover_autocombat: 死亡恢复 + 自动战斗宏

与 recover_autofarm 的区别：
- recover_autofarm: 流程4开启L挂机
- recover_autocombat: 流程4执行战斗宏（macro_combat）

流程说明：
1. 检测死亡弹窗，点击出窍
2. 从地府走出去（带地图检测和重试）
3. 回到对应位置（带地图检测和重试）
4. 下坐骑、召唤宝宝、启动战斗宏
"""

import time
import os
import cv2
import threading

from dataclasses import dataclass
from typing import Any

from core.capture_win32 import grab_client
from core.vision import find_template
from core.clicker_human import HumanClicker, ForegroundBlock


@dataclass
class BotContext:
    binder: Any
    input: Any      # 你的 InputController（后台按键）
    clock: Any      # HumanClock
    control: Any    # RunControl
    config: dict


def _load_tpl(path: str):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"模板加载失败: {path}")
    return img


def _roi_around_point(img):
    pos = (560, 224, 613, 259)
    x1, y1, x2, y2 = pos
    return (x1, y1, x2, y2)


def _save_debug_roi(img, roi, name="debug"):
    os.makedirs("debug", exist_ok=True)
    x1, y1, x2, y2 = roi
    crop = img[y1:y2, x1:x2]
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = f"debug/{name}_{ts}.png"
    cv2.imwrite(path, crop)
    print(f"[DEBUG] 保存 ROI 截图: {path}")


def _click_point(clicks: dict, name: str):
    if name not in clicks:
        raise RuntimeError(f"配置缺少 clicks.{name}")
    x, y = clicks[name]
    return int(x), int(y)


def _match_map_region(hwnd: int, tpl_map, threshold=0.85, roi=None):
    """
    地图模板匹配：截取游戏右上角的地图区域，与本地模板进行匹配
    
    Args:
        hwnd: 游戏窗口句柄
        tpl_map: 地图模板图像
        threshold: 匹配阈值，默认0.8
        roi: 可选的ROI区域 (x1, y1, x2, y2)，如果为None则使用默认右上角区域
    
    Returns:
        匹配结果对象 (包含 ok, score 等属性)
    """
    # 截取游戏窗口
    img = grab_client(hwnd)
    
    # 如果没有指定ROI，使用默认的右上角地图区域
    if roi is None:
        roi = (867, 15, 955, 29)  # (x1, y1, x2, y2)
    
    # 执行模板匹配
    m = find_template(img, tpl_map, threshold=threshold, roi=roi)
    
    return m


def _press_alt_m(ctx: BotContext, hwnd: int):
    """
    世界地图快捷键：Alt + M
    你地府里说不能用快捷键，所以地府不调用这个。
    """
    ctx.input.key_down(hwnd, "alt")
    ctx.clock.sleep(0.03)
    ctx.input.press(hwnd, "m", hold=0.05)
    ctx.clock.sleep(0.02)
    ctx.input.key_up(hwnd, "alt")


def _click_chuqiao(ctx: BotContext, hwnd: int, clicker: HumanClicker, clicks: dict):
    """
    流程1: 点击出窍按钮
    """
    print("[流程1] 点击出窍")
    
    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "chuqiao")
        clicker.click(hwnd, x, y, times=1)
        print("[流程1] 已点击出窍按钮")
    
    ctx.clock.sleep(5)
    print("[流程1] 出窍完成")


def _escape_underworld(ctx: BotContext, hwnd: int, clicker: HumanClicker, clicks: dict, cfg: dict):
    """
    流程2: 从地府走出去
    自动寻路 -> 双击孟婆 -> 选择洛阳 -> 离开地府
    """
    print("[流程2] 开始地府流程")
    
    # 步骤1: 自动寻路
    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, "tab", hold=0.05)
        print("[地府] 已按下Tab自动寻路")
    ctx.clock.sleep(1)

    # 步骤2: 双击孟婆NPC
    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "mengpo")
        clicker.click(hwnd, x, y, times=2)
        print("[地府] 已双击孟婆")
    ctx.clock.sleep(1.5)

    # 步骤3: 自动寻路走向孟婆
    with ForegroundBlock(hwnd, max_wait=0.6):
        ctx.input.press(hwnd, "tab", hold=0.05)
    ctx.clock.sleep(float(cfg.get("walk_to_mengpo_wait", 5)))
    print("[地府] 已走到孟婆位置")

    # 步骤4: 选择洛阳
    with ForegroundBlock(hwnd, max_wait=0.6):
        x, y = _click_point(clicks, "luoyang")
        clicker.click(hwnd, x, y, times=1)
        print("[地府] 已选择洛阳")
    
    # 等待离开地府
    ctx.clock.sleep(float(cfg.get("leave_underworld_wait", 8)))
    print("[流程2] 地府流程完成")


def _travel_to_position(ctx: BotContext, hwnd: int, clicker: HumanClicker, clicks: dict, cfg: dict, scene: str, target: dict):
    """
    流程3: 回到对应位置
    世界地图传送 -> 输入坐标 -> 移动到目标位置
    """
    print(f"[流程3] 开始回到对应位置")
    
    # 子流程1: 世界地图传送到场景
    with ForegroundBlock(hwnd, max_wait=0.6):
        # 步骤1: 取消当前自动寻路
        ctx.input.press(hwnd, "tab", hold=0.05)
        ctx.clock.sleep(2)

        # 步骤2: 打开世界地图
        _press_alt_m(ctx, hwnd)
        ctx.clock.sleep(2)
        print("[传送] 已打开世界地图")

        # 步骤3: 点击目标场景
        x, y = _click_point(clicks, scene)
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(2)
        print(f"[传送] 已选择场景: {scene}")

        # 步骤4: 在小地图上点击目标点
        x, y = _click_point(clicks, "ditu_click")
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(2)
        print("[传送] 已点击地图位置")

        # 步骤5: 点击确认按钮
        x, y = _click_point(clicks, "confirm_btn")
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(2)
        print("[传送] 已确认传送")

    # 等待跑图到目标地图
    travel_wait = float(cfg.get("travel_wait", 180))
    print(f"[传送] 等待到达目标场景 ({travel_wait}秒)")
    ctx.clock.sleep(travel_wait)
    
    # 子流程2: 输入坐标并移动到目标位置
    target_x = str(target.get("x", "0"))
    target_y = str(target.get("y", "0"))
    
    with ForegroundBlock(hwnd, max_wait=0.6):
        # 步骤1: 打开自动寻路面板
        ctx.input.press(hwnd, "tab", hold=0.2)
        ctx.clock.sleep(2)
        print("[移动] 已打开自动寻路面板")

        # 步骤2: 点击坐标输入框
        x, y = _click_point(clicks, "coord_input")
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(2)
        print("[移动] 已点击坐标输入框")

        # 步骤3: 输入X坐标
        ctx.input.type_text(hwnd, target_x)
        ctx.clock.sleep(1)
        ctx.input.press(hwnd, "enter", hold=0.2)
        ctx.clock.sleep(1)
        print(f"[移动] 已输入X坐标: {target_x}")
        
        # 步骤4: 输入Y坐标
        ctx.input.type_text(hwnd, target_y)
        ctx.clock.sleep(1)
        print(f"[移动] 已输入Y坐标: {target_y}")
        
        # 步骤5: 点击移动按钮
        x, y = _click_point(clicks, "move_btn")
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(1)
        ctx.input.press(hwnd, "tab", hold=0.2)
        print("[移动] 已开始移动到目标坐标")

    # 等待移动到位
    move_wait = float(cfg.get("move_to_xy_wait", 30))
    print(f"[移动] 等待到达目标坐标 ({move_wait}秒)")
    ctx.clock.sleep(move_wait)
    
    print("[流程3] 已到达目标位置")


def _start_macro_combat(ctx: BotContext, hwnd: int, clicker: HumanClicker, clicks: dict, cfg: dict, combat_thread_control: dict):
    """
    流程4: 下坐骑、召唤宝宝、启动战斗宏
    
    与 recover_autofarm 的区别：
    - autofarm: 按 L 开启挂机
    - autocombat: 启动战斗宏循环（在独立线程中）
    """
    print("[流程4] 开始准备战斗")
    
    with ForegroundBlock(hwnd, max_wait=0.6):
        # 步骤1: 下坐骑
        x, y = _click_point(clicks, "dismount_btn")
        clicker.click(hwnd, x, y, times=1)
        ctx.clock.sleep(1)
        ctx.input.press(hwnd, "d", hold=0.2)
        ctx.clock.sleep(1)
        print("[战斗] 已下坐骑")

        # 步骤2: 召唤宠物
        ctx.input.press(hwnd, "x", hold=0.2)
        ctx.clock.sleep(1)

        x, y = _click_point(clicks, "summon_pet_pos")
        clicker.click(hwnd, x, y, times=1)
        
        ctx.clock.sleep(1)
        ctx.input.press(hwnd, "x", hold=0.2)
        print("[战斗] 已召唤宠物")

        # 等待宠物/动画
        summon_wait = float(cfg.get("summon_wait", 5))
        ctx.clock.sleep(summon_wait)
    
    print("[流程4] 准备完成，启动战斗宏线程")
    
    # 停止之前的战斗宏线程（如果有）
    combat_thread_control["running"] = False
    if combat_thread_control["thread"] is not None:
        combat_thread_control["thread"].join(timeout=2)
    
    # 启动新的战斗宏线程
    combat_thread_control["running"] = True
    combat_thread = threading.Thread(
        target=_run_combat_macro_loop,
        args=(ctx, hwnd, cfg, combat_thread_control),
        daemon=True
    )
    combat_thread.start()
    combat_thread_control["thread"] = combat_thread
    
    print("[流程4] 战斗宏线程已启动")


def _run_combat_macro_loop(ctx: BotContext, hwnd: int, cfg: dict, combat_thread_control: dict):
    """
    战斗宏循环：反复执行配置的技能序列（在独立线程中运行）
    
    配置格式：
    macro:
      - { type: key, key: "s", hold: 0.05, gap: 0.25 }
      - { type: key, key: "a", hold: 0.06, gap: 1.20 }
    """
    macro = cfg.get("macro", [])
    if not macro:
        print("[战斗] 警告：配置中没有 macro 动作列表，战斗宏未启动")
        return
    
    loop_gap = float(cfg.get("loop_gap", 0.05))
    
    print(f"[战斗] 战斗宏循环开始，共 {len(macro)} 个技能")
    
    loop_count = 0
    
    # 战斗宏循环（由线程控制停止）
    while combat_thread_control["running"] and not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.05)
            continue
        
        loop_count += 1
        if loop_count % 10 == 0:
            print(f"[战斗] 宏循环执行中... (第 {loop_count} 轮)")
        
        # 执行技能序列
        for step in macro:
            if not combat_thread_control["running"] or ctx.control.stop or not ctx.control.running:
                break

            if step.get("type") != "key":
                continue

            key = step.get("key")
            hold = float(step.get("hold", 0.05))
            gap = float(step.get("gap", 0.20))

            ctx.input.press(hwnd, key, hold=hold)
            ctx.clock.sleep(gap)
        
        # 循环间隔
        ctx.clock.sleep(loop_gap)
    
    print("[战斗] 战斗宏循环已停止")


def run(ctx: BotContext):
    cfg = ctx.config
    clicks = cfg.get("clicks", {})
    tpls = cfg.get("templates", {})

    # 完全按配置
    check_interval = float(cfg.get("check_interval", 120))
    thr = float(cfg.get("threshold", 0.85))

    # 出窍模板：只做触发判断
    tpl_chuqiao = _load_tpl(tpls["death_chuqiao"])
    
    # 地图模板：用于检测场景
    tpl_difu = None
    tpl_scene = None
    
    if "map_difu" in tpls:
        tpl_difu = _load_tpl(tpls["map_difu"])
        print(f"[*] 已加载地府地图模板")
    
    scene = cfg.get("scene", "xueyuan")
    if scene not in ("xueyuan", "huanglong"):
        raise RuntimeError(f"scene 不支持: {scene}")
    
    map_key = f"map_{scene}"
    if map_key in tpls:
        tpl_scene = _load_tpl(tpls[map_key])
        print(f"[*] 已加载场景地图模板: {map_key}")

    # 目标坐标
    target = cfg.get("target", {})

    # 人性化点击器
    clicker = HumanClicker(
        hold_mean=float(cfg.get("hold_mean", 0.10)),
        hold_jitter=float(cfg.get("hold_jitter", 0.02)),
        hover=(float(cfg.get("hover_min", 0.04)), float(cfg.get("hover_max", 0.10))),
    )
    
    # 战斗宏线程控制
    combat_thread_control = {
        "running": False,
        "thread": None
    }

    print(f"[*] recover_autocombat 启动 | scene={scene} | check_interval={check_interval}s")
    print("[*] F8 暂停/继续，F9 退出")
    
    # 启动时立即开启战斗宏
    print("[*] 启动战斗宏...")
    hwnd = ctx.binder.ensure()
    
    # 启动战斗宏线程
    combat_thread_control["running"] = True
    combat_thread = threading.Thread(
        target=_run_combat_macro_loop,
        args=(ctx, hwnd, cfg, combat_thread_control),
        daemon=True
    )
    combat_thread.start()
    combat_thread_control["thread"] = combat_thread
    print("[*] 战斗宏已启动，同时开始监控死亡...")

    while not ctx.control.stop:
        if not ctx.control.running:
            ctx.clock.sleep(0.05)
            continue

        hwnd = ctx.binder.ensure()

        # ===== 1) 检测死亡弹窗 =====
        img = grab_client(hwnd)

        if "chuqiao" not in clicks:
            raise RuntimeError("配置缺少 clicks.chuqiao")

        roi = _roi_around_point(img)

        m = find_template(img, tpl_chuqiao, threshold=thr, roi=roi)

        if not m.ok:
            # 未检测到死亡，战斗宏继续运行
            # print(f"[MISS] chuqiao score={m.score:.3f}")
            ctx.clock.sleep(check_interval)
            continue

        # 检测到死亡弹窗，停止战斗宏
        print(f"[TRIGGER] 发现出窍弹窗 score={m.score:.3f} -> 执行恢复流程")
        
        if combat_thread_control["running"]:
            print("[战斗] 检测到死亡，停止战斗宏...")
            combat_thread_control["running"] = False
            if combat_thread_control["thread"] is not None:
                combat_thread_control["thread"].join(timeout=2)

        # =========================
        # 流程1: 点击出窍
        # =========================
        try:
            _click_chuqiao(ctx, hwnd, clicker, clicks)
        except Exception as e:
            print(f"[ERR] 流程1异常: {e}")
            ctx.clock.sleep(check_interval)
            continue

        ctx.clock.sleep(30)

        # =========================
        # 流程2: 从地府走出去 (带重试)
        # =========================
        max_underworld_retries = int(cfg.get("max_underworld_retries", 3))
        underworld_retry = 0
        
        while underworld_retry < max_underworld_retries:
            try:
                _escape_underworld(ctx, hwnd, clicker, clicks, cfg)
                
                # 验证是否还在地府
                if tpl_difu is not None:
                    print("[验证] 检测是否已离开地府...")
                    ctx.clock.sleep(2)
                    
                    m = _match_map_region(hwnd, tpl_difu, threshold=0.85)
                    
                    if m.ok:
                        underworld_retry += 1
                        print(f"[警告] 仍在地府 score={m.score:.3f}，重试流程2 ({underworld_retry}/{max_underworld_retries})")
                        ctx.clock.sleep(3)
                        continue
                    else:
                        print(f"[验证] 已离开地府 score={m.score:.3f}")
                        break
                else:
                    print("[验证] 未配置地府地图模板，跳过验证")
                    break
                    
            except Exception as e:
                print(f"[ERR] 流程2异常: {e}")
                underworld_retry += 1
                if underworld_retry >= max_underworld_retries:
                    print(f"[ERR] 流程2重试次数已达上限，跳过本次恢复")
                    ctx.clock.sleep(check_interval)
                    break
                ctx.clock.sleep(5)
        
        if underworld_retry >= max_underworld_retries:
            continue

        # =========================
        # 流程3: 回到对应位置 (带重试)
        # =========================
        max_travel_retries = int(cfg.get("max_travel_retries", 2))
        travel_retry = 0
        
        # 添加总重试计数器，防止流程2和流程3之间反复死亡导致的无限循环
        max_total_retries = int(cfg.get("max_total_retries", 5))
        total_retry = 0
        
        while travel_retry < max_travel_retries and total_retry < max_total_retries:
            total_retry += 1
            
            # ======================================================
            # 在执行流程3前，先检测是否有出窍弹窗或又回到了地府
            # （可能在路上被打死）
            # ======================================================
            
            # 1. 先检测是否有出窍弹窗（刚被打死，还没回地府）
            print("[验证] 流程3前检测是否有出窍弹窗...")
            ctx.clock.sleep(1)
            img = grab_client(hwnd)
            roi = _roi_around_point(img)
            m_chuqiao = find_template(img, tpl_chuqiao, threshold=thr, roi=roi)
            
            if m_chuqiao.ok:
                # 检测到出窍弹窗，说明在路上被打死了
                print(f"[警告] 检测到出窍弹窗 score={m_chuqiao.score:.3f}，在路上被打死，重新执行流程1+2")
                
                # 重新执行流程1：点击出窍
                try:
                    _click_chuqiao(ctx, hwnd, clicker, clicks)
                except Exception as e:
                    print(f"[ERR] 流程1（重新执行）异常: {e}")
                    break
                
                # 重新执行流程2：离开地府
                underworld_retry_inner = 0
                while underworld_retry_inner < max_underworld_retries:
                    try:
                        _escape_underworld(ctx, hwnd, clicker, clicks, cfg)
                        
                        # 验证是否还在地府
                        print("[验证] 检测是否已离开地府...")
                        ctx.clock.sleep(2)
                        
                        m_check = _match_map_region(hwnd, tpl_difu, threshold=0.85) if tpl_difu is not None else None
                        
                        if m_check and m_check.ok:
                            # 还在地府，需要重试
                            underworld_retry_inner += 1
                            print(f"[警告] 仍在地府 score={m_check.score:.3f}，重试流程2 ({underworld_retry_inner}/{max_underworld_retries})")
                            ctx.clock.sleep(3)
                            continue
                        else:
                            # 已离开地府
                            if m_check:
                                print(f"[验证] 已离开地府 score={m_check.score:.3f}")
                            else:
                                print(f"[验证] 未配置地府模板，默认已离开")
                            break
                            
                    except Exception as e:
                        print(f"[ERR] 流程2（重新执行）异常: {e}")
                        underworld_retry_inner += 1
                        if underworld_retry_inner >= max_underworld_retries:
                            print(f"[ERR] 流程2重新执行失败，跳过本次恢复")
                            break
                        ctx.clock.sleep(5)
                
                # 如果重新执行流程2失败，跳过本次恢复
                if underworld_retry_inner >= max_underworld_retries:
                    print("[ERR] 流程2重新执行失败次数过多，放弃本次恢复")
                    break
                
                # 成功离开地府后，继续执行流程3
                print("[*] 流程1+2重新执行成功，继续流程3")
            
            # 2. 检测是否又回到了地府（5分钟后自动回地府）
            elif tpl_difu is not None:
                print("[验证] 流程3前检测是否在地府...")
                ctx.clock.sleep(2)
                
                m = _match_map_region(hwnd, tpl_difu, threshold=0.85)
                
                if m.ok:
                    # 又回到地府了，需要重新执行流程2
                    print(f"[警告] 检测到又回到地府 score={m.score:.3f}，可能在路上被打死，重新执行流程2")
                    
                    # 重新执行流程2
                    underworld_retry_inner = 0
                    while underworld_retry_inner < max_underworld_retries:
                        try:
                            _escape_underworld(ctx, hwnd, clicker, clicks, cfg)
                            
                            # 验证是否还在地府
                            print("[验证] 检测是否已离开地府...")
                            ctx.clock.sleep(2)
                            
                            m_check = _match_map_region(hwnd, tpl_difu, threshold=0.85)
                            
                            if m_check.ok:
                                # 还在地府，需要重试
                                underworld_retry_inner += 1
                                print(f"[警告] 仍在地府 score={m_check.score:.3f}，重试流程2 ({underworld_retry_inner}/{max_underworld_retries})")
                                ctx.clock.sleep(3)
                                continue
                            else:
                                # 已离开地府
                                print(f"[验证] 已离开地府 score={m_check.score:.3f}")
                                break
                                
                        except Exception as e:
                            print(f"[ERR] 流程2（重新执行）异常: {e}")
                            underworld_retry_inner += 1
                            if underworld_retry_inner >= max_underworld_retries:
                                print(f"[ERR] 流程2重新执行失败，跳过本次恢复")
                                break
                            ctx.clock.sleep(5)
                    
                    # 如果重新执行流程2失败，跳过本次恢复
                    if underworld_retry_inner >= max_underworld_retries:
                        print("[ERR] 流程2重新执行失败次数过多，放弃本次恢复")
                        break
                    
                    # 成功离开地府后，继续执行流程3
                    print("[*] 流程2重新执行成功，继续流程3")
            
            try:
                _travel_to_position(ctx, hwnd, clicker, clicks, cfg, scene, target)
                
                # 验证是否到达目标场景
                if tpl_scene is not None:
                    print(f"[验证] 检测是否到达目标场景 {scene}...")
                    ctx.clock.sleep(2)
                    
                    m = _match_map_region(hwnd, tpl_scene, threshold=0.85)
                    
                    if not m.ok:
                        travel_retry += 1
                        print(f"[警告] 未到达 {scene} score={m.score:.3f}，重试流程3 ({travel_retry}/{max_travel_retries})")
                        ctx.clock.sleep(5)
                        continue
                    else:
                        print(f"[验证] 已到达 {scene} score={m.score:.3f}")
                        break
                else:
                    print(f"[验证] 未配置 {scene} 地图模板，跳过验证")
                    break
                    
            except Exception as e:
                print(f"[ERR] 流程3异常: {e}")
                travel_retry += 1
                if travel_retry >= max_travel_retries:
                    print(f"[ERR] 流程3重试次数已达上限，跳过本次恢复")
                    ctx.clock.sleep(check_interval)
                    break
                ctx.clock.sleep(5)
        
        if travel_retry >= max_travel_retries or total_retry >= max_total_retries:
            if total_retry >= max_total_retries:
                print(f"[ERR] 总重试次数已达上限 ({max_total_retries})，可能反复在路上被打死，跳过本次恢复")
            continue

        # =========================
        # 流程4: 下坐骑、召唤宝宝、启动战斗宏
        # =========================
        try:
            _start_macro_combat(ctx, hwnd, clicker, clicks, cfg, combat_thread_control)
            # 战斗宏在独立线程中运行，主循环会继续检测死亡
        except Exception as e:
            print(f"[ERR] 流程4异常: {e}")
            ctx.clock.sleep(check_interval)
            continue

        print("[DONE] 恢复流程完成，战斗宏在后台运行，继续监控...")

        # 下一轮检测：继续检测死亡弹窗
        ctx.clock.sleep(check_interval)
