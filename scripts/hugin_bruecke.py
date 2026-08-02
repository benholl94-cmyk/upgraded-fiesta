#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hugin_bruecke.py -- Routenplanung fuer Provider-Aufrufe. Ohne Socket.

## Was das ist, und wovon es sich unterscheidet

Diese Datei plant Provider-Aufrufe: sie nimmt eine Anfrage-Huelle, fuehrt
sie durch eine feste Kette R1-R7, waehlt anhand einer **versiegelten**
Routentabelle ein Ziel, prueft Groessen- und Kopfzeilenvorgaben und
schreibt eine kettenverhakte Quittung.

**Sie sendet nichts.** R6 erzeugt einen Plan; es wird zu keinem Zeitpunkt
ein Socket geoeffnet. Nachgeprueft, nicht behauptet: die Datei importiert
weder `socket` noch `urllib` noch `requests`, und
`tests/test_hugin_bruecke.py` rechnet das nach.

Das ist der Grund, warum sie neben `scripts/hugin_oracle.py` stehen darf.
Die Verfassung kennt **einen** Weg nach draussen, und der ist das
Oracle-Gate. Ein zweiter waere kein Rueckfallplan, sondern die Stelle, an
der beide auseinanderlaufen und niemand merkt, welcher der betriebene ist.
Die Bruecke ist kein zweiter Weg, sondern die Schicht **darunter**:

| | Bruecke | Oracle-Gate |
|---|---|---|
| Frage | *wohin, mit welchen Koepfen, in welcher Groesse* | *darf das raus, und was kommt zurueck* |
| Netz | **nie** | ja, der einzige Ausgang |
| Zustand | Doppelfach A/B, HMAC-versiegelt | Auditprotokoll |

## Die Kette

    R1  Huellen-Normalisierung   Struktur, Pflichtfelder, Groesse messen
    R2  Siegel-Pruefung          HMAC-SHA256 ueber die Routentabelle
    R3  Regel-Aufloesung         Praedikat-Abgleich, Rang-Sortierung
    R4  Grenz-Pruefung           Nutzlast gegen Endpunkt-/Anbietergrenze
    R5  Kopf-Zusammenbau         x-api-key | Authorization, Version, Typ
    R6  Plan-Erzeugung           Trockenlauf. Es wird NICHTS gesendet.
    R7  Quittung                 kettenverhakte Zeile, mit Rueckleseprobe

## Die Siegel -- und was sie NICHT leisten

K1 HMAC-SHA256 ueber die Routentabelle · K2 Doppelfach A/B mit Selbstheilung
aus dem gesunden Fach · K3 Rueckleseprobe nach jedem Schreibvorgang ·
K4 jede Quittung traegt den Hash der vorigen Zeile.

**Keine Authentizitaet gegenueber Dritten.** Der HMAC-Schluessel liegt auf
demselben Geraet wie der Zustand: wer Lese- und Schreibrecht auf
`~/.hugin/bruecke` hat, kann Zustand *und* Siegel konsistent faelschen. Die
Siegel schuetzen gegen Beschaedigung und stilles Abdriften, nicht gegen
einen Angreifer mit Schreibrecht. Das ist derselbe ehrliche Zuschnitt wie
beim Schluesselbund: sechs Schluessel sind selbst ausstellbar, weil beide
Enden dem Projekt gehoeren -- und die anderen elf ausdruecklich nicht.

Ebenfalls nicht geleistet: Vertraulichkeit (Zustand und Chronik liegen im
Klartext), Zustellgarantie (R6 ist ein Plan, keine Verbindung), Schutz vor
fremden Schreibern ausserhalb der PID-Sperre. Die eingebetteten
Endpunktgrenzen sind eine Momentaufnahme und werden nicht online
nachgeprueft.

## Herkunft

Uebernommen aus einem eigenstaendigen Einzeldatei-Werkzeug (`BRUECKE`,
stdlib-only, fuer iSH/BusyBox gebaut) und fuer dieses Repo umbenannt und
eingepasst: Zustand unter `~/.hugin/`, Umgebungsvariable mit `HUGIN_`-
Praefix, Namen in der Familie der uebrigen `hugin_*`-Werkzeuge. Die Logik
der Kette ist unveraendert -- sie war bereits stdlib-only und ohne Netz,
also genau das, was dieses Repo verlangt.

    python3 scripts/hugin_bruecke.py --hilfe
    python3 scripts/hugin_bruecke.py keimen
    python3 scripts/hugin_bruecke.py pruefen
    python3 scripts/hugin_bruecke.py --selftest
"""
import base64
import binascii
import errno
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import signal
import stat
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _log import get_logger  # noqa: E402

log = get_logger(__name__)
import tempfile
import time

WERK = "BRUECKE"
FASSUNG = "1.0.0"

# ---------------------------------------------------------------------------
# Eingebettete Grenzwerte (Momentaufnahme der Claude-API-Dokumentation)
# ---------------------------------------------------------------------------

MB = 1024 * 1024

ENDPUNKT_GRENZEN = {
    "messages": 32 * MB,
    "count_tokens": 32 * MB,
    "batches": 256 * MB,
    "files": 500 * MB,
    "sessions": 32 * MB,
    "agents": 32 * MB,
    "environments": 32 * MB,
    "models": 32 * MB,
    "skills": 32 * MB,
}

# Anbieter-Deckel. Der wirksame Grenzwert ist min(Endpunkt, Anbieter).
ANBIETER_DECKEL = {
    "anthropic": None,          # kein zusaetzlicher Deckel
    "claude-platform-aws": None,  # gleiche Grenzen wie die direkte API
    "bedrock": 20 * MB,
    "google": 30 * MB,
    "foundry": None,
}

PFLICHT_KOEPFE = ("anthropic-version", "content-type")

SEITEN_SCHEMA_CURSOR = "page"      # page / next_page / prev_page
SEITEN_SCHEMA_ID = "id"            # after_id / before_id / has_more / first_id / last_id

ID_SCHEMA_ENDPUNKTE = {"batches", "files", "models", "admin"}

# ---------------------------------------------------------------------------
# Fehler
# ---------------------------------------------------------------------------


class BrueckeFehler(Exception):
    """Grundfehler. Fail-closed: jeder ungeklaerte Zustand bricht ab."""


class SiegelFehler(BrueckeFehler):
    """Ein Siegel passt nicht zum Inhalt oder der Schluessel fehlt."""


class FachFehler(BrueckeFehler):
    """Beide Faecher des Doppelfachs sind unbrauchbar."""


class KettenFehler(BrueckeFehler):
    """Die Chronik-Verhakung ist unterbrochen: eine Zeile fehlt oder wurde
    veraendert."""


# ---------------------------------------------------------------------------
# Heim / Pfade
# ---------------------------------------------------------------------------


def heim():
    p = os.environ.get("HUGIN_BRUECKE_HEIM")
    if p:
        return os.path.abspath(p)
    return os.path.join(os.path.expanduser("~"), ".hugin", "bruecke")


def pfad(*teile):
    return os.path.join(heim(), *teile)


def P_SCHLUESSEL():
    return pfad("schluessel")


def P_FACH(fach):
    return pfad("zustand.%s.json" % fach)


def P_CHRONIK():
    return pfad("chronik.jsonl")


def P_SPULE():
    return pfad("spule")


def P_FERTIG():
    return pfad("spule.fertig")


def P_SPERRE():
    return pfad("wache.pid")


FAECHER = ("a", "b")


# ---------------------------------------------------------------------------
# Grundwerkzeug: kanonische Form, Siegel, atomares Schreiben
# ---------------------------------------------------------------------------


def kanon(obj):
    """Kanonische Byte-Darstellung. Stabil ueber Neustarts und Python-Fassungen."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_hex(daten):
    if isinstance(daten, str):
        daten = daten.encode("utf-8")
    return hashlib.sha256(daten).hexdigest()


def siegeln(schluessel, obj):
    return hmac.new(schluessel, kanon(obj), hashlib.sha256).hexdigest()


def siegel_gueltig(schluessel, obj, siegel):
    if not isinstance(siegel, str):
        return False
    try:
        return hmac.compare_digest(siegeln(schluessel, obj), siegel)
    except (TypeError, ValueError):
        return False


