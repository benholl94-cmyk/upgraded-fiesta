"""Die iOS-Installierbarkeit der HUGIN-PWA, nachgerechnet statt behauptet.

Die PWA trug ausschließlich SVG-Icons. iOS Safari wertet für
`apple-touch-icon` nur Rasterformate aus, also blieb auf dem Home-Bildschirm
das App-Symbol aus — installierbar war sie, aber sie sah installiert nicht wie
sie selbst aus.

Ein eingechecktes PNG ist eine Behauptung, die niemand nachrechnen kann:
ändert sich `icon-512.svg`, bleibt das PNG stumm veraltet. Deshalb wird hier
gegen den Generator geprüft, nicht gegen ein Abbild — dieselbe Regel wie
`hugin_index_sync` und `hook-drift`.
"""
from __future__ import annotations

import json
import re
import struct
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HUGIN = REPO / "hugin"
sys.path.insert(0, str(REPO / "scripts"))

import generate_hugin_icons as gen  # noqa: E402


def _png_header(data: bytes) -> tuple[int, int, int, int]:
    """Gibt (breite, hoehe, bittiefe, farbtyp) aus dem IHDR zurueck."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "keine PNG-Signatur"
    length = struct.unpack(">I", data[8:12])[0]
    assert data[12:16] == b"IHDR"
    width, height, depth, color_type = struct.unpack(">IIBB", data[16 : 16 + 10])
    assert length == 13
    return width, height, depth, color_type


@pytest.mark.parametrize("name,size", sorted(gen.TARGETS.items()))
def test_icon_exists_and_declares_the_expected_size(name: str, size: int):
    path = HUGIN / name
    assert path.exists(), f"{name} fehlt — python3 scripts/generate_hugin_icons.py"
    width, height, depth, color_type = _png_header(path.read_bytes())
    assert (width, height) == (size, size)
    assert depth == 8
    assert color_type == 2, "Farbtyp 2 = RGB deckend; iOS komponiert Transparenz auf Schwarz"


def test_every_chunk_checksum_holds():
    """Ein PNG mit falscher CRC ist auf manchen Decodern schlicht kein Bild."""
    for name in gen.TARGETS:
        data = (HUGIN / name).read_bytes()
        offset = 8
        seen = []
        while offset < len(data):
            length = struct.unpack(">I", data[offset : offset + 4])[0]
            kind = data[offset + 4 : offset + 8]
            body = data[offset + 8 : offset + 8 + length]
            stored = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])[0]
            assert stored == zlib.crc32(kind + body) & 0xFFFFFFFF, f"{name}: CRC {kind!r}"
            seen.append(kind)
            offset += 12 + length
        assert seen[0] == b"IHDR" and seen[-1] == b"IEND", f"{name}: {seen}"


def test_icons_match_the_generator():
    """Der eigentliche Drift-Test: Datei == das, was der Generator erzeugt."""
    for name, data in gen.build().items():
        on_disk = (HUGIN / name).read_bytes()
        assert on_disk == data, (
            f"{name} weicht vom Generator ab. "
            "Beheben mit: python3 scripts/generate_hugin_icons.py"
        )


def test_apple_touch_icon_is_a_raster_file_not_an_svg_data_uri():
    """Die Regression selbst.

    Vorher stand hier ein `data:image/svg+xml,...`. Der Link war vorhanden,
    wohlgeformt und für iOS wirkungslos — genau die Sorte Fehler, die im
    Quelltext richtig aussieht.
    """
    html = (HUGIN / "hugin.html").read_text(encoding="utf-8")
    links = re.findall(r'<link[^>]*rel="apple-touch-icon"[^>]*>', html)
    assert links, "kein apple-touch-icon deklariert"
    for link in links:
        href = re.search(r'href="([^"]+)"', link)
        assert href, link
        target = href.group(1)
        assert not target.startswith("data:image/svg"), (
            "iOS ignoriert SVG als apple-touch-icon: " + link
        )
        assert target.endswith(".png"), link
        assert (HUGIN / target).exists(), f"{target} ist verlinkt, fehlt aber"


def test_the_locked_screen_keeps_the_pwa_head_intact():
    """Der Zustand, in dem tatsächlich installiert wird.

    Der Admin-Gate ersetzt bei fehlendem Token das gesamte Dokument. Vorher
    warf er dabei `<link rel="manifest">` und `apple-touch-icon` mit weg —
    und ohne Token ist genau das der Zustand, in dem ein Besucher „Zum
    Home-Bildschirm" tippt. Der Gate hat die Installierbarkeit miterschlagen,
    ohne dass das je beabsichtigt war.

    Im Browser mit iPhone-Profil gegengeprüft: gesperrter Bildschirm,
    apple-touch-icon liefert HTTP 200 image/png.
    """
    html = (HUGIN / "hugin.html").read_text(encoding="utf-8")
    start = html.find("function deny()")
    assert start != -1, "deny() nicht gefunden — Sperrbildschirm umgebaut?"
    body = html[start : html.find("\n  }", start)]

    for needed in (
        'rel="manifest"',
        'rel="apple-touch-icon"',
        "apple-touch-icon-180.png",
        'name="apple-mobile-web-app-capable"',
    ):
        assert needed in body, f"Sperrbildschirm verliert {needed}"


def test_the_locked_screen_markup_is_not_duplicated():
    """Vier wortgleiche Kopien waren der Grund, dass die Kopfzeilen fehlten.

    Wer eine von vier Stellen ergänzt, hat drei stille Rückfälle gebaut.
    """
    html = (HUGIN / "hugin.html").read_text(encoding="utf-8")
    assert html.count("Kein Zugang.</body>") == 1, (
        "Sperr-Markup steht wieder mehrfach im Dokument; "
        "genau so ist die PWA-Kopfzeile verloren gegangen"
    )


def test_manifest_offers_at_least_one_png_in_each_purpose():
    """Ein Manifest mit ausschliesslich SVG-Icons hilft Safari nicht weiter."""
    manifest = json.loads((HUGIN / "manifest.json").read_text(encoding="utf-8"))
    icons = manifest["icons"]
    pngs = [i for i in icons if i.get("type") == "image/png"]
    assert pngs, "keine PNG-Icons im Manifest"

    for icon in icons:
        src = icon["src"].lstrip("./")
        assert (HUGIN / src).exists(), f"{icon['src']} ist deklariert, fehlt aber"

    purposes = {p for i in pngs for p in i.get("purpose", "any").split()}
    assert "any" in purposes and "maskable" in purposes, purposes


def test_service_worker_caches_the_png_icons():
    """Was nicht in der Shell liegt, fehlt bei der Offline-Installation."""
    sw = (HUGIN / "sw.js").read_text(encoding="utf-8")
    for name in gen.TARGETS:
        assert f"'./{name}'" in sw, f"{name} fehlt in der Service-Worker-Shell"


def test_service_worker_cache_version_was_raised_past_the_svg_only_shell():
    """`activate` loescht nur Caches, die nicht `CACHE` heissen.

    Bleibt die Version stehen, behaelt ein bereits installiertes Geraet die
    alte Shell — die neuen Icons kaemen dort nie an, und der Fehler saehe aus
    wie „hat nicht funktioniert" statt wie „wurde nie ausgeliefert".
    """
    sw = (HUGIN / "sw.js").read_text(encoding="utf-8")
    match = re.search(r"const CACHE = 'hugin-v(\d+)'", sw)
    assert match, "Cache-Version nicht auffindbar"
    assert int(match.group(1)) >= 8, "Cache-Version nach der Icon-Aenderung nicht erhoeht"


def test_the_raven_stays_inside_the_maskable_safe_zone():
    """`purpose: maskable` verspricht, dass nichts Wichtiges beschnitten wird.

    Der Sicherheitsbereich ist der Kreis mit 80 % Durchmesser. Nachgerechnet
    aus derselben Geometrie, aus der auch gerendert wird — sonst waere das
    Versprechen nur ein Wort im Manifest.
    """
    reach = gen.outermost_reach()
    assert reach <= gen.MASKABLE_SAFE_RADIUS, (
        f"Zeichnung ragt aus dem maskable-Sicherheitskreis: {reach:.1f} "
        f"> {gen.MASKABLE_SAFE_RADIUS:.1f}"
    )


def test_the_inset_is_what_makes_it_fit_and_not_a_coincidence():
    """Gegenprobe: ohne Einrückung passt es nachweislich nicht.

    Ohne diese Richtung könnte GLYPH_INSET auf 1.0 zurückfallen und der Test
    oben bliebe trotzdem grün, wenn die Rohgeometrie zufällig knapp passte —
    sie passt aber nicht, und genau das soll festgehalten sein.
    """
    original = gen.GLYPH_INSET
    try:
        gen.GLYPH_INSET = 1.0
        assert gen.outermost_reach() > gen.MASKABLE_SAFE_RADIUS, (
            "Rohgeometrie passt wider Erwarten in den Sicherheitskreis — dann "
            "ist GLYPH_INSET unnötig und diese Begründung falsch"
        )
    finally:
        gen.GLYPH_INSET = original
