"""Tests der iOS-Auslieferung.

Die PWA **ist** die iOS-Oberflaeche: `hugin.html` wird auf dem iPhone zum
Startbildschirm hinzugefuegt und laeuft dann wie eine App. Damit entscheidet
der Service Worker darueber, ob eine neue Fassung ueberhaupt ankommt.

Genau das ist einmal schiefgegangen: der Worker lieferte die Huelle
Cache-First aus, der Schluessel `hugin-v7` wurde beim Umbau von `hugin.html`
nicht hochgezaehlt, und auf jedem installierten iPhone blieb die alte Seite
stehen. Ausgeliefert und trotzdem unerreichbar.
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
SW = REPO / "hugin" / "sw.js"
HTML = REPO / "hugin" / "hugin.html"
INDEX = REPO / "hugin" / "index.html"
MANIFEST = REPO / "hugin" / "manifest.json"


def test_the_shell_is_fetched_network_first():
    """Cache-First war die Ursache. Netz zuerst heisst: online ist die
    ausgelieferte Fassung immer die aktuelle, und Aktualitaet haengt nicht
    mehr daran, dass jemand an eine Zahl denkt."""
    t = SW.read_text(encoding="utf-8")
    holen = t.index("addEventListener('fetch'")
    zweig = t[holen:]
    assert "fetch(e.request)" in zweig
    # Der Netzabruf muss VOR dem Cache-Zugriff stehen.
    assert zweig.index("fetch(e.request)") < zweig.index("caches.match"), \
        "Cache wird vor dem Netz befragt — das ist wieder Cache-First"


def test_foreign_origins_and_non_get_are_passed_through_untouched():
    """Strukturelle Regel statt Namensliste. Die alte Fassung zaehlte 14
    AI-Hosts auf und vergass das eigene Gateway: ein `POST /chat` lief in den
    Huellen-Zweig, und bei nicht erreichbarem Gateway antwortete der Worker
    mit index.html — die PWA bekam HTML statt eines Ereignisstroms."""
    t = SW.read_text(encoding="utf-8")
    assert "url.origin !== self.location.origin" in t
    assert "e.request.method !== 'GET'" in t
    # Die alte Host-Liste darf nicht zurueckkehren; sie veraltet zwangslaeufig.
    assert "api.groq.com" not in t, "Host-Liste ist wieder da"


def test_the_cache_key_changed_since_the_version_that_shipped_stale():
    """Gegentest zum konkreten Vorfall: `hugin-v7` ist die Fassung, die eine
    Aenderung nicht ausgeliefert hat."""
    m = re.search(r"const CACHE = '([^']+)'", SW.read_text(encoding="utf-8"))
    assert m, "kein Cache-Schluessel gefunden"
    assert m.group(1) != "hugin-v7", "Schluessel unveraendert seit dem Vorfall"


def test_every_shell_entry_exists():
    """Ein Eintrag, den es nicht gibt, laesst `addAll` scheitern — und dann
    installiert sich der Worker gar nicht, still."""
    t = SW.read_text(encoding="utf-8")
    block = t[t.index("const SHELL"):t.index("];", t.index("const SHELL"))]
    for eintrag in re.findall(r"'\./([^']*)'", block):
        if not eintrag:            # './' ist das Verzeichnis selbst
            continue
        assert (REPO / "hugin" / eintrag).is_file(), f"SHELL zeigt auf {eintrag}"


def test_it_is_installable_on_ios():
    """Ohne diese drei Angaben bietet iOS kein 'Zum Home-Bildschirm'."""
    t = HTML.read_text(encoding="utf-8")
    assert 'rel="manifest"' in t
    assert "apple-mobile-web-app-capable" in t
    assert "apple-touch-icon" in t
    assert MANIFEST.is_file()


def test_index_is_a_byte_copy():
    """Dieselbe Regel wie im Supervisor — hier, damit ein einzelner Testlauf
    sie ebenfalls faengt."""
    assert INDEX.read_bytes() == HTML.read_bytes(), \
        "cp hugin/hugin.html hugin/index.html"


def test_the_gateway_provider_is_present_in_the_shipped_page():
    """Der Kern-Anbieter ist der Grund, warum die Auslieferung ueberhaupt
    zaehlt: er ist der Weg, ueber den vom iPhone aus befehligt wird."""
    t = HTML.read_text(encoding="utf-8")
    assert "id: 'kern'" in t
    assert "chunkToTextKern" in t
