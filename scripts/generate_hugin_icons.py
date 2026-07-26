#!/usr/bin/env python3
"""Erzeugt die PNG-Icons der HUGIN-PWA aus derselben Geometrie wie icon-512.svg.

**Warum überhaupt PNG.** Die PWA trug ausschließlich SVG-Icons: `icon-192.svg`,
`icon-512.svg` und einen `apple-touch-icon` als data-URI mit SVG-Inhalt. iOS
Safari wertet für `apple-touch-icon` nur Rasterformate aus und ignoriert SVG
— auch in den Manifest-Icons. „Zum Home-Bildschirm" ergab damit kein
App-Symbol, sondern den Rückfall von iOS. Die PWA war installierbar und sah
installiert nicht wie sie selbst aus.

**Warum ein Generator und keine eingecheckten Binärdateien.** Ein PNG im Repo
ist eine Behauptung, die niemand nachrechnen kann: ändert sich das Zeichen in
`icon-512.svg`, bleibt das PNG stumm veraltet. Hier ist die Geometrie einmal
notiert, und `tests/test_hugin_icons.py` prüft die erzeugten Dateien gegen
diese Quelle nach — dieselbe Regel wie `hugin_index_sync`.

**Warum selbstgeschrieben.** In dieser Umgebung gibt es weder `rsvg-convert`
noch Pillow noch ImageMagick, und die Betriebsregel des Repos ist
stdlib-only. Gerastert wird über ein Abstandsfeld (`zlib` + `struct` für PNG),
was zusätzlich saubere Kantenglättung ohne Supersampling ergibt.

**Warum randlos statt mit runden Ecken.** iOS legt seine eigene Maske über das
Symbol, Android ebenso bei `purpose: maskable`. Ein bereits abgerundetes
Symbol wird dann ein zweites Mal beschnitten. Die Zeichnung liegt deshalb
vollflächig auf.

**Warum das Zeichen leicht eingerückt ist.** `purpose: maskable` verspricht,
dass innerhalb des Sicherheitskreises (80 % Durchmesser, also Radius 204,8)
nichts Wichtiges beschnitten wird. Die Rohgeometrie hält das *nicht* ein: der
äußerste Bahnpunkt liegt 202,4 vom Mittelpunkt entfernt, und die halbe
Strichbreite von 9 kommt oben drauf — 211,4 > 204,8. Die erste Fassung dieser
Datei behauptete im Kommentar das Gegenteil, weil sie die Strichbreite
schlicht vergaß; aufgefallen ist es nur, weil `tests/test_hugin_icons.py` die
Zahl nachrechnet statt den Kommentar zu lesen. `GLYPH_INSET` schrumpft die
Zeichnung um die Bildmitte, bis sie tatsächlich hineinpasst.

    python3 scripts/generate_hugin_icons.py            # schreibt nach hugin/
    python3 scripts/generate_hugin_icons.py --check    # prüft nur, schreibt nicht
"""
from __future__ import annotations

import argparse
import math
import struct
import sys
import zlib
from array import array
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "hugin"

# ── Geometrie, 512er-Koordinatensystem (identisch zu hugin/icon-512.svg) ──────

BG = (0x05, 0x07, 0x0A)
FG = (0x3E, 0xF4, 0xE6)

# M64 320 Q128 144 256 128 Q384 144 448 320 Q352 272 320 336
#         Q288 240 256 240 Q224 240 192 336 Q160 272 64 320 Z
PATH_START = (64.0, 320.0)
QUADS = [
    ((128.0, 144.0), (256.0, 128.0)),
    ((384.0, 144.0), (448.0, 320.0)),
    ((352.0, 272.0), (320.0, 336.0)),
    ((288.0, 240.0), (256.0, 240.0)),
    ((224.0, 240.0), (192.0, 336.0)),
    ((160.0, 272.0), (64.0, 320.0)),
]
STROKE_WIDTH = 18.0
EYES = [((208.0, 208.0), 12.0), ((304.0, 208.0), 12.0)]

VIEWBOX = 512.0

# Sicherheitskreis fuer `purpose: maskable`: 80 % des Durchmessers.
MASKABLE_SAFE_RADIUS = VIEWBOX * 0.8 / 2

# Um diesen Faktor wird die Zeichnung zur Bildmitte hin geschrumpft, damit sie
# samt Strichbreite in den Sicherheitskreis passt. Erforderlich waeren 204,8 /
# 211,4 = 0,969; 0,95 laesst etwas Luft und ist optisch nicht von der
# Rohgroesse zu unterscheiden.
GLYPH_INSET = 0.95

# Was erzeugt wird. 180 ist die von iOS ausgewertete apple-touch-icon-Groesse,
# 192/512 sind die Manifest-Groessen.
TARGETS = {
    "apple-touch-icon-180.png": 180,
    "icon-192.png": 192,
    "icon-512.png": 512,
}


def _flatten_quad(p0, p1, p2, steps: int) -> list[tuple[float, float]]:
    """Zerlegt eine quadratische Bezier in Streckenzuege."""
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


def _inset(x: float, y: float) -> tuple[float, float]:
    """Schrumpft einen Punkt um die Bildmitte, siehe GLYPH_INSET."""
    c = VIEWBOX / 2
    return c + (x - c) * GLYPH_INSET, c + (y - c) * GLYPH_INSET


