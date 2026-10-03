"""Rebuild the bundled OFL report font from the pinned upstream Noto source.

Run from the repository root with matplotlib's fontTools dependency installed.
This is a development asset-generation utility, never called by the application.
"""

from pathlib import Path
import hashlib
import urllib.request
import tempfile
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from fontTools import subset
revision='f8d157532fbfaeda587e826d4cd5b21a49186f7c'
base=f'https://raw.githubusercontent.com/notofonts/noto-cjk/{revision}/Sans'
source=Path(tempfile.gettempdir())/'vibe-report-NotoSansCJKsc-VF.ttf'
if not source.exists():
    urllib.request.urlretrieve(base+'/Variable/TTF/NotoSansCJKsc-VF.ttf',source)
data=source.read_bytes()
assert hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()=='e67840913223f5c5db60570ce5bf001b0e079d42'
font=instantiateVariableFont(TTFont(source),{'wght':400},inplace=True)
options=subset.Options()
options.name_IDs=['*']
options.name_languages=['*']
subsetter=subset.Subsetter(options=options)
unicodes=set()
for start,end in ((0x20,0x250),(0x370,0x52f),(0x1100,0x11ff),(0x2000,0x26ff),(0x3000,0x318f),(0x31f0,0x31ff),(0x3400,0x9fff),(0xac00,0xd7af),(0xf900,0xfaff),(0xff00,0xffef)):
    unicodes.update(range(start,end+1))
subsetter.populate(unicodes=unicodes)
subsetter.subset(font)
for name in font['name'].names:
    if name.nameID in (1,3,4,6,16):
        name.string=('VibeCJK-Regular' if name.nameID==6 else 'Vibe CJK Regular').encode(name.getEncoding())
    elif name.nameID in (2,17):
        name.string='Regular'.encode(name.getEncoding())
out=Path('agent/src/shadow_account/assets')
out.mkdir(parents=True,exist_ok=True)
font.save(out/'VibeCJK-Regular.ttf')
with urllib.request.urlopen(base+'/LICENSE') as response:
    (out/'OFL.txt').write_bytes(response.read())
print({'bytes':(out/'VibeCJK-Regular.ttf').stat().st_size,'glyphs':len(font.getBestCmap()),'probe':[char in font.getBestCmap() for char in map(ord,'中国日本한국áβ')]})
