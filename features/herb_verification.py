import ctypes
import os
import winsound

import cv2

from core.capture_win32 import grab_client
from core.vision import find_template


def _start_alert_audio(cfg: dict):
    path = os.path.abspath(str(cfg.get("verification_alert_audio", "templates/alert.mp3")))
    if not os.path.isfile(path):
        print(f"[VERIFY] alert audio not found: {path}")
        return None

    alias = "herb_verification_alert"
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f"close {alias}", None, 0, None)
    if mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None) != 0:
        print(f"[VERIFY] failed to open alert audio: {path}")
        return None
    if mci(f"play {alias} repeat", None, 0, None) != 0:
        mci(f"close {alias}", None, 0, None)
        print(f"[VERIFY] failed to play alert audio: {path}")
        return None
    print(f"[VERIFY] looping alert audio: {path}")
    return alias


def _stop_alert_audio(alias):
    if not alias:
        return
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f"stop {alias}", None, 0, None)
    mci(f"close {alias}", None, 0, None)


def load_template(cfg: dict):
    templates = cfg.get("templates", {}) or {}
    path = str(templates.get("herb_verification", "templates/herb_verification.png"))
    if not os.path.isfile(path):
        print(f"[VERIFY] verification template not found: {path}")
        return None
    template = cv2.imread(path, cv2.IMREAD_COLOR)
    if template is None:
        raise RuntimeError(f"无法读取采药验证窗口模板: {path}")
    return template


def detect(hwnd: int, cfg: dict, template, image=None):
    if template is None:
        return None
    roi_cfg = cfg.get("herb_verification_roi", [491, 198, 542, 223])
    roi = tuple(int(v) for v in roi_cfg)
    if image is None:
        image = grab_client(hwnd)
    return find_template(
        image,
        template,
        threshold=float(cfg.get("herb_verification_threshold", 0.86)),
        roi=roi,
    )


def pause_until_resumed(ctx, hwnd: int, cfg: dict, template, image=None) -> bool:
    match = detect(hwnd, cfg, template, image=image)
    if match is None or not match.ok:
        return False

    ctx.control.running = False
    print(f"[VERIFY] 检测到采药验证窗口 score={match.score:.3f}")
    print("[VERIFY] 已暂停；验证窗口消失后自动继续，F8 可手动继续")
    audio_alias = _start_alert_audio(cfg)
    if audio_alias is None:
        try:
            winsound.Beep(1200, 250)
            winsound.Beep(900, 250)
            winsound.Beep(1200, 350)
        except RuntimeError:
            pass

    auto_resume = bool(cfg.get("verification_auto_resume", True))
    poll_interval = float(cfg.get("verification_clear_poll_interval", 0.3))
    clear_hits_required = max(1, int(cfg.get("verification_clear_hits", 3)))
    clear_hits = 0
    try:
        while not ctx.control.running and not ctx.control.stop:
            if auto_resume:
                current = detect(hwnd, cfg, template)
                if current is not None and current.ok:
                    clear_hits = 0
                else:
                    clear_hits += 1
                    print(
                        f"[VERIFY] verification window clear check "
                        f"{clear_hits}/{clear_hits_required}"
                    )
                    if clear_hits >= clear_hits_required:
                        ctx.control.running = True
                        print("[VERIFY] 验证窗口已消失，自动停止提示音并继续")
                        break
            ctx.clock.sleep(poll_interval)
    finally:
        _stop_alert_audio(audio_alias)
    return True
