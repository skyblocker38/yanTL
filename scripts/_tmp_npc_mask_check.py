import os, sys, time, cv2, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + os.sep + '..')
from core.window import WindowBinder
from core.capture_win32 import grab_client

cfg = yaml.safe_load(open('config/profiles_cod_v3.yaml','r',encoding='utf-8'))['cod_instance_default']
title = '《新天龙八部》 0.08.0207 (原始一区:江湖梦)'
roi = tuple(int(v) for v in cfg.get('npc_label_roi', [280,140,760,460]))
lower = tuple(int(v) for v in cfg.get('npc_text_hsv_lower', [15,80,140]))
upper = tuple(int(v) for v in cfg.get('npc_text_hsv_upper', [40,255,255]))

binder = WindowBinder(title)
hwnd = binder.ensure()
img = grab_client(hwnd)
x1,y1,x2,y2 = roi
crop = img[y1:y2, x1:x2]

hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
mask = cv2.inRange(hsv, lower, upper)
vis = cv2.bitwise_and(crop, crop, mask=mask)

out_dir = os.path.join('debug','npc_mask_check')
os.makedirs(out_dir, exist_ok=True)
ts = time.strftime('%Y%m%d_%H%M%S')
paths = {
    'crop': os.path.abspath(os.path.join(out_dir, f'{ts}_crop.png')),
    'mask': os.path.abspath(os.path.join(out_dir, f'{ts}_mask.png')),
    'masked': os.path.abspath(os.path.join(out_dir, f'{ts}_masked.png')),
}
cv2.imwrite(paths['crop'], crop)
cv2.imwrite(paths['mask'], mask)
cv2.imwrite(paths['masked'], vis)
print('ROI', roi)
for k,v in paths.items():
    print(k, v)
