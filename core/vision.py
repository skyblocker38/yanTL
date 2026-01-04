from dataclasses import dataclass
import cv2
import numpy as np

@dataclass
class Match:
    ok: bool
    x: int = 0  # client x
    y: int = 0  # client y
    score: float = 0.0

def find_template(img_bgr: np.ndarray, tpl_bgr: np.ndarray, threshold=0.2, roi=None) -> Match:
    """
    roi: (x1,y1,x2,y2) in client coords; None means full image
    返回匹配中心点坐标（client coords）
    """
    if roi is not None:
        x1, y1, x2, y2 = roi
        view = img_bgr[y1:y2, x1:x2]
        offx, offy = x1, y1
    else:
        view = img_bgr
        offx, offy = 0, 0

    if view.size == 0:
        return Match(False)

    # 灰度匹配更稳
    img_g = cv2.cvtColor(view, cv2.COLOR_BGR2GRAY)
    tpl_g = cv2.cvtColor(tpl_bgr, cv2.COLOR_BGR2GRAY)

    res = cv2.matchTemplate(img_g, tpl_g, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)

    if max_val < threshold:
        return Match(False, score=float(max_val))

    th, tw = tpl_g.shape[:2]
    cx = offx + max_loc[0] + tw // 2
    cy = offy + max_loc[1] + th // 2
    return Match(True, cx, cy, float(max_val))