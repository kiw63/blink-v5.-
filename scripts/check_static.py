"""Safe static checks; not a replacement for physical device/media or GPU tests."""
from pathlib import Path
from html.parser import HTMLParser
import re
ROOT=Path(__file__).resolve().parent.parent/'docs'
class Parser(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.refs=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        for key in ['src','href']:
            if a.get(key) and a[key].startswith('./'):self.refs.append(a[key])
p=Parser();p.feed((ROOT/'index.html').read_text())
assert len(p.ids)==len(set(p.ids)),'Duplicate HTML IDs'
for ref in p.refs:
    if ref=='./':continue
    assert (ROOT/ref).is_file(),f'Broken static asset: {ref}'
js=(ROOT/'assets/app.js').read_text()
for id in set(re.findall(r"\$\('([^']+)'\)",js)):
    assert id in p.ids,f'Missing element #{id}'
for name in ['media.js','studio-api.js','app.js','style.css','ondevice-ai.js','smart-backup.js','tiny-restore-v1.json']:
    assert (ROOT/'assets'/name).is_file(),f'Missing {name}'
assert (ROOT/'.nojekyll').exists()
assert not re.search(r'(?:admin_password|BLINK_ADMIN_PASSWORD)\s*[:=]',js,re.I), 'Potential admin secret assignment'
assert re.search(r'api/studio/jobs', (ROOT/'assets/studio-api.js').read_text()),'Missing real AI API route'
print(f'Static structure validated: {len(p.ids)} unique elements, {len(p.refs)} assets, API bridge present.')
