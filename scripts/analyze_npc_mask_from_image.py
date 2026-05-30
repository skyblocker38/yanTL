import argparse
import os
import sys
import time

import cv2
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.vision import find_template, find_template_masked


def _load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _discover_npc_templates(cfg: dict) -> list[str]:
    configured = list(cfg.get("templates", {}).get("npc", []) or [])
    if configured:
        return configured

    template_dir = cfg.get("npc_template_dir", "templates")
    if not os.path.isdir(template_dir):
        return []

    discovered = []
    for name in sorted(os.listdir(template_dir)):
        if not name.lower().endswith(".png"):
            continue
        if name.startswith("cod_npc"):
            discovered.append(os.path.join(template_dir, name))
    return discovered


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Analyze NPC yellow-mask effect from a screenshot")
    parser.add_argument("--image", required=True, help="input screenshot path")
    parser.add_argument("--config", default="config/profiles_cod_v3.yaml", help="config yaml path")
    parser.add_argument("--profile", default="cod_instance_default", help="profile name")
    parser.add_argument("--out-dir", default="debug/npc_mask_analysis", help="output dir")
    parser.add_argument("--image-is-roi", action="store_true", help="treat input image as already cropped npc ROI")
    args = parser.parse_args()

    all_cfg = _load_yaml(args.config)
    if args.profile not in all_cfg:
        raise RuntimeError(f"profile not found: {args.profile}")
    cfg = all_cfg[args.profile]

    img = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read image: {args.image}")

    roi = cfg.get("npc_label_roi") or cfg.get("npc_roi")
    if args.image_is_roi:
        roi = None
    # Auto-detect: images from debug/npc_rejected are already ROI crops.
    if ("npc_rejected" in os.path.normpath(args.image).lower()) and roi is not None and not args.image_is_roi:
        roi = None

    if roi is not None:
        x1, y1, x2, y2 = [int(v) for v in roi]
        crop = img[y1:y2, x1:x2]
    else:
        x1 = y1 = 0
        crop = img

    if crop.size == 0:
        raise RuntimeError("ROI crop is empty, check npc_label_roi")

    lower = tuple(int(v) for v in cfg.get("npc_text_hsv_lower", [15, 80, 140]))
    upper = tuple(int(v) for v in cfg.get("npc_text_hsv_upper", [40, 255, 255]))
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    masked = cv2.bitwise_and(crop, crop, mask=mask)

    _ensure_dir(args.out_dir)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = f"npc_mask_{ts}"
    crop_path = os.path.abspath(os.path.join(args.out_dir, f"{base}_crop.png"))
    mask_path = os.path.abspath(os.path.join(args.out_dir, f"{base}_mask.png"))
    masked_path = os.path.abspath(os.path.join(args.out_dir, f"{base}_masked.png"))
    cv2.imwrite(crop_path, crop)
    cv2.imwrite(mask_path, mask)
    cv2.imwrite(masked_path, masked)

    print(f"[OUT] crop   : {crop_path}")
    print(f"[OUT] mask   : {mask_path}")
    print(f"[OUT] masked : {masked_path}")
    print(f"[INFO] roi   : {[x1, y1, x1 + crop.shape[1], y1 + crop.shape[0]]}")
    print(f"[INFO] hsv   : lower={lower}, upper={upper}")

    templates = _discover_npc_templates(cfg)
    if not templates:
        print("[WARN] no npc templates found (templates.npc empty and no cod_npc*.png)")
        return

    threshold = float(cfg.get("npc_threshold", 0.82))
    plain_threshold = float(cfg.get("npc_plain_threshold", threshold))
    use_mask = bool(cfg.get("npc_use_yellow_mask", True))

    print(f"[INFO] templates={len(templates)} use_mask={use_mask}")
    print("[SCORES] top matches on this screenshot:")

    scores = []
    for path in templates:
        tpl = cv2.imread(path, cv2.IMREAD_COLOR)
        if tpl is None:
            continue
        masked_match = find_template_masked(
            img,
            tpl,
            threshold=threshold,
            roi=tuple(roi) if roi is not None else None,
            lower_hsv=lower,
            upper_hsv=upper,
        )
        plain_match = find_template(
            img,
            tpl,
            threshold=plain_threshold,
            roi=tuple(roi) if roi is not None else None,
        )
        scores.append((os.path.basename(path), masked_match.score, plain_match.score, masked_match.ok, plain_match.ok))

    scores.sort(key=lambda x: x[1], reverse=True)
    for name, masked_score, plain_score, masked_ok, plain_ok in scores[:10]:
        print(
            f"- {name}: masked={masked_score:.3f} ({'ok' if masked_ok else 'no'}), "
            f"plain={plain_score:.3f} ({'ok' if plain_ok else 'no'})"
        )


if __name__ == "__main__":
    main()
