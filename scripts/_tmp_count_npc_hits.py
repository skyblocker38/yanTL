import os, sys, cv2, yaml, numpy as np
sys.path.insert(0, os.getcwd())
from core.vision import mask_hsv_range

img_path = r'debug/npc_rejected/songshan-6_20260402_203636.png'
cfg = yaml.safe_load(open('config/profiles_cod_v3.yaml','r',encoding='utf-8'))['cod_instance_default']

img = cv2.imread(img_path, cv2.IMREAD_COLOR)
tpl_path = os.path.join('templates','cod_npc_1.png')
tpl = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
if img is None or tpl is None:
    raise RuntimeError('image/template missing')

lower = tuple(int(v) for v in cfg.get('npc_text_hsv_lower',[18,100,180]))
upper = tuple(int(v) for v in cfg.get('npc_text_hsv_upper',[36,255,255]))

img_m = mask_hsv_range(img, lower, upper)
tpl_m = mask_hsv_range(tpl, lower, upper)

res = cv2.matchTemplate(img_m, tpl_m, cv2.TM_CCOEFF_NORMED)
threshold = float(cfg.get('npc_threshold',0.82))
ys, xs = np.where(res >= threshold)

h, w = tpl_m.shape[:2]
rects = []
for y, x in zip(ys, xs):
    rects.append([int(x), int(y), int(x+w), int(y+h), float(res[y,x])])

rects.sort(key=lambda r: r[4], reverse=True)
kept = []
for r in rects:
    x1,y1,x2,y2,s = r
    keep = True
    for k in kept:
        xx1 = max(x1,k[0]); yy1=max(y1,k[1]); xx2=min(x2,k[2]); yy2=min(y2,k[3])
        iw = max(0, xx2-xx1); ih=max(0, yy2-yy1)
        inter = iw*ih
        a1 = (x2-x1)*(y2-y1)
        a2 = (k[2]-k[0])*(k[3]-k[1])
        iou = inter/(a1+a2-inter+1e-6)
        if iou > 0.35:
            keep = False
            break
    if keep:
        kept.append(r)

print('template:', tpl_path)
print('threshold:', threshold)
print('raw_hits:', len(rects))
print('nms_hits:', len(kept))
for i, r in enumerate(kept, 1):
    x1,y1,x2,y2,s = r
    cx = (x1+x2)//2
    cy = (y1+y2)//2
    print(f'hit#{i}: center=({cx},{cy}) score={s:.3f}')
