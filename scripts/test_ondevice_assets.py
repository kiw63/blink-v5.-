"""Always-on CI verification of actual bundled CNN weights and privacy scope."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
A=ROOT/'docs/assets'
m=json.loads((A/'tiny-restore-v1.json').read_text())
assert m['id']=='blink-tiny-restore-v1'
assert len(m['conv1'])==len(m['conv2'])==len(m['bias1'])==4
assert all(len(w)==25 for w in m['conv1'])
assert all(len(w)==9 for w in m['conv2'])
assert (A/'ondevice-ai.js').exists() and (A/'smart-backup.js').exists()
engine=(A/'ondevice-ai.js').read_text();backup=(A/'smart-backup.js').read_text()
assert 'inferNeuralPixels' in engine and 'enhanceOnDevicePhoto' in engine
assert 'makeOnDeviceVideoProcessor' in engine
assert 'indexedDB' in backup and 'stageVideoChunk' in backup
assert "import('./ondevice-ai.js')" in (A/'media.js').read_text()
assert 'makeOnDeviceVideoProcessor' not in (A/'app.js').read_text()
assert "enqueueAutoAI('video'" not in (A/'app.js').read_text()
assert "enhanceOnDevicePhoto" in engine
assert "renderFrame(context,video,canvas.width,canvas.height,selected,intensity)" in (A/'app.js').read_text()
assert 'new Blob' in (A/'media.js').read_text()
assert (ROOT/'_site/assets/tiny-restore-v1.json').read_bytes()==(A/'tiny-restore-v1.json').read_bytes()
assert (ROOT/'_site/assets/ondevice-ai.js').read_bytes()==(A/'ondevice-ai.js').read_bytes()
print('ON-DEVICE CNN asset and backup contracts PASS; severe blur quality not certified')
