"""Fetch the selected CC0 Poly Haven school materials and one tree source."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'data/cache/school_assets'
HEADERS={'User-Agent':'photo3d-school-scene/1.0 (personal asset preparation)'}

def metadata(asset):
    path=CACHE/(asset+'.json')
    if not path.exists():
        raw=urlopen(Request('https://api.polyhaven.com/files/'+asset,headers=HEADERS),timeout=60).read()
        json.loads(raw)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(raw)
    return json.loads(path.read_text())

def fetch(job):
    path,info=job
    if path.exists() and path.stat().st_size==info['size']:return path.name
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=urlopen(Request(info['url'],headers=HEADERS),timeout=120).read()
    if len(raw)!=info['size']:raise ValueError('Incomplete download: '+str(path))
    if info.get('md5') and hashlib.md5(raw).hexdigest()!=info['md5']:raise ValueError('Checksum mismatch: '+str(path))
    path.write_bytes(raw)
    return path.name

jobs=[]
for asset in ('terrazzo_tiles','leafy_grass','precast_stone_paving'):
    data=metadata(asset)
    for key,short in [('Diffuse','diff'),('nor_gl','nor'),('Rough','rough')]:
        jobs.append((ROOT/'data/textures'/asset/(short+'.jpg'),data[key]['2k']['jpg']))
data=metadata('tree_small_02')['gltf']['1k']['gltf']
dest=ROOT/'data/assets/school_tree'
jobs.append((dest/'tree_small_02_1k.gltf',data))
for name,info in data['include'].items():
    path=(dest/name).resolve()
    if not path.is_relative_to(dest.resolve()):raise ValueError('Invalid included path')
    jobs.append((path,info))
with ThreadPoolExecutor(max_workers=4) as pool:
    for result in pool.map(fetch,jobs):print(result,flush=True)
print('Powered by Poly Haven: https://polyhaven.com/ ; assets CC0.')
