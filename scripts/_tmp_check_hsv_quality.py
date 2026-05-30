import os, cv2, yaml, sys
sys.path.insert(0, os.getcwd())
from core.vision import find_template_masked

img_path = r'debug/npc_rejected/songshan-6_20260402_203636.png'
img = cv2.imread(img_path, cv2.IMREAD_COLOR)
tpl = cv2.imread(os.path.join('templates','cod_npc_1.png'), cv2.IMREAD_COLOR)

cands = [
    ((15,80,140),(40,255,255),'current'),
    ((20,120,200),(34,255,255),'candidate_A'),
    ((18,100,180),(36,255,255),'candidate_B'),
    ((20,140,200),(32,255,255),'candidate_C'),
]

for lower, upper, name in cands:
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    nz = cv2.countNonZero(mask)
    total = mask.shape[0]*mask.shape[1]
    ratio = nz/total
    m = find_template_masked(img, tpl, threshold=0.0, roi=None, lower_hsv=lower, upper_hsv=upper)
    print(f'{name}: score={m.score:.3f}, mask_ratio={ratio:.4f}, ok={m.ok}')
