#!/usr/bin/env sh
set -eu
python3 - <<'PY'
import json
import urllib.request

base = 'http://127.0.0.1:8080'
for path in ['/health', '/state']:
    data = urllib.request.urlopen(base + path, timeout=5).read().decode()
    print(path)
    print(json.dumps(json.loads(data), indent=2, sort_keys=True))

req = urllib.request.Request(
    base + '/chat',
    data=b'{"message":"test"}',
    headers={'Content-Type': 'application/json'},
    method='POST',
)
data = urllib.request.urlopen(req, timeout=5).read().decode()
print('/chat')
print(json.dumps(json.loads(data), indent=2, sort_keys=True))
PY
