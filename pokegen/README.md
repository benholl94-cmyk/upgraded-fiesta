# pokegen — Normkonformitäts-Engine für Pokémon-Datensätze

Beantwortet zwei Fragen:

1. **Ist dieser Datensatz normkonform?** — `check()` listet jeden Regelverstoß mit Namen.
2. **Wie sieht mein Wunsch-Pokémon aus, wenn es normkonform sein soll?** — `generate()` baut es, oder sagt präzise, warum es das nicht geben kann.

Stdlib-only Python, keine Netzwerkaufrufe, keine Konsolen-Anbindung.

## Architektur-Invariante

> Der Generator erfindet **nie** eine Begegnung. Er wählt eine Zeile aus
> `encounters.ENCOUNTERS` und legt die Constraints an, die *diese* Zeile erlaubt.

Gleiches Prinzip wie `hm-tool-exec`: die Anfrage *wählt* aus festen Einträgen, sie *baut* keinen. Wenn kein Eintrag den Wunsch erfüllt, lautet die richtige Antwort „dieses Pokémon kann nicht legitim existieren" — nicht „Tabelle erweitern".

## Nutzung

```sh
python3 -m pokegen gen Garchomp --nature Jolly --ability "Rough Skin" \
    --evs "0/252/0/0/4/252" --move Earthquake --move Outrage --shiny
python3 -m pokegen gen "Flutter Mane" --shiny      # -> ACHTUNG, shiny-locked
python3 -m pokegen check record.json
python3 -m pokegen list encounters
```

Exit-Codes bei `gen`: `0` = Wunsch exakt erfüllt, `1` = nur nach Aufgabe einer Eigenschaft erfüllt (steht in `dropped`), `2` = unmöglich.

Die Relaxierung ist **nie still** — `Result.exact` ist `False`, sobald etwas aufgegeben wurde. Ein Validator, der leise etwas anderes liefert als verlangt, ist schlimmer als keiner.

## Defensiver Einsatz

Der eigentliche Alltagsnutzen: `check()` auf ein Pokémon anwenden, das dir jemand **getauscht** hat. Die Engine sagt dir, ob es genned ist, bevor es in deine HOME-Box wandert. `Violation.fatal` trennt „reparierbar" (EV-Spread) von „kann nie legal sein" (shiny-locked, unlernbare Attacke).

## Implementierte Regeln

Encounter-Existenz · Level-/Fundlevel-Konsistenz · Fundort · Ball-Pool je Methode (Master Ball wild ja / Raid nein, Ei erbt) · Shiny-Locks · garantierte 31er-IVs je Raid-Stufe · IV-/EV-Grenzen (252 pro Wert, 510 gesamt) · Fähigkeit inkl. HA-Quelle · Geschlechterverhältnis · Tera-Typ · Attacken-Herkunft (Level-up / TM / Ei) · Ei-Attacken nur aus ei-fähigen Quellen · TID/SID · Spitzname-Länge · Versions-Exklusivität

## Bekannte Lücken — bewusst offen, nicht halb implementiert

- **Datensatz ist ein kuratierter Ausschnitt.** 11 Spezies, 17 Encounter. PKHeX transportiert mehrere MB extrahierter Binärtabellen; das hier ist klein genug, um es per Auge zu auditieren — das ist der Zweck, nicht ein Mangel an Ehrgeiz. Neue Spezies brauchen **keine** Codeänderung, nur einen Tabelleneintrag.
- **Kein Evolutions-Level-Check.** Ein Lv.1-Garchomp wird derzeit nicht beanstandet, obwohl Garchomp erst ab Lv.48 existiert. Braucht Evolutionsdaten in `species.py`.
- **Kein PID/EC-Modell.** Shiny ist ein Bool, nicht aus Trainer-ID und Encryption Constant abgeleitet. Für echte Byte-Ausgabe wäre das nötig.
- **Keine `.pk9`-Serialisierung.** Die Engine liefert ein Python-Objekt bzw. JSON, keine spielfertigen Bytes.
- **Keine Ribbons/Marks, keine Herkunftsspiel-Historie (HOME-Transferketten).**
- Die IV-Untergrenzen je Raid-Stufe und die Ball-Pools sind aus dokumentierter Spielmechanik von Hand eingetragen. Gegen die echten Tabellen gegenprüfen, bevor du dich darauf verlässt.

## Was hier bewusst nicht drin ist

Kein Injektionspfad auf die Konsole und kein Auto-Trade. Beides braucht CFW/sys-botbase — Umgehung technischer Schutzmaßnahmen (§95a UrhG) — und verteilt im Tauschfall Ban-Risiko an Dritte, die nicht gefragt wurden. Die Engine hier rechnet lokal und schickt nichts irgendwohin.