def path_points(scale: float, steps: int = 48) -> list[tuple[float, float]]:
    """Der komplette Streckenzug des Rabenzeichens, eingerueckt und skaliert."""
    pts = [PATH_START]
    current = PATH_START
    for ctrl, end in QUADS:
        pts.extend(_flatten_quad(current, ctrl, end, steps))
        current = end
    return [tuple(v * scale for v in _inset(x, y)) for x, y in pts]


def eye_circles(scale: float) -> list[tuple[tuple[float, float], float]]:
    """Die beiden Augen, eingerueckt und skaliert."""
    return [
        (tuple(v * scale for v in _inset(cx, cy)), r * GLYPH_INSET * scale)
        for (cx, cy), r in EYES
    ]


def stroke_radius(scale: float = 1.0) -> float:
    return STROKE_WIDTH * GLYPH_INSET * scale / 2.0


def outermost_reach() -> float:
    """Groesster Abstand der *sichtbaren* Zeichnung vom Bildmittelpunkt.

    Rechnet die halbe Strichbreite mit — genau das Glied, dessen Fehlen die
    erste Fassung dieser Datei falsch behaupten liess, das Zeichen passe in
    den maskable-Sicherheitskreis.
    """
    centre = VIEWBOX / 2
    points = list(path_points(scale=1.0))
    for (cx, cy), r in eye_circles(scale=1.0):
        points.extend([(cx + r, cy), (cx - r, cy), (cx, cy + r), (cx, cy - r)])
    worst = max(math.hypot(x - centre, y - centre) for x, y in points)
    return worst + stroke_radius()


def _segment_distance(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def render(size: int) -> bytes:
    """Rendert das Icon als rohe RGB-Bytes (size*size*3), vollflaechig deckend."""
    scale = size / VIEWBOX
    radius = stroke_radius(scale)
    pts = path_points(scale)

    # Abstandsfeld: je Pixel der kleinste Abstand zur Mittellinie. Daraus
    # ergibt sich die Deckung analytisch — das glaettet die Kanten, ohne jeden
    # Pixel vielfach abtasten zu muessen.
    far = float(size * 4)
    dist = array("f", [far]) * (size * size)

    reach = radius + 1.0
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        x0 = max(0, int(math.floor(min(ax, bx) - reach)))
        x1 = min(size - 1, int(math.ceil(max(ax, bx) + reach)))
        y0 = max(0, int(math.floor(min(ay, by) - reach)))
        y1 = min(size - 1, int(math.ceil(max(ay, by) + reach)))
        for y in range(y0, y1 + 1):
            row = y * size
            py = y + 0.5
            for x in range(x0, x1 + 1):
                d = _segment_distance(x + 0.5, py, ax, ay, bx, by)
                if d < dist[row + x]:
                    dist[row + x] = d

    # Augen: gefuellte Kreise, als eigenes Abstandsfeld eingerechnet.
    for (cx, cy), r in eye_circles(scale):
        x0 = max(0, int(math.floor(cx - r - 1)))
        x1 = min(size - 1, int(math.ceil(cx + r + 1)))
        y0 = max(0, int(math.floor(cy - r - 1)))
        y1 = min(size - 1, int(math.ceil(cy + r + 1)))
        for y in range(y0, y1 + 1):
            row = y * size
            for x in range(x0, x1 + 1):
                # Abstand zur Kreisflaeche, auf dieselbe Halbbreite normiert.
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy) - r + radius
                if d < dist[row + x]:
                    dist[row + x] = d

    out = bytearray(size * size * 3)
    for idx in range(size * size):
        coverage = radius + 0.5 - dist[idx]
        if coverage <= 0.0:
            r, g, b = BG
        elif coverage >= 1.0:
            r, g, b = FG
        else:
            r = int(BG[0] + (FG[0] - BG[0]) * coverage + 0.5)
            g = int(BG[1] + (FG[1] - BG[1]) * coverage + 0.5)
            b = int(BG[2] + (FG[2] - BG[2]) * coverage + 0.5)
        o = idx * 3
        out[o] = r
        out[o + 1] = g
        out[o + 2] = b
    return bytes(out)


def encode_png(size: int, rgb: bytes) -> bytes:
    """Minimaler PNG-Encoder, Farbtyp 2 (RGB, deckend)."""
    stride = size * 3
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # Filter 'None'
        raw += rgb[y * stride : (y + 1) * stride]

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def build(out_dir: Path = OUT_DIR) -> dict[str, bytes]:
    return {name: encode_png(size, render(size)) for name, size in TARGETS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="nur pruefen, ob die Dateien dem Generator entsprechen",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    produced = build(args.out)
    drift = []
    for name, data in produced.items():
        target = args.out / name
        if args.check:
            if not target.exists() or target.read_bytes() != data:
                drift.append(name)
            continue
        target.write_bytes(data)
        print(f"{target.relative_to(REPO)}  {len(data)} B")

    if args.check:
        if drift:
            print("Icons weichen vom Generator ab: " + ", ".join(sorted(drift)))
            print("Beheben mit: python3 scripts/generate_hugin_icons.py")
            return 1
        print("Icons entsprechen dem Generator ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