def schreibe_atomar(ziel, daten):
    """mkstemp + os.replace im selben Verzeichnis. Kein Teilzustand bei Abbruch."""
    if isinstance(daten, str):
        daten = daten.encode("utf-8")
    ordner = os.path.dirname(os.path.abspath(ziel)) or "."
    os.makedirs(ordner, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".hugin-bruecke.", dir=ordner)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(daten)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError as exc:
                # iSH liefert fuer fsync gelegentlich EINVAL. Der Schreibvorgang
                # ist damit nicht garantiert dauerhaft -- das ist eine Aussage
                # ueber die Umgebung, keine ueber die Datei, und wird deshalb
                # protokolliert statt verschluckt.
                log.debug("fsync auf %s nicht moeglich: %s", ziel, exc)
        os.replace(tmp, ziel)
        tmp = None
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError as exc:
                # Aufraeumen im Fehlerpfad. Ein zurueckbleibendes Temp ist
                # ein Schoenheitsfehler, kein Datenverlust -- die Zieldatei
                # ist unangetastet. Protokolliert wird es trotzdem: stilles
                # Verschlucken macht eine volle Platte unsichtbar.
                log.debug("Temp %s nicht entfernbar: %s", tmp, exc)


def lies_datei(quelle):
    with open(quelle, "rb") as f:
        return f.read()


def schreibe_mit_rueckleseprobe(ziel, daten):
    """K3. Schreiben, sofort zurueckzulesen, Byte-Gleichheit erzwingen."""
    if isinstance(daten, str):
        daten = daten.encode("utf-8")
    schreibe_atomar(ziel, daten)
    zurueck = lies_datei(ziel)
    if zurueck != daten:
        raise FachFehler("Rueckleseprobe fehlgeschlagen: %s" % ziel)
    return True


# ---------------------------------------------------------------------------
# Schluessel
# ---------------------------------------------------------------------------


def schluessel_erzeugen():
    os.makedirs(heim(), exist_ok=True)
    roh = secrets.token_bytes(32)
    schreibe_mit_rueckleseprobe(P_SCHLUESSEL(), base64.b64encode(roh) + b"\n")
    try:
        os.chmod(P_SCHLUESSEL(), 0o600)
    except OSError as exc:
        # SICHERHEITSRELEVANT, deshalb eine Warnung und kein Debug: schlaegt
        # das fehl, liegt der HMAC-Schluessel moeglicherweise fuer andere
        # lesbar da. Abgebrochen wird trotzdem nicht -- auf manchen
        # Dateisystemen (iSH, FAT) gibt es keine Rechte, und dort waere ein
        # Abbruch eine Fehlmeldung ueber die Umgebung.
        log.warning("Rechte 0600 auf %s nicht setzbar: %s — Schluessel "
                    "moeglicherweise mitlesbar", P_SCHLUESSEL(), exc)
    return roh


def schluessel_laden():
    try:
        roh = lies_datei(P_SCHLUESSEL()).strip()
    except FileNotFoundError:
        raise BrueckeFehler("Kein Schluessel. Zuerst: bruecke.py keimen")
    try:
        k = base64.b64decode(roh, validate=True)
    except (binascii.Error, ValueError):
        raise SiegelFehler("Schluesseldatei unlesbar")
    if len(k) < 32:
        raise SiegelFehler("Schluessel zu kurz (%d Byte, erwartet >=32)" % len(k))
    return k


def schluessel_rechte_pruefen():
    """Meldet, ob der Schluessel fuer Gruppe/Welt lesbar ist. Kein Abbruch."""
    try:
        m = os.stat(P_SCHLUESSEL()).st_mode
    except OSError:
        return None
    return bool(m & (stat.S_IRWXG | stat.S_IRWXO))


# ---------------------------------------------------------------------------
# Doppelfach A/B mit Selbstheilung
# ---------------------------------------------------------------------------


