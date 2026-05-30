import os, cv2, yaml, itertools, sys
sys.path.insert(0, os.getcwd())
from core.vision import find_template_masked

img_path = r'debug/npc_rejected/songshan-6_20260402_203636.png'
cfg = yaml.safe_load(open('config/profiles_cod_v3.yaml','r',encoding='utf-8'))['cod_instance_default']
img = cv2.imread(img_path, cv2.IMREAD_COLOR)
if img is None:
    raise RuntimeError('image not found')

# load first npc template actually used
tpl_paths = [p for p in sorted(os.listdir('templates')) if p.startswith('cod_npc') and p.endswith('.png')]
if not tpl_paths:
    raise RuntimeError('no cod_npc*.png in templates')
tpl = cv2.imread(os.path.join('templates', tpl_paths[0]), cv2.IMREAD_COLOR)
if tpl is None:
    raise RuntimeError('template unreadable')

H_low = [10, 12, 14, 16, 18, 20]
H_high = [30, 32, 34, 36, 38, 40]
S_low = [40, 60, 80, 100, 120, 140]
V_low = [120, 140, 160, 180, 200]

results = []
for hl, hh, sl, vl in itertools.product(H_low, H_high, S_low, V_low):
    if hh <= hl:
        continue
    m = find_template_masked(
        img, tpl,
        threshold=0.0,
        roi=None,
        lower_hsv=(hl, sl, vl),
        upper_hsv=(hh, 255, 255),
    )
    results.append((m.score, hl, sl, vl, hh))

results.sort(reverse=True)
print('template=', tpl_paths[0])
for s, hl, sl, vl, hh in results[:15]:
    print(f'score={s:.3f} lower=({hl},{sl},{vl}) upper=({hh},255,255)')
