#!/usr/bin/env python3
"""Provision local development secrets; NEVER overwrites existing .env or creates admin."""
from pathlib import Path
import base64, os, secrets, sys

root=Path(__file__).resolve().parents[1]
path=root/'.env'
if path.exists():
    print(f'Configuration already exists: {path.name}. No changes made.')
    sys.exit(0)
env=(root/'.env.example').read_text()
for placeholder,value in {
    'REPLACE_WITH_LONG_RANDOM_PASSWORD': secrets.token_urlsafe(36),
    'REPLACE_WITH_A_UNIQUE_RANDOM_SECRET_AT_LEAST_48_CHARS': secrets.token_urlsafe(64),
    'REPLACE_WITH_FERNET_GENERATED_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
}.items():
    if placeholder not in env: raise RuntimeError('Expected placeholder missing: '+placeholder)
    env=env.replace(placeholder,value)
fd=os.open(str(path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as out: out.write(env)
print('Created private .env with secure random development secrets.')
print('Set SMTP_... before enabling public registration, and configure GPU/model weights for AI.')
print('Never commit .env or disclose its values.')