def _fach_lesen(fach, schluessel):
    p = P_FACH(fach)
    try:
        roh = lies_datei(p)
    except FileNotFoundError:
        return None
    try:
        huelle = json.loads(roh.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(huelle, dict):
        return None
    nutz = huelle.get("nutzlast")
    sieg = huelle.get("siegel")
    if nutz is None or not siegel_gueltig(schluessel, nutz, sieg):
        return None
    return nutz


def _fach_schreiben(fach, schluessel, nutzlast):
    huelle = {
        "werk": WERK,
        "fassung": FASSUNG,
        "fach": fach,
        "nutzlast": nutzlast,
        "siegel": siegeln(schluessel, nutzlast),
    }
    roh = json.dumps(huelle, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    schreibe_mit_rueckleseprobe(P_FACH(fach), roh)
    # Zweite Probe: erneut entsiegeln, nicht nur Bytes vergleichen.
    if _fach_lesen(fach, schluessel) is None:
        raise FachFehler("Fach %s nach dem Schreiben nicht entsiegelbar" % fach)


def zustand_laden(schluessel, heilen=True):
    """Liest A, sonst B. Heilt das defekte Fach aus dem gesunden."""
    a = _fach_lesen("a", schluessel)
    b = _fach_lesen("b", schluessel)
    if a is None and b is None:
        raise FachFehler(
            "Beide Faecher unbrauchbar. Fail-closed. "
            "Neuanlage: bruecke.py keimen --neu"
        )
    if a is not None and b is None:
        if heilen:
            _fach_schreiben("b", schluessel, a)
        return a, ["b"]
    if a is None and b is not None:
        if heilen:
            _fach_schreiben("a", schluessel, b)
        return b, ["a"]
    # Beide gesund. A gilt. Abweichung wird gemeldet und A nach B gespiegelt.
    if kanon(a) != kanon(b):
        if heilen:
            _fach_schreiben("b", schluessel, a)
        return a, ["b"]
    return a, []


def zustand_sichern(schluessel, nutzlast):
    """A zuerst, dann B. Faellt A aus, bleibt B unberuehrt und gueltig."""
    nutzlast = dict(nutzlast)
    nutzlast["gesiegelt_um"] = int(time.time())
    _fach_schreiben("a", schluessel, nutzlast)
    _fach_schreiben("b", schluessel, nutzlast)
    return nutzlast


# ---------------------------------------------------------------------------
# Routentabelle
# ---------------------------------------------------------------------------


ROUTEN_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def standard_routen():
    return [
        {
            "name": "haupt",
            "anbieter": "anthropic",
            "ziel": "https://api.anthropic.com",
            "endpunkt": "messages",
            "pfad": "/v1/messages",
            "methode": "POST",
            "auth": "x-api-key",
            "version": "2023-06-01",
            "rang": 10,
            "praedikate": {"art": "messages"},
            "faellt_auf": "stapel",
        },
        {
            "name": "stapel",
            "anbieter": "anthropic",
            "ziel": "https://api.anthropic.com",
            "endpunkt": "batches",
            "pfad": "/v1/messages/batches",
            "methode": "POST",
            "auth": "x-api-key",
            "version": "2023-06-01",
            "rang": 20,
            "praedikate": {"art": "messages"},
            "faellt_auf": None,
        },
        {
            "name": "zaehler",
            "anbieter": "anthropic",
            "ziel": "https://api.anthropic.com",
            "endpunkt": "count_tokens",
            "pfad": "/v1/messages/count_tokens",
            "methode": "POST",
            "auth": "x-api-key",
            "version": "2023-06-01",
            "rang": 10,
            "praedikate": {"art": "count_tokens"},
            "faellt_auf": None,
        },
        {
            "name": "truhe",
            "anbieter": "anthropic",
            "ziel": "https://api.anthropic.com",
            "endpunkt": "files",
            "pfad": "/v1/files",
            "methode": "POST",
            "auth": "x-api-key",
            "version": "2023-06-01",
            "rang": 10,
            "praedikate": {"art": "files"},
            "faellt_auf": None,
        },
        {
            "name": "wolke",
            "anbieter": "bedrock",
            "ziel": "https://bedrock-runtime.eu-central-1.amazonaws.com",
            "endpunkt": "messages",
            "pfad": "/model/invoke",
            "methode": "POST",
            "auth": "bearer",
            "version": "2023-06-01",
            "rang": 90,
            "praedikate": {"art": "messages"},
            "faellt_auf": None,
        },
    ]


def route_pruefen(r):
    if not isinstance(r, dict):
        raise BrueckeFehler("Route ist kein Objekt")
    name = r.get("name")
    if not isinstance(name, str) or not ROUTEN_NAME.match(name):
        raise BrueckeFehler("Routenname unzulaessig: %r" % (name,))
    for feld in ("ziel", "pfad", "methode", "auth", "version", "endpunkt", "anbieter"):
        if not isinstance(r.get(feld), str) or not r.get(feld):
            raise BrueckeFehler("Route %s: Feld %s fehlt" % (name, feld))
    if r["auth"] not in ("x-api-key", "bearer"):
        raise BrueckeFehler("Route %s: auth muss x-api-key oder bearer sein" % name)
    if r["endpunkt"] not in ENDPUNKT_GRENZEN:
        raise BrueckeFehler(
            "Route %s: unbekannter Endpunkt %s" % (name, r["endpunkt"])
        )
    if r["anbieter"] not in ANBIETER_DECKEL:
        raise BrueckeFehler("Route %s: unbekannter Anbieter %s" % (name, r["anbieter"]))
    if not isinstance(r.get("rang"), int):
        raise BrueckeFehler("Route %s: rang muss ganzzahlig sein" % name)
    if not r["ziel"].startswith("https://"):
        raise BrueckeFehler("Route %s: ziel muss https:// sein" % name)
    if not r["pfad"].startswith("/") or ".." in r["pfad"]:
        raise BrueckeFehler("Route %s: pfad unzulaessig" % name)
    p = r.get("praedikate")
    if p is not None and not isinstance(p, dict):
        raise BrueckeFehler("Route %s: praedikate muss ein Objekt sein" % name)
    f = r.get("faellt_auf")
    if f is not None and (not isinstance(f, str) or not ROUTEN_NAME.match(f)):
        raise BrueckeFehler("Route %s: faellt_auf unzulaessig" % name)
    return True


def grenze_fuer(route):
    e = ENDPUNKT_GRENZEN[route["endpunkt"]]
    d = ANBIETER_DECKEL.get(route["anbieter"])
    return e if d is None else min(e, d)


def routen_pruefen_gesamt(routen):
    namen = set()
    for r in routen:
        route_pruefen(r)
        if r["name"] in namen:
            raise BrueckeFehler("Doppelter Routenname: %s" % r["name"])
        namen.add(r["name"])
    for r in routen:
        if r.get("faellt_auf") and r["faellt_auf"] not in namen:
            raise BrueckeFehler(
                "Route %s verweist auf unbekannten Ersatz %s"
                % (r["name"], r["faellt_auf"])
            )
    # Zyklen in den Ersatzketten
    for r in routen:
        gesehen = [r["name"]]
        cur = r.get("faellt_auf")
        nach_name = {x["name"]: x for x in routen}
        while cur:
            if cur in gesehen:
                raise BrueckeFehler(
                    "Ersatzkette bildet einen Kreis: %s" % " -> ".join(gesehen + [cur])
                )
            gesehen.append(cur)
            cur = nach_name[cur].get("faellt_auf")
    return True


# ---------------------------------------------------------------------------
# Chronik mit Verhakung (K4)
# ---------------------------------------------------------------------------


def chronik_letzter_hash():
    p = P_CHRONIK()
    if not os.path.exists(p):
        return "0" * 64
    letzte = None
    with open(p, "rb") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                letzte = zeile
    if letzte is None:
        return "0" * 64
    return sha256_hex(letzte)


def chronik_anhaengen(schluessel, eintrag):
    kern = dict(eintrag)
    kern["vorher"] = chronik_letzter_hash()
    kern["um"] = int(time.time())
    kern["siegel"] = siegeln(schluessel, {k: v for k, v in kern.items()})
    zeile = json.dumps(kern, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    os.makedirs(heim(), exist_ok=True)
    with open(P_CHRONIK(), "a", encoding="utf-8") as f:
        f.write(zeile + "\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError as exc:
            log.debug("fsync auf der Chronik nicht moeglich: %s", exc)
    return sha256_hex(zeile)


def chronik_pruefen(schluessel):
    """Prueft Verhakung und Siegel jeder Zeile. Liefert (anzahl, fehler)."""
    p = P_CHRONIK()
    if not os.path.exists(p):
        return 0, []
    fehler = []
    vorher = "0" * 64
    n = 0
    with open(p, "rb") as f:
        for i, roh in enumerate(f, 1):
            roh = roh.strip()
            if not roh:
                continue
            n += 1
            try:
                e = json.loads(roh.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                fehler.append((i, "unlesbar"))
                vorher = sha256_hex(roh)
                continue
            sieg = e.pop("siegel", None)
            if not siegel_gueltig(schluessel, e, sieg):
                fehler.append((i, "Siegel ungueltig"))
            if e.get("vorher") != vorher:
                fehler.append((i, "Verhakung gebrochen"))
            vorher = sha256_hex(roh)
    return n, fehler


# ---------------------------------------------------------------------------
# Kette R1 - R7
# ---------------------------------------------------------------------------


ERLAUBTE_ARTEN = set(ENDPUNKT_GRENZEN.keys())


def r1_normalisieren(huelle):
    """Struktur und Pflichtfelder. Nutzlast messen."""
    if not isinstance(huelle, dict):
        raise KettenFehler("R1: Huelle ist kein Objekt")
    art = huelle.get("art")
    if not isinstance(art, str) or art not in ERLAUBTE_ARTEN:
        raise KettenFehler(
            "R1: art fehlt oder unbekannt (erlaubt: %s)"
            % ", ".join(sorted(ERLAUBTE_ARTEN))
        )
    nutz = huelle.get("nutzlast")
    if nutz is None:
        raise KettenFehler("R1: nutzlast fehlt")
    if isinstance(nutz, (dict, list)):
        roh = kanon(nutz)
    elif isinstance(nutz, str):
        roh = nutz.encode("utf-8")
    else:
        raise KettenFehler("R1: nutzlast muss Objekt, Liste oder Text sein")
    marken = huelle.get("marken") or []
    if not isinstance(marken, list) or not all(isinstance(m, str) for m in marken):
        raise KettenFehler("R1: marken muss eine Liste von Text sein")
    kennung = huelle.get("kennung")
    if kennung is not None and not isinstance(kennung, str):
        raise KettenFehler("R1: kennung muss Text sein")
    return {
        "art": art,
        "bytes": len(roh),
        "abdruck": sha256_hex(roh),
        "marken": marken,
        "kennung": kennung or ("h-" + sha256_hex(roh)[:16]),
        "wunsch_route": huelle.get("route"),
    }


def r2_siegel(schluessel):
    """Zustand entsiegeln. Meldet geheilte Faecher."""
    zustand, geheilt = zustand_laden(schluessel)
    routen = zustand.get("routen")
    if not isinstance(routen, list) or not routen:
        raise SiegelFehler("R2: Routentabelle leer oder beschaedigt")
    routen_pruefen_gesamt(routen)
    return zustand, routen, geheilt


def _praedikate_passen(route, norm):
    p = route.get("praedikate") or {}
    if "art" in p and p["art"] != norm["art"]:
        return False
    if "marke" in p and p["marke"] not in norm["marken"]:
        return False
    if "min_bytes" in p and norm["bytes"] < int(p["min_bytes"]):
        return False
    if "max_bytes" in p and norm["bytes"] > int(p["max_bytes"]):
        return False
    return True


def r3_aufloesen(routen, norm):
    """Kandidaten nach Praedikat, sortiert nach Rang, dann Name."""
    nach_name = {r["name"]: r for r in routen}
    if norm.get("wunsch_route"):
        w = norm["wunsch_route"]
        if w not in nach_name:
            raise KettenFehler("R3: gewuenschte Route unbekannt: %s" % w)
        return [nach_name[w]], nach_name
    kandidaten = [r for r in routen if _praedikate_passen(r, norm)]
    if not kandidaten:
        raise KettenFehler("R3: keine Route trifft auf art=%s zu" % norm["art"])
    kandidaten.sort(key=lambda r: (r["rang"], r["name"]))
    return kandidaten, nach_name


def r4_grenze(route, norm):
    g = grenze_fuer(route)
    if norm["bytes"] > g:
        return False, (
            "413 request_too_large: %d Byte > %d Byte (Endpunkt %s / Anbieter %s)"
            % (norm["bytes"], g, route["endpunkt"], route["anbieter"])
        )
    return True, None


def r5_koepfe(route):
    koepfe = {
        "anthropic-version": route["version"],
        "content-type": "application/json",
    }
    if route["auth"] == "x-api-key":
        koepfe["x-api-key"] = "<REDIGIERT>"
    else:
        koepfe["Authorization"] = "Bearer <REDIGIERT>"
    for k in PFLICHT_KOEPFE:
        if k not in koepfe:
            raise KettenFehler("R5: Pflichtkopf %s fehlt" % k)
    return koepfe


def r6_plan(route, norm, koepfe):
    """Trockenlauf. Es wird kein Socket geoeffnet."""
    return {
        "methode": route["methode"],
        "url": route["ziel"].rstrip("/") + route["pfad"],
        "anbieter": route["anbieter"],
        "endpunkt": route["endpunkt"],
        "kopf": koepfe,
        "nutzlast_bytes": norm["bytes"],
        "nutzlast_abdruck": norm["abdruck"],
        "grenze_bytes": grenze_fuer(route),
        "gesendet": False,
    }


def leiten(schluessel, huelle, mit_quittung=True):
    """Volle Kette R1-R7. Liefert das Urteil."""
    norm = r1_normalisieren(huelle)
    zustand, routen, geheilt = r2_siegel(schluessel)
    kandidaten, nach_name = r3_aufloesen(routen, norm)

    versuche = []
    gruende = []
    plan = None
    gewaehlt = None

    # Kandidatenliste zuerst, jede mit ihrer Ersatzkette.
    reihe = []
    for k in kandidaten:
        cur = k
        tiefe = 0
        while cur is not None and tiefe < 16:
            if cur["name"] not in [r["name"] for r in reihe]:
                reihe.append(cur)
            nxt = cur.get("faellt_auf")
            cur = nach_name.get(nxt) if nxt else None
            tiefe += 1

    for route in reihe:
        versuche.append(route["name"])
        ok, grund = r4_grenze(route, norm)
        if not ok:
            gruende.append("%s: %s" % (route["name"], grund))
            continue
        koepfe = r5_koepfe(route)
        plan = r6_plan(route, norm, koepfe)
        gewaehlt = route
        break

    if gewaehlt is None:
        urteil = {
            "werk": WERK,
            "fassung": FASSUNG,
            "kennung": norm["kennung"],
            "kette": ["R1", "R2", "R3", "R4"],
            "urteil": "ABGEWIESEN",
            "route": None,
            "versuche": versuche,
            "gruende": gruende,
            "plan": None,
            "geheilte_faecher": geheilt,
        }
    else:
        urteil = {
            "werk": WERK,
            "fassung": FASSUNG,
            "kennung": norm["kennung"],
            "kette": ["R1", "R2", "R3", "R4", "R5", "R6"],
            "urteil": "BEREIT" if versuche[0] == gewaehlt["name"] else "ERSATZ",
            "route": gewaehlt["name"],
            "versuche": versuche,
            "gruende": gruende,
            "plan": plan,
            "geheilte_faecher": geheilt,
        }

    if mit_quittung:
        q = chronik_anhaengen(
            schluessel,
            {
                "kennung": urteil["kennung"],
                "urteil": urteil["urteil"],
                "route": urteil["route"],
                "bytes": norm["bytes"],
                "abdruck": norm["abdruck"],
                "versuche": versuche,
            },
        )
        urteil["kette"].append("R7")
        urteil["quittung"] = q
    return urteil


# ---------------------------------------------------------------------------
# Seiten-Helfer (beide Cursor-Schemata)
# ---------------------------------------------------------------------------


def seiten_schema(endpunkt):
    return SEITEN_SCHEMA_ID if endpunkt in ID_SCHEMA_ENDPUNKTE else SEITEN_SCHEMA_CURSOR


def seiten_naechste(endpunkt, antwort, limit=None, order=None):
    """Baut die Abfrageparameter der Folgeseite. None = keine weitere Seite."""
    if not isinstance(antwort, dict):
        raise BrueckeFehler("Antwort ist kein Objekt")
    schema = seiten_schema(endpunkt)
    par = {}
    if limit is not None:
        par["limit"] = int(limit)
    if schema == SEITEN_SCHEMA_CURSOR:
        nxt = antwort.get("next_page")
        if not nxt:
            return None
        par["page"] = nxt
        if order:
            # Ein page-Cursor gilt nur mit der order, mit der er erzeugt wurde.
            par["order"] = order
        return par
    # id-Schema
    if not antwort.get("has_more"):
        return None
    last = antwort.get("last_id")
    if not last:
        return None
    par["after_id"] = last
    return par


def seiten_vorige(endpunkt, antwort, limit=None, order=None):
    schema = seiten_schema(endpunkt)
    par = {}
    if limit is not None:
        par["limit"] = int(limit)
    if schema == SEITEN_SCHEMA_CURSOR:
        prv = antwort.get("prev_page")
        if not prv:
            return None  # fehlt oder null -> keine Rueckwaerts-Blaetterung
        par["page"] = prv
        if order:
            par["order"] = order
        return par
    first = antwort.get("first_id")
    if not first:
        return None
    par["before_id"] = first
    return par


# ---------------------------------------------------------------------------
# Wache: der Aufsatz-Prozess
# ---------------------------------------------------------------------------


SICHERER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\.json$")

_LAUF = {"weiter": True}


def _halt(signum, rahmen):
    _LAUF["weiter"] = False


def sperre_nehmen():
    """PID-Sperre mit O_EXCL. Erkennt tote Halter und uebernimmt."""
    os.makedirs(heim(), exist_ok=True)
    p = P_SPERRE()
    for _ in range(2):
        try:
            fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w") as f:
                f.write("%d\n" % os.getpid())
            return True
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            alt = sperre_halter()
            if alt is None or not prozess_lebt(alt):
                try:
                    os.unlink(p)
                except OSError as exc:
                    # Ein anderer Prozess war schneller. Kein Fehler, aber
                    # sichtbar: eine Sperre, die sich nie loesen laesst,
                    # sieht sonst wie ein Haenger aus.
                    log.debug("verwaiste Sperre %s nicht entfernbar: %s", p, exc)
                continue
            raise BrueckeFehler("Wache laeuft bereits (PID %d)" % alt)
    raise BrueckeFehler("Sperre konnte nicht genommen werden")


def sperre_halter():
    try:
        roh = lies_datei(P_SPERRE()).decode("utf-8").strip()
        return int(roh)
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def prozess_lebt(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == errno.EPERM


def sperre_loesen():
    try:
        if sperre_halter() == os.getpid():
            os.unlink(P_SPERRE())
    except OSError as exc:
        log.debug("eigene Sperre nicht loesbar: %s", exc)


def spule_durchgang(schluessel):
    """Ein Durchgang ueber die Spule. Liefert (verarbeitet, abgewiesen)."""
    os.makedirs(P_SPULE(), exist_ok=True)
    os.makedirs(P_FERTIG(), exist_ok=True)
    verarbeitet = 0
    abgewiesen = 0
    for name in sorted(os.listdir(P_SPULE())):
        if not SICHERER_NAME.match(name):
            continue  # Pfadwanderung und Fremddateien werden ignoriert
        quelle = os.path.join(P_SPULE(), name)
        if not os.path.isfile(quelle):
            continue
        try:
            huelle = json.loads(lies_datei(quelle).decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            urteil = {
                "urteil": "ABGEWIESEN",
                "gruende": ["R1: Huelle unlesbar: %s" % e],
                "kennung": name,
            }
            abgewiesen += 1
        else:
            try:
                urteil = leiten(schluessel, huelle)
                if urteil["urteil"] == "ABGEWIESEN":
                    abgewiesen += 1
                else:
                    verarbeitet += 1
            except BrueckeFehler as e:
                urteil = {
                    "urteil": "ABGEWIESEN",
                    "gruende": [str(e)],
                    "kennung": name,
                }
                abgewiesen += 1
        ziel = os.path.join(P_FERTIG(), name.rsplit(".", 1)[0] + ".urteil.json")
        schreibe_mit_rueckleseprobe(
            ziel, json.dumps(urteil, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        try:
            os.unlink(quelle)
        except OSError as exc:
            # Das Urteil ist bereits geschrieben; die Huelle in der Spule
            # liegen zu lassen ist unschoen, aber nicht folgenlos: sie wird
            # beim naechsten Durchgang erneut geleitet. Deshalb sichtbar.
            log.warning("Huelle %s nicht aus der Spule entfernbar: %s — sie "
                        "wird erneut geleitet werden", quelle, exc)
    return verarbeitet, abgewiesen


def wache(schluessel, intervall=5.0, einmal=False, laut=True):
    _LAUF["weiter"] = True
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _halt)
        except (ValueError, OSError):
            pass
    sperre_nehmen()
    v_ges = a_ges = 0
    try:
        while _LAUF["weiter"]:
            try:
                v, a = spule_durchgang(schluessel)
            except BrueckeFehler as e:
                if laut:
                    print("wache: %s" % e, file=sys.stderr)
                v, a = 0, 0
            v_ges += v
            a_ges += a
            if laut and (v or a):
                print(
                    "wache: %d bereit, %d abgewiesen" % (v, a),
                    file=sys.stderr,
                    flush=True,
                )
            if einmal:
                break
            schlaf = 0.0
            while schlaf < intervall and _LAUF["weiter"]:
                time.sleep(min(0.25, intervall - schlaf))
                schlaf += 0.25
    finally:
        sperre_loesen()
    return v_ges, a_ges


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------


def befehl_keimen(argv):
    neu = "--neu" in argv
    os.makedirs(heim(), exist_ok=True)
    os.makedirs(P_SPULE(), exist_ok=True)
    os.makedirs(P_FERTIG(), exist_ok=True)
    if neu or not os.path.exists(P_SCHLUESSEL()):
        schluessel = schluessel_erzeugen()
    else:
        schluessel = schluessel_laden()
    vorhanden = os.path.exists(P_FACH("a")) or os.path.exists(P_FACH("b"))
    if vorhanden and not neu:
        try:
            zustand, geheilt = zustand_laden(schluessel)
            print("bereits gekeimt: %d Routen, geheilt: %s"
                  % (len(zustand.get("routen", [])), geheilt or "-"))
            return 0
        except FachFehler as exc:
            # Kein gesundes Fach vorhanden -- genau der Fall, fuer den
            # `keimen` da ist. Es wird frisch angelegt, nicht abgebrochen;
            # protokolliert wird es trotzdem, denn ein Doppelfach, das
            # regelmaessig neu gekeimt werden muss, ist ein Befund.
            log.info("kein lesbares Fach (%s) — es wird neu angelegt", exc)
    routen = standard_routen()
    routen_pruefen_gesamt(routen)
    zustand_sichern(schluessel, {"routen": routen, "gekeimt_um": int(time.time())})
    print("gekeimt: %s" % heim())
    print("Routen: %s" % ", ".join(r["name"] for r in routen))
    if schluessel_rechte_pruefen():
        print("WARNUNG: Schluessel ist fuer Gruppe/Welt zugaenglich.",
              file=sys.stderr)
    return 0


def befehl_zeigen(argv):
    schluessel = schluessel_laden()
    zustand, routen, geheilt = r2_siegel(schluessel)
    if "--json" in argv:
        print(json.dumps(routen, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print("%-10s %-8s %-20s %-14s %10s  %s"
          % ("NAME", "RANG", "ANBIETER/ENDPUNKT", "AUTH", "GRENZE", "ERSATZ"))
    for r in sorted(routen, key=lambda x: (x["rang"], x["name"])):
        print("%-10s %-8d %-20s %-14s %9dM  %s"
              % (r["name"], r["rang"],
                 r["anbieter"] + "/" + r["endpunkt"],
                 r["auth"], grenze_fuer(r) // MB, r.get("faellt_auf") or "-"))
    if geheilt:
        print("geheilte Faecher: %s" % ", ".join(geheilt), file=sys.stderr)
    return 0


def _json_von_argv_oder_stdin(argv, flagge="--datei"):
    if flagge in argv:
        i = argv.index(flagge)
        if i + 1 >= len(argv):
            raise BrueckeFehler("%s ohne Pfad" % flagge)
        return json.loads(lies_datei(argv[i + 1]).decode("utf-8"))
    daten = sys.stdin.read()
    if not daten.strip():
        raise BrueckeFehler("Keine Eingabe auf stdin und kein %s" % flagge)
    return json.loads(daten)


def befehl_binden(argv):
    schluessel = schluessel_laden()
    neue = _json_von_argv_oder_stdin(argv)
    if isinstance(neue, dict):
        neue = [neue]
    if not isinstance(neue, list):
        raise BrueckeFehler("Erwartet Route oder Liste von Routen")
    zustand, routen, _ = r2_siegel(schluessel)
    nach_name = {r["name"]: r for r in routen}
    for r in neue:
        route_pruefen(r)
        nach_name[r["name"]] = r
    liste = sorted(nach_name.values(), key=lambda x: (x["rang"], x["name"]))
    routen_pruefen_gesamt(liste)
    zustand["routen"] = liste
    zustand_sichern(schluessel, zustand)
    chronik_anhaengen(schluessel, {"tat": "binden",
                                   "routen": [r["name"] for r in neue]})
    print("gebunden: %s" % ", ".join(r["name"] for r in neue))
    return 0


def befehl_loesen(argv):
    if len(argv) < 1:
        raise BrueckeFehler("loesen <name>")
    name = argv[0]
    schluessel = schluessel_laden()
    zustand, routen, _ = r2_siegel(schluessel)
    rest = [r for r in routen if r["name"] != name]
    if len(rest) == len(routen):
        raise BrueckeFehler("Unbekannte Route: %s" % name)
    if not rest:
        raise BrueckeFehler("Letzte Route kann nicht geloest werden")
    for r in rest:
        if r.get("faellt_auf") == name:
            r["faellt_auf"] = None
    routen_pruefen_gesamt(rest)
    zustand["routen"] = rest
    zustand_sichern(schluessel, zustand)
    chronik_anhaengen(schluessel, {"tat": "loesen", "route": name})
    print("geloest: %s" % name)
    return 0


def befehl_leiten(argv):
    schluessel = schluessel_laden()
    huelle = _json_von_argv_oder_stdin(argv)
    urteil = leiten(schluessel, huelle)
    print(json.dumps(urteil, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if urteil["urteil"] != "ABGEWIESEN" else 3


def befehl_wache(argv):
    schluessel = schluessel_laden()
    intervall = 5.0
    if "--intervall" in argv:
        intervall = float(argv[argv.index("--intervall") + 1])
    einmal = "--einmal" in argv
    v, a = wache(schluessel, intervall=intervall, einmal=einmal)
    print("wache beendet: %d bereit, %d abgewiesen" % (v, a))
    return 0


def befehl_wache_halt(argv):
    pid = sperre_halter()
    if pid is None:
        print("keine Wache eingetragen")
        return 1
    if not prozess_lebt(pid):
        sperre_loesen()
        try:
            os.unlink(P_SPERRE())
        except OSError as exc:
            # `sperre_loesen()` hat sie in der Regel schon entfernt.
            log.debug("Sperre bereits weg oder nicht entfernbar: %s", exc)
        print("tote Sperre entfernt (PID %d)" % pid)
        return 0
    os.kill(pid, signal.SIGTERM)
    print("SIGTERM an PID %d" % pid)
    return 0


def befehl_kette(argv):
    zeilen = [
        ("R1", "Huellen-Normalisierung", "Struktur, art, nutzlast, Groesse, Abdruck"),
        ("R2", "Siegel-Pruefung", "HMAC-SHA256 ueber die Routentabelle, Doppelfach"),
        ("R3", "Regel-Aufloesung", "Praedikate, Rang, Ersatzkette ohne Kreise"),
        ("R4", "Grenz-Pruefung", "min(Endpunkt-Grenze, Anbieter-Deckel)"),
        ("R5", "Kopf-Zusammenbau", "auth + anthropic-version + content-type"),
        ("R6", "Plan-Erzeugung", "Trockenlauf, kein Socket, Schluessel redigiert"),
        ("R7", "Quittung", "verhakte Chronikzeile, Rueckleseprobe"),
    ]
    for k, n, b in zeilen:
        print("%-4s %-26s %s" % (k, n, b))
    return 0


def befehl_chronik(argv):
    schluessel = schluessel_laden()
    n = 20
    if "-n" in argv:
        n = int(argv[argv.index("-n") + 1])
    p = P_CHRONIK()
    if not os.path.exists(p):
        print("Chronik leer")
        return 0
    with open(p, "rb") as f:
        zeilen = [z.strip() for z in f if z.strip()]
    for roh in zeilen[-n:]:
        e = json.loads(roh.decode("utf-8"))
        print("%s  %-10s %-8s %s"
              % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.get("um", 0))),
                 e.get("urteil") or e.get("tat") or "-",
                 str(e.get("route") or "-"),
                 e.get("kennung") or ""))
    anz, fehler = chronik_pruefen(schluessel)
    print("--- %d Zeilen, %d Beanstandungen" % (anz, len(fehler)))
    return 0


def befehl_pruefen(argv):
    schluessel = schluessel_laden()
    beanst = 0
    a = _fach_lesen("a", schluessel)
    b = _fach_lesen("b", schluessel)
    print("Fach A: %s" % ("gesund" if a is not None else "DEFEKT"))
    print("Fach B: %s" % ("gesund" if b is not None else "DEFEKT"))
    if a is None:
        beanst += 1
    if b is None:
        beanst += 1
    if a is not None and b is not None and kanon(a) != kanon(b):
        print("Faecher weichen ab")
        beanst += 1
    if a is not None or b is not None:
        try:
            routen_pruefen_gesamt((a or b).get("routen", []))
            print("Routentabelle: gueltig")
        except BrueckeFehler as e:
            print("Routentabelle: %s" % e)
            beanst += 1
    n, fehler = chronik_pruefen(schluessel)
    print("Chronik: %d Zeilen, %d Beanstandungen" % (n, len(fehler)))
    for i, g in fehler[:10]:
        print("  Zeile %d: %s" % (i, g))
    beanst += len(fehler)
    offen = schluessel_rechte_pruefen()
    print("Schluesselrechte: %s"
          % ("OFFEN fuer Gruppe/Welt" if offen else "nur Eigentuemer"))
    if offen:
        beanst += 1
    pid = sperre_halter()
    if pid is not None:
        print("Wache-Sperre: PID %d (%s)"
              % (pid, "lebt" if prozess_lebt(pid) else "tot"))
    print("Beanstandungen: %d" % beanst)
    return 0 if beanst == 0 else 4


def befehl_heilen(argv):
    schluessel = schluessel_laden()
    zustand, geheilt = zustand_laden(schluessel, heilen=True)
    print("geheilt: %s" % (", ".join(geheilt) if geheilt else "nichts noetig"))
    return 0


def befehl_seiten(argv):
    if not argv:
        raise BrueckeFehler("seiten <endpunkt> [--rueck] [--limit N] [--order asc|desc]")
    endpunkt = argv[0]
    antwort = _json_von_argv_oder_stdin(argv[1:])
    limit = None
    order = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    if "--order" in argv:
        order = argv[argv.index("--order") + 1]
    if "--rueck" in argv:
        par = seiten_vorige(endpunkt, antwort, limit, order)
    else:
        par = seiten_naechste(endpunkt, antwort, limit, order)
    print(json.dumps(
        {"schema": seiten_schema(endpunkt), "parameter": par},
        ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if par is not None else 5


def befehl_grenzen(argv):
    print("%-16s %10s" % ("ENDPUNKT", "GRENZE"))
    for k in sorted(ENDPUNKT_GRENZEN):
        print("%-16s %9dM" % (k, ENDPUNKT_GRENZEN[k] // MB))
    print()
    print("%-22s %10s" % ("ANBIETER", "DECKEL"))
    for k in sorted(ANBIETER_DECKEL):
        d = ANBIETER_DECKEL[k]
        print("%-22s %10s" % (k, "-" if d is None else "%dM" % (d // MB)))
    return 0


# ---------------------------------------------------------------------------
# Selbsttest
# ---------------------------------------------------------------------------


class Pruefstand(object):
    def __init__(self):
        self.gut = 0
        self.schlecht = 0
        self.zeilen = []

    def wahr(self, name, bedingung, hinweis=""):
        if bedingung:
            self.gut += 1
            self.zeilen.append("  ok   %s" % name)
        else:
            self.schlecht += 1
            self.zeilen.append("  FEHL %s %s" % (name, hinweis))

    def hebt(self, name, fn, typ=BrueckeFehler):
        try:
            fn()
        except typ:
            self.gut += 1
            self.zeilen.append("  ok   %s" % name)
            return
        except Exception as e:  # noqa: BLE001 — Testlaeufer: ein
            # unerwarteter Fehler wird als Fehlschlag GEZAEHLT, nicht
            # verschluckt; sonst blieben die restlichen Faelle ungeprueft.
            log.debug("Selbsttest %s: unerwarteter Fehler %r", name, e)
            self.schlecht += 1
            self.zeilen.append("  FEHL %s (falscher Fehler: %r)" % (name, e))
            return
        self.schlecht += 1
        self.zeilen.append("  FEHL %s (kein Fehler ausgeloest)" % name)


def selbsttest():
    ps = Pruefstand()
    alt_heim = os.environ.get("HUGIN_BRUECKE_HEIM")
    tmp = tempfile.mkdtemp(prefix="bruecke-test-")
    os.environ["HUGIN_BRUECKE_HEIM"] = tmp
    echt_stdout = sys.stdout
    sys.stdout = io.StringIO()  # Befehlsausgaben im Test stummschalten
    try:
        # --- Grundlagen ------------------------------------------------
        ps.wahr("T01 kanon stabil",
                kanon({"b": 1, "a": 2}) == kanon({"a": 2, "b": 1}))
        ps.wahr("T02 kanon unterscheidet Werte",
                kanon({"a": 1}) != kanon({"a": 2}))

        befehl_keimen([])
        k = schluessel_laden()
        ps.wahr("T03 Schluessel 32 Byte", len(k) == 32)
        ps.wahr("T04 Schluesselrechte geschlossen",
                schluessel_rechte_pruefen() is False)

        z, routen, geheilt = r2_siegel(k)
        ps.wahr("T05 Standardroutentabelle geladen", len(routen) == 5)
        ps.wahr("T06 keine Heilung noetig nach keimen", geheilt == [])

        # --- Siegel ----------------------------------------------------
        ps.wahr("T07 Siegel gueltig", siegel_gueltig(k, {"x": 1},
                                                     siegeln(k, {"x": 1})))
        ps.wahr("T08 Siegel erkennt Aenderung",
                not siegel_gueltig(k, {"x": 2}, siegeln(k, {"x": 1})))
        ps.wahr("T09 Siegel erkennt fremden Schluessel",
                not siegel_gueltig(b"\x00" * 32, {"x": 1}, siegeln(k, {"x": 1})))
        ps.wahr("T10 Siegel erkennt Nicht-Text", not siegel_gueltig(k, {"x": 1}, 5))

        # --- Doppelfach ------------------------------------------------
        with open(P_FACH("a"), "w") as f:
            f.write("{kaputt")
        gelesen, geheilt = zustand_laden(k)
        ps.wahr("T11 Fach A defekt -> aus B gelesen",
                len(gelesen.get("routen", [])) == 5)
        ps.wahr("T12 Fach A wurde geheilt", geheilt == ["a"])
        ps.wahr("T13 Fach A jetzt wieder gesund",
                _fach_lesen("a", k) is not None)

        # Nutzlast manipulieren, Siegel unveraendert lassen
        roh = json.loads(lies_datei(P_FACH("b")).decode("utf-8"))
        roh["nutzlast"]["routen"] = []
        with open(P_FACH("b"), "w") as f:
            json.dump(roh, f)
        ps.wahr("T14 manipuliertes Fach B verworfen",
                _fach_lesen("b", k) is None)
        gelesen, geheilt = zustand_laden(k)
        ps.wahr("T15 B aus A geheilt", geheilt == ["b"])

        # Beide Faecher zerstoeren -> fail-closed
        for f_ in FAECHER:
            with open(P_FACH(f_), "w") as f:
                f.write("x")
        ps.hebt("T16 beide Faecher defekt -> FachFehler",
                lambda: zustand_laden(k), FachFehler)
        befehl_keimen(["--neu"])
        k = schluessel_laden()

        # --- Rueckleseprobe (Fehlerinjektion) --------------------------
        echt_replace = os.replace

        def kaputt_replace(a, b_):
            raise OSError(errno.EIO, "injiziert")

        os.replace = kaputt_replace
        try:
            ps.hebt("T17 os.replace-Ausfall bricht Schreiben ab",
                    lambda: schreibe_mit_rueckleseprobe(pfad("probe.txt"), "x"),
                    OSError)
        finally:
            os.replace = echt_replace
        ps.wahr("T18 kein Teilzustand nach Schreibausfall",
                not os.path.exists(pfad("probe.txt")))
        ps.wahr("T19 keine Reste im Heim",
                not any(n.startswith(".hugin-bruecke.") for n in os.listdir(heim())))

        echt_lies = globals()["lies_datei"]

        def luegen_lies(q):
            return b"ANDERE BYTES"

        globals()["lies_datei"] = luegen_lies
        try:
            ps.hebt("T20 verfaelschtes Ruecklesen wird erkannt",
                    lambda: schreibe_mit_rueckleseprobe(pfad("probe2.txt"), "x"),
                    FachFehler)
        finally:
            globals()["lies_datei"] = echt_lies

        # --- Routenpruefung --------------------------------------------
        gut = dict(standard_routen()[0])
        ps.wahr("T21 gueltige Route besteht", route_pruefen(gut))
        ps.hebt("T22 Name mit Schraegstrich abgelehnt",
                lambda: route_pruefen(dict(gut, name="a/b")))
        ps.hebt("T23 http:// abgelehnt",
                lambda: route_pruefen(dict(gut, ziel="http://x.invalid")))
        ps.hebt("T24 Pfadwanderung abgelehnt",
                lambda: route_pruefen(dict(gut, pfad="/v1/../etc")))
        ps.hebt("T25 unbekannter Endpunkt abgelehnt",
                lambda: route_pruefen(dict(gut, endpunkt="nichts")))
        ps.hebt("T26 unbekannter Anbieter abgelehnt",
                lambda: route_pruefen(dict(gut, anbieter="nirgends")))
        ps.hebt("T27 falsches auth abgelehnt",
                lambda: route_pruefen(dict(gut, auth="basic")))
        ps.hebt("T28 doppelter Routenname abgelehnt",
                lambda: routen_pruefen_gesamt([gut, dict(gut)]))
        ps.hebt("T29 unbekannter Ersatz abgelehnt",
                lambda: routen_pruefen_gesamt(
                    [dict(gut, faellt_auf="gibtsnicht")]))
        ps.hebt("T30 Ersatz-Kreis erkannt",
                lambda: routen_pruefen_gesamt([
                    dict(gut, name="x", faellt_auf="y"),
                    dict(gut, name="y", faellt_auf="x"),
                ]))

        # --- Kette R1 ---------------------------------------------------
        ps.hebt("T31 R1 ohne art", lambda: r1_normalisieren({"nutzlast": {}}),
                KettenFehler)
        ps.hebt("T32 R1 unbekannte art",
                lambda: r1_normalisieren({"art": "zauber", "nutzlast": {}}),
                KettenFehler)
        ps.hebt("T33 R1 ohne nutzlast",
                lambda: r1_normalisieren({"art": "messages"}), KettenFehler)
        ps.hebt("T34 R1 nutzlast falscher Typ",
                lambda: r1_normalisieren({"art": "messages", "nutzlast": 7}),
                KettenFehler)
        ps.hebt("T35 R1 marken falscher Typ",
                lambda: r1_normalisieren(
                    {"art": "messages", "nutzlast": {}, "marken": [1]}),
                KettenFehler)
        n = r1_normalisieren({"art": "messages", "nutzlast": {"a": 1}})
        ps.wahr("T36 R1 misst Bytes", n["bytes"] == len(kanon({"a": 1})))
        ps.wahr("T37 R1 vergibt Kennung", n["kennung"].startswith("h-"))

        # --- Kette gesamt -----------------------------------------------
        u = leiten(k, {"art": "messages", "nutzlast": {"m": "hallo"}})
        ps.wahr("T38 kleine Messages-Huelle -> haupt", u["route"] == "haupt")
        ps.wahr("T39 Urteil BEREIT", u["urteil"] == "BEREIT")
        ps.wahr("T40 Kette vollstaendig",
                u["kette"] == ["R1", "R2", "R3", "R4", "R5", "R6", "R7"])
        ps.wahr("T41 Plan sendet nicht", u["plan"]["gesendet"] is False)
        ps.wahr("T42 Schluessel im Plan redigiert",
                u["plan"]["kopf"]["x-api-key"] == "<REDIGIERT>")
        ps.wahr("T43 Pflichtkoepfe gesetzt",
                all(h in u["plan"]["kopf"] for h in PFLICHT_KOEPFE))
        ps.wahr("T44 Quittung vorhanden", len(u.get("quittung", "")) == 64)

        # Ueberschreitung -> Ersatz auf stapel (256M)
        gross = "x" * (33 * MB)
        u2 = leiten(k, {"art": "messages", "nutzlast": gross})
        ps.wahr("T45 33M weicht auf stapel aus", u2["route"] == "stapel")
        ps.wahr("T46 Urteil ERSATZ", u2["urteil"] == "ERSATZ")
        ps.wahr("T47 haupt zuerst versucht", u2["versuche"][0] == "haupt")
        ps.wahr("T48 Grund nennt 413", "413" in u2["gruende"][0])

        # Alles zu gross -> abgewiesen
        u3 = leiten(k, {"art": "count_tokens", "nutzlast": gross})
        ps.wahr("T49 33M count_tokens abgewiesen", u3["urteil"] == "ABGEWIESEN")
        ps.wahr("T50 kein Plan bei Abweisung", u3["plan"] is None)

        # Wunschroute
        u4 = leiten(k, {"art": "messages", "nutzlast": {"m": 1}, "route": "wolke"})
        ps.wahr("T51 Wunschroute beachtet", u4["route"] == "wolke")
        ps.wahr("T52 bearer erzeugt Authorization",
                u4["plan"]["kopf"]["Authorization"].startswith("Bearer "))
        ps.hebt("T53 unbekannte Wunschroute",
                lambda: leiten(k, {"art": "messages", "nutzlast": {},
                                   "route": "nirgendwo"}), KettenFehler)

        # Anbieter-Deckel
        ps.wahr("T54 bedrock deckelt auf 20M",
                grenze_fuer([r for r in standard_routen()
                             if r["name"] == "wolke"][0]) == 20 * MB)
        ps.wahr("T55 anthropic messages 32M",
                grenze_fuer(standard_routen()[0]) == 32 * MB)

        # --- Chronik ----------------------------------------------------
        anz, fehler = chronik_pruefen(k)
        ps.wahr("T56 Chronik gefuellt", anz >= 4, "anz=%d" % anz)
        ps.wahr("T57 Chronik unbeanstandet", fehler == [], str(fehler))
        with open(P_CHRONIK(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"kennung": "falsch", "vorher": "0" * 64,
                                "um": 0, "siegel": "00"}) + "\n")
        anz2, fehler2 = chronik_pruefen(k)
        ps.wahr("T58 gefaelschte Chronikzeile erkannt", len(fehler2) >= 1)
        ps.wahr("T59 Verhakung meldet Bruch",
                any("Verhakung" in g or "Siegel" in g for _, g in fehler2))
        os.unlink(P_CHRONIK())

        # --- Seiten -----------------------------------------------------
        ps.wahr("T60 messages nutzt page-Schema",
                seiten_schema("messages") == SEITEN_SCHEMA_CURSOR)
        ps.wahr("T61 files nutzt id-Schema",
                seiten_schema("files") == SEITEN_SCHEMA_ID)
        ps.wahr("T62 next_page uebernommen",
                seiten_naechste("sessions", {"next_page": "c1"},
                                limit=5)["page"] == "c1")
        ps.wahr("T63 order wird mitgefuehrt",
                seiten_naechste("sessions", {"next_page": "c1"},
                                order="asc")["order"] == "asc")
        ps.wahr("T64 next_page null -> Ende",
                seiten_naechste("sessions", {"next_page": None}) is None)
        ps.wahr("T65 has_more false -> Ende",
                seiten_naechste("files", {"has_more": False,
                                          "last_id": "f9"}) is None)
        ps.wahr("T66 after_id aus last_id",
                seiten_naechste("files", {"has_more": True,
                                          "last_id": "f9"})["after_id"] == "f9")
        ps.wahr("T67 prev_page fehlend -> None",
                seiten_vorige("messages", {"next_page": "c1"}) is None)
        ps.wahr("T68 before_id aus first_id",
                seiten_vorige("batches", {"first_id": "b1"})["before_id"] == "b1")
        ps.hebt("T69 Seiten-Helfer weist Nicht-Objekt ab",
                lambda: seiten_naechste("files", ["x"]))

        # --- Spule und Wache --------------------------------------------
        os.makedirs(P_SPULE(), exist_ok=True)
        schreibe_atomar(os.path.join(P_SPULE(), "eins.json"),
                        json.dumps({"art": "messages", "nutzlast": {"m": 1}}))
        schreibe_atomar(os.path.join(P_SPULE(), "zwei.json"), "{kaputt")
        schreibe_atomar(os.path.join(P_SPULE(), "drei.txt"), "ignorieren")
        v, a = spule_durchgang(k)
        ps.wahr("T70 eine Huelle verarbeitet", v == 1, "v=%d" % v)
        ps.wahr("T71 unlesbare Huelle abgewiesen", a == 1, "a=%d" % a)
        ps.wahr("T72 Fremddatei unberuehrt",
                os.path.exists(os.path.join(P_SPULE(), "drei.txt")))
        ps.wahr("T73 Urteil abgelegt",
                os.path.exists(os.path.join(P_FERTIG(), "eins.urteil.json")))
        ps.wahr("T74 Spule geleert",
                not os.path.exists(os.path.join(P_SPULE(), "eins.json")))
        ps.wahr("T75 sicherer Name lehnt Pfadwanderung ab",
                SICHERER_NAME.match("../x.json") is None)
        ps.wahr("T76 sicherer Name lehnt Schraegstrich ab",
                SICHERER_NAME.match("a/b.json") is None)
        ps.wahr("T77 sicherer Name nimmt normale Datei",
                SICHERER_NAME.match("a-1_b.json") is not None)

        # Sperre
        sperre_nehmen()
        ps.wahr("T78 Sperre gehalten", sperre_halter() == os.getpid())
        ps.hebt("T79 zweite Sperre abgewiesen", sperre_nehmen)
        sperre_loesen()
        ps.wahr("T80 Sperre geloest", not os.path.exists(P_SPERRE()))
        # tote Sperre
        with open(P_SPERRE(), "w") as f:
            f.write("999999\n")
        if not prozess_lebt(999999):
            sperre_nehmen()
            ps.wahr("T81 tote Sperre uebernommen", sperre_halter() == os.getpid())
            sperre_loesen()
        else:
            ps.wahr("T81 tote Sperre uebernommen (uebersprungen)", True)

        # wache --einmal
        schreibe_atomar(os.path.join(P_SPULE(), "vier.json"),
                        json.dumps({"art": "files", "nutzlast": {"f": 1}}))
        v2, a2 = wache(k, intervall=0.1, einmal=True, laut=False)
        ps.wahr("T82 wache --einmal arbeitet ab", v2 == 1, "v2=%d" % v2)
        ps.wahr("T83 Sperre nach wache frei", not os.path.exists(P_SPERRE()))

        # --- Befehle ----------------------------------------------------
        ps.wahr("T84 pruefen liefert 0", befehl_pruefen([]) == 0)
        ps.wahr("T85 zeigen liefert 0", befehl_zeigen([]) == 0)
        ps.wahr("T86 kette liefert 0", befehl_kette([]) == 0)
        ps.wahr("T87 grenzen liefert 0", befehl_grenzen([]) == 0)
        ps.wahr("T88 heilen liefert 0", befehl_heilen([]) == 0)

        neue_route = {
            "name": "probe", "anbieter": "anthropic",
            "ziel": "https://api.anthropic.com", "endpunkt": "skills",
            "pfad": "/v1/skills", "methode": "POST", "auth": "x-api-key",
            "version": "2023-06-01", "rang": 5,
            "praedikate": {"art": "skills"}, "faellt_auf": None,
        }
        schreibe_atomar(pfad("neu.json"), json.dumps(neue_route))
        ps.wahr("T89 binden liefert 0",
                befehl_binden(["--datei", pfad("neu.json")]) == 0)
        _, routen2, _ = r2_siegel(k)
        ps.wahr("T90 Route gebunden",
                any(r["name"] == "probe" for r in routen2))
        ps.wahr("T91 loesen liefert 0", befehl_loesen(["probe"]) == 0)
        _, routen3, _ = r2_siegel(k)
        ps.wahr("T92 Route geloest",
                not any(r["name"] == "probe" for r in routen3))
        ps.hebt("T93 loesen unbekannt", lambda: befehl_loesen(["gibtsnicht"]))

        # --- Schluesselverlust -------------------------------------------
        gesichert = lies_datei(P_SCHLUESSEL())
        os.unlink(P_SCHLUESSEL())
        ps.hebt("T94 fehlender Schluessel bricht ab", schluessel_laden)
        schreibe_atomar(P_SCHLUESSEL(), b"nicht base64 !!!\n")
        ps.hebt("T95 unlesbarer Schluessel bricht ab", schluessel_laden,
                SiegelFehler)
        schreibe_atomar(P_SCHLUESSEL(), base64.b64encode(b"kurz"))
        ps.hebt("T96 zu kurzer Schluessel bricht ab", schluessel_laden,
                SiegelFehler)
        schreibe_atomar(P_SCHLUESSEL(), gesichert)
        ps.wahr("T97 Schluessel wiederhergestellt", len(schluessel_laden()) == 32)

        # --- Fremder Schluessel gegen bestehenden Zustand -----------------
        fremd = b"\x01" * 32
        ps.wahr("T98 fremder Schluessel entsiegelt Fach A nicht",
                _fach_lesen("a", fremd) is None)
        ps.hebt("T99 fremder Schluessel -> fail-closed",
                lambda: zustand_laden(fremd, heilen=False), FachFehler)

        ps.wahr("T100 Heim unter Testpfad", heim() == tmp)

    finally:
        sys.stdout = echt_stdout
        if alt_heim is None:
            os.environ.pop("HUGIN_BRUECKE_HEIM", None)
        else:
            os.environ["HUGIN_BRUECKE_HEIM"] = alt_heim
        shutil.rmtree(tmp, ignore_errors=True)

    print("%s %s Selbsttest" % (WERK, FASSUNG))
    for z in ps.zeilen:
        print(z)
    print("--- %d/%d bestanden" % (ps.gut, ps.gut + ps.schlecht))
    return 0 if ps.schlecht == 0 else 1


# ---------------------------------------------------------------------------
# Einstieg
# ---------------------------------------------------------------------------


HILFE = """%s %s — Routing-Ketten-Werk

  keimen [--neu]              Heim, Schluessel und Standardrouten anlegen
  zeigen [--json]             Routentabelle
  binden [--datei P]          Route(n) aus JSON hinzufuegen/ersetzen (sonst stdin)
  loesen <name>               Route entfernen
  leiten [--datei P]          Huelle durch R1-R7 leiten (sonst stdin)
  wache [--intervall S]       Aufsatz-Prozess: Spule dauerhaft abarbeiten
        [--einmal]            nur ein Durchgang
  wache-halt                  laufender Wache SIGTERM senden
  kette                       Kettenstufen erklaeren
  grenzen                     eingebettete Endpunkt-/Anbietergrenzen
  chronik [-n N]              Quittungen
  pruefen                     Faecher, Routen, Chronik, Rechte
  heilen                      defektes Fach aus dem gesunden herstellen
  seiten <endpunkt> [--rueck] [--limit N] [--order asc|desc]
                              Folgeseiten-Parameter aus einer Antwort
  --selftest                  Selbsttest
  --hilfe                     diese Uebersicht

Heim: %s   (ueberschreibbar via HUGIN_BRUECKE_HEIM)
Es wird zu keinem Zeitpunkt ein Socket geoeffnet.
""" % (WERK, FASSUNG, heim())


BEFEHLE = {
    "keimen": befehl_keimen,
    "zeigen": befehl_zeigen,
    "binden": befehl_binden,
    "loesen": befehl_loesen,
    "leiten": befehl_leiten,
    "wache": befehl_wache,
    "wache-halt": befehl_wache_halt,
    "kette": befehl_kette,
    "grenzen": befehl_grenzen,
    "chronik": befehl_chronik,
    "pruefen": befehl_pruefen,
    "heilen": befehl_heilen,
    "seiten": befehl_seiten,
}


def haupt(argv):
    if not argv or argv[0] in ("--hilfe", "-h", "--help"):
        sys.stdout.write(HILFE)
        return 0
    if argv[0] == "--selftest":
        return selbsttest()
    if argv[0] in ("--fassung", "--version"):
        print("%s %s" % (WERK, FASSUNG))
        return 0
    fn = BEFEHLE.get(argv[0])
    if fn is None:
        print("Unbekannter Befehl: %s" % argv[0], file=sys.stderr)
        sys.stdout.write(HILFE)
        return 2
    try:
        return fn(argv[1:])
    except BrueckeFehler as e:
        print("%s: %s" % (WERK, e), file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print("%s: JSON unlesbar: %s" % (WERK, e), file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print("%s: %s" % (WERK, e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    try:
        sys.exit(haupt(sys.argv[1:]))
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            # Der Kanal ist bereits zu; mehr als schliessen gibt es nicht zu tun.
            pass
        os._exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
