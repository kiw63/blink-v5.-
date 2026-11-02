#!/usr/bin/env python3
"""Dependency-free static cross-service contract check for BLINK source distribution."""
import json,re,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
api=(root/'backend/app/main.py').read_text()
ui=(root/'frontend/app/platform.tsx').read_text()
compose=(root/'docker-compose.yml').read_text()
docker=(root/'backend/Dockerfile').read_text()
req=(root/'frontend/package.json').read_text()
from ast import literal_eval
from sys import path as sys_path
sys_path.insert(0,str(root/'backend'))
from app.capabilities import PHOTO_MODES, VIDEO_MODES, CINEMA_MODES, COSTS

def frontend_choice_values(name):
    match=re.search(r'const '+name+r'=(\[.*?\]);', ui)
    return [entry[0] for entry in literal_eval(match.group(1))] if match else []

cinema_values=re.findall(r'<option value="(natural|ultra-clear|film-contrast|golden-hour|night-cinema)"', ui)
checks={
    'Photo selection matches backend modes': set(frontend_choice_values('choicesPhoto'))==set(PHOTO_MODES),
    'Video selection matches backend modes': set(frontend_choice_values('choicesVideo'))==set(VIDEO_MODES),
    'Cinematic selection matches backend modes': set(cinema_values)==set(CINEMA_MODES),
    'Frontend prices match token contract': 'Rp20.000' in ui and '3 token gratis' in ui and '20 token' in ui,
    'Frontend has Next.js and React': 'next' in json.loads(req)['dependencies'] and 'react' in json.loads(req)['dependencies'],
    'Relative API proxy configured': "source:'/api/:path*'" in (root/'frontend/next.config.js').read_text(),
    'Actual frontend API capability handshake': "api('/public/capabilities')" in ui and "@app.get('/api/public/capabilities')" in api,
    'Protected payment approval contract': "@app.post('/api/admin/payments/{order_id}/approve')" in api and "Depends(admin_mutation)" in api,
    'Admin session requires TOTP': "verify_totp(" in api and "totp:" in api,
    'Token amounts defined on backend': "'photo': 1" in (root/'backend/app/capabilities.py').read_text(),
    'Database migration copied into image': 'COPY alembic ./alembic' in docker and 'COPY alembic.ini ./alembic.ini' in docker,
    'Database migrations run before backend': 'service_completed_successfully' in compose and "command: ['alembic','upgrade','head']" in compose,
    'Frontend waits for healthy backend': 'backend: {condition: service_healthy}' in compose,
    'Real provided logo': (root/'frontend/public/blink-logo.png').is_file(),
    'Real provided QRIS': (root/'backend/assets/qris-nanzera.jpg').is_file(),
    'Environment template exists': (root/'.env.example').is_file(),
}
for label,ok in checks.items():print(('PASS' if ok else 'FAIL')+' '+label)
if not all(checks.values()):sys.exit(1)
print('All static cross-service checks passed. Live GPU, SMTP, PostgreSQL, S3 and deployment remain unverified.')
