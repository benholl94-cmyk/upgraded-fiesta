#!/usr/bin/env python3
from html.parser import HTMLParser
from pathlib import Path
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TEXT_FILES = [
    'README.md',
    'docs/iphone-local-dev-setup.md',
    'index.html',
    'styles.css',
    'app.js',
    'manifest.webmanifest',
    'service-worker.js',
]
GUIDE_BLOCKLIST = [
    r'\b(Foto|photo|Bildfehler|OCR)\b',
    r'\b(TODO|FIXME|XXX)\b',
    r'(curl|wget).*(\|\s*(sh|bash))',
    r'example\.com',
    r'\bNone\b',
]
REQUIRED_HTML = [
    'id="access"',
    'class="skip-link"',
    'aria-pressed="true"',
    'id="safety"',
    'id="requests"',
    'id="requestOutput"',
    'id="main"',
]

class Parser(HTMLParser):
    pass

def read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')

def fail(message):
    print(f'validation failed: {message}', file=sys.stderr)
    raise SystemExit(1)

def main():
    for relative_path in TEXT_FILES:
        text = read(relative_path)
        if not text.endswith('\n'):
            fail(f'{relative_path} is missing a final newline')
        if '\t' in text:
            fail(f'{relative_path} contains tab characters')

    Parser().feed(read('index.html'))
    html = read('index.html')
    for needle in REQUIRED_HTML:
        if needle not in html:
            fail(f'index.html missing {needle}')

    guide = read('docs/iphone-local-dev-setup.md')
    for pattern in GUIDE_BLOCKLIST:
        match = re.search(pattern, guide, flags=re.I)
        if match:
            fail(f'guide contains blocked pattern {pattern}: {match.group(0)!r}')

    headings = [int(value) for value in re.findall(r'^## (\d+)\. ', guide, flags=re.M)]
    expected = list(range(1, len(headings) + 1))
    if headings != expected or len(headings) < 20:
        fail(f'guide headings are not sequential enough: {headings}')

    json.loads(read('manifest.webmanifest'))
    print('validation ok')

if __name__ == '__main__':
    main()
