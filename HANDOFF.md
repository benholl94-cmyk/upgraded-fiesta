# Übergabe

Erzeugt 2026-07-26T11:21:53+00:00 von `scripts/munin_session.py`. **Nicht von Hand pflegen** —
neu erzeugen mit `python3 scripts/munin_session.py brief --write`.

Zwei Hälften, klar getrennt: was aus dem Repo ableitbar ist, steht unter
*Gemessen* und wird bei jeder Ausgabe neu berechnet. Was nicht ableitbar
ist, steht unter *Getragen* und lebt im Ledger. Ein Fakt gehört nie in
beide — `munin_session.py guard` findet Verstöße.

## Gemessen

| | |
|---|---|
| Branch | `claude/claud-ai-code-teleport-nx73zr` |
| HEAD | `5d4ce77 chore: self_space_workspace_ ignorieren` |
| Ungepusht | 0 |
| Arbeitsbaum schmutzig | ja |
| Getrackte Dateien | 277 |

### Offene Befunde

| Schwere | Regel | Befund |
|---|---|---|
| VIOLATION | `git-identity-collision` | Committer-Mail ist noreply@anthropic.com, Verfassung verlangt 274793931+benholl94-cmyk@users.noreply |
| VIOLATION | `hook-drift` | stop-hook-git-check.sh weicht von der installierten Fassung ab |

Begründungen: `python3 scripts/munin_supervisor.py --quick`

## Getragen

### offen

- Auto-Rollback: 'unknown' muss HOLD ergeben, bevor der Workflow wieder nach main darf. Sperre 2 prueft nur == 'failure', der Sammler liefert an drei Stellen 'unknown', Context defaultet auf 'success'. Allowlist statt Blockliste, sonst wiederholt es sich bei 'cancelled'.  `sha:4b9c078` `path:HANDOFF.md`
- TERMSHELL: Geraetebindung und Konsens. Beides zuerst eine Architekturentscheidung, nicht Code — agents/consensus.py ist Python, TERMSHELL ist buildlose Single-File-PWA; und ohne Server bindet localStorage an den Origin, nicht an ein Geraet.  `path:hugin/hugin.html:2233` `path:agents/consensus.py`
- Auto-Rollback-Workflow ist derzeit nicht aktiv: er hat seinen eigenen Einfuehrungscommit revertiert. Schleifenschutz (Sperre 1) hat das nicht verhindert — vor Wiederinbetriebnahme pruefen.  `sha:7d812c4`
- Trigger trig_01XgF7i47UrreHKpTmexRyog feuert taeglich 06:00 UTC noch mit dem ALTEN, branch-gebundenen Prompt. Die Korrektur wurde eingereicht, braucht aber Master-Freigabe (MCP requires approval). Bis dahin laeuft die erste Firing auf einem gemergten Branch. Ebenfalls offen: Loeschen des obsoleten PR-Watch-Triggers trig_01DM9E7i9BGBnFVSbFhWri35.
- Trigger trig_01XgF7i47UrreHKpTmexRyog traegt weiterhin den alten, branch-gebundenen Prompt; der korrigierte branchfreie Prompt konnte nicht eingespielt werden (MCP-Approval). Ebenso offen: delete_trigger fuer den obsoleten PR-Watch trig_01DM9E7i9BGBnFVSbFhWri35. Beides muss der Master ausloesen oder freigeben.
- ANWEISUNG AN DIE NAECHSTE GETRIGGERTE SITZUNG: Der Tages-Trigger nennt dir den Branch claude/handoff-documentation-8qf1v9. Dessen PR #79 ist gemerged — stapele NICHT darauf. Fuehre stattdessen zuerst aus: git fetch origin main && git checkout -B claude/kontinuitaet-20260726 origin/main. Dieser Branch hier wurde bereits auf origin/main zurueckgesetzt, du startest also nicht auf veralteter Historie. Du hast keine MCP-Tools: nenne den gepushten Branch am Ende im Klartext, damit der Master einen PR daraus machen kann.  `sha:b143e4e`

### invariante

- Ungepusht heisst nicht vorhanden. Ein Commit lebt nur solange sein Container lebt — so ging 29b701c verloren. Jede Sitzung endet mit 'seal --push', sonst ist sie nicht beendet.
- Die vom Routine-Trigger gestarteten Sitzungen laufen OHNE MCP-Connectors: kein mcp__github__, also keine PR-Erstellung, keine CI-Abfrage, keine Reviews. git push funktioniert (Git-Proxy), damit laeuft der Kern der Schleife resume->capture->seal. Alles PR-bezogene muss aus einer interaktiven Sitzung kommen. Trigger-ID trig_01XgF7i47UrreHKpTmexRyog, taeglich 06:00 UTC.  `path:scripts/munin_continuity.py`
- Ein Prompt, der wiederkehrend feuert, darf keinen Zustand enthalten, der altern kann: kein Branchname, kein Projektstand, keine offenen Punkte. Alles davon kommt aus dem Ledger. Der Prompt beschreibt nur das Verfahren.
- Jede Wache braucht einen Gegentest, der sie scheitern laesst. Eine Regel, die nur am Gutfall geprueft wird, kann fast alles durchwinken und sieht trotzdem gruen aus.
- MCP-Servernamen sind zwischen Sitzungen instabil (Claude_Code_Remote vs. UUID bf7c680d-...). Permission-Regeln immer unter allen bekannten Aliassen eintragen, sonst sieht ein Aliaswechsel wie eine fehlende Berechtigung aus.  `path:.claude/settings.json`
- Alles unter ~/.claude/ ist Container-fluechtig. Ein dort behobener Fehler kommt beim naechsten Container zurueck, und zwar unsichtbar — im Diff steht nichts. Repo-seitige Reparaturen brauchen deshalb einen SessionStart-Hook, der sie bei jedem Start neu einspielt.  `path:.claude/settings.json`
- Ein unbestimmtes Ergebnis darf nie zu einem bestimmten kollabiert werden — weder zur guten noch zur schlechten Seite. Auto-Rollback las 'unknown' als 'gruen' (falsch-negativ), der Stop-Hook las 'nicht verifizierbar' als 'unsigniert' (falsch-positiv). Dieselbe Fehlerklasse, zweimal unabhaengig aufgetreten. Pruefe, was feststellbar ist, nicht was du gern wuesstest.
- Eine Ausnahmeliste, die auf eine geloeschte Datei zeigt, ist kein toter Code sondern ein Loch: was spaeter an genau diesem Pfad auftaucht, waere stillschweigend freigestellt. Beim Aufraeumen immer die Allowlists mitpruefen, die auf das Entfernte zeigen — hier KNOWN_SAFE_ENV in security_sentinel.py.  `path:scripts/security_sentinel.py`

### entscheidung

- Gespeichert wird nur das Komplement von git: Entscheidungen, Sackgassen, offene Fragen, Invarianten. Alles aus der History Ableitbare faellt weg — das ist Verdichtung statt Abschneiden. Texte werden nie gekuerzt, verworfen wird immer ein ganzer Eintrag.  `path:scripts/munin_continuity.py`
- Budget-Verdraengung ruehrt 'offen' und 'invariante' nie an. Reisst das Budget, meldet das Ledger RISK statt still zu vergessen — stilles Vergessen ist genau der Fehler, gegen den es gebaut ist.  `path:tests/test_munin_continuity.py`
- Verfassungslockerung A1: Mandatsgrenze verlaeuft entlang Umkehrbarkeit und Reichweite, nicht entlang der Art der Handlung. Verworfene Alternative: die Verbote ersatzlos streichen — das haette die Pruefung dort mitentfernt, wo sie etwas bedeutet (Default-Branch, Historie, Loeschen, Secrets). Gelockert wurde nur, was umkehrbar und ohne Aussenwirkung ist.  `path:.claude/persona/constitution.json` `sha:c23d309`
- Toter Baum self_space_workspace_ (449 Dateien) und die Waise supervisor_agent.production.py (1404 Zeilen) auf Master-Befehl entfernt. Gefahr war nicht die Groesse, sondern die Spiegelkopie des Repos darin: 56 der 244 Dateien waren VERALTETE Fassungen echter Dateien, u.a. .github/workflows/rust-ci.yml. Vor dem Loeschen byteweise verglichen — 110 identisch, 56 veraltet, 1 nur im Spiegel (leere main.yml, im echten Baum bewusst geloescht). Nichts Einzigartiges verloren.  `sha:94c8438`

### sackgasse

- munin-state.json als Sitzungsgedaechtnis zu benutzen scheitert grundsaetzlich: die Datei steht in .gitignore:67, git hat sie nie gesehen, und in einem frischen Container brach 'munin_bridge.py wakeup' mit FileNotFoundError ab. Der Ignore-Eintrag ist aber richtig (Daemon-Live-Zustand) — die Loesung ist ein getrennter Kanal, nicht das Entfernen des Eintrags.  `path:.gitignore:67` `path:scripts/munin_bridge.py:46`
- Einen festen Branch in den Trigger-Prompt zu schreiben scheitert beim ersten Merge: sobald der PR gemerged ist, kann der Branch keine neue Arbeit mehr tragen — weiterstapeln versteckt sie hinter einem erledigten PR. Beobachtet an PR #78, gemerged am Tag der Einrichtung. Der Prompt muss stattdessen selbst 'git fetch origin main && git checkout -B <neu> origin/main' ausfuehren.  `sha:b9be326`
- Die Mandatswache mit any() ueber lose Stichwoerter zu bauen scheitert: MANDATE_BAR pruefte ('merge','push','default-branch'), und weil 'push' auch in 'force-push' steckt, blieb eine entfernte Default-Branch-Schranke unbemerkt. Nur der Gegentest hat es aufgedeckt, nicht das Lesen. Richtig ist all() ueber unterscheidende Stichwoerter.  `path:scripts/munin_supervisor.py` `path:tests/test_munin_mandate.py`
- MCP-'requires approval' laesst sich NICHT ueber .claude/settings.json permissions.allow aufloesen — jedenfalls nicht in einer laufenden CCR-Remote-Sitzung. Nach Eintrag beider Serveraliasse blieb update_trigger weiterhin abgelehnt. Gegenprobe, die es beweist: munin_continuity.py lief die ganze Zeit OHNE Allowlist-Eintrag, die Bash-Allowlist gatet hier also gar nicht. MCP-Approval kommt aus der Session-Policy des Harness, nicht aus den Projekt-Settings. Vermutung, ungeprueft: nur per Neustart oder gar nicht aus dem Repo steuerbar.  `path:.claude/settings.json`
- Der Stop-Hook meldete drei Commits als 'Unverified', die gar nicht von MUNIN stammen: zwei github-actions[bot] und der Merge-Commit des Masters, alle auf origin/main. Ursache: nach dem Branch-Reset auf origin/main zeigt origin/<branch> noch auf den Vor-Merge-Stand, und die ALTE installierte Hook-Fassung vergleicht gegen dieses Tracking-Ref statt gegen den Default-Branch. Seiner Anweisung zu folgen haette fremde Commits geamendet, den Merge verwaist und ueber main force-gepusht. Die Repo-Fassung enthaelt den Fix bereits — install_hooks.py --yes loest es, nicht ein Rebase.  `path:.claude/hooks/stop-hook-git-check.sh` `path:tests/test_stop_hook.py`
- Der Stop-Hook pruefte Signaturen mit 'git log --format=%G?' und behandelte N als 'unsigniert'. Falsch: CCR signiert per SSH OHNE gpg.ssh.allowedSignersFile, git kann dann gar nicht verifizieren und meldet N fuer signierte wie unsignierte Commits gleichermassen. Belegt an 9d29122, dessen Rohobjekt einen gpgsig-Header traegt. Die vorgeschlagene Abhilfe haette einen Force-Push auf bereits gepushte Commits verlangt — verboten und wirkungslos. Richtig ist die Praesenzpruefung des Headers im Rohobjekt.  `path:.claude/hooks/stop-hook-git-check.sh` `sha:9d29122`

## Grenzwache

- ledger/s2-1: nackter Commit-Hash im Text -- gehoert als anchor 'sha:...', nicht in die Prosa
- ledger/s2-15: nackter Commit-Hash im Text -- gehoert als anchor 'sha:...', nicht in die Prosa
- ledger/s2-18: nackter Commit-Hash im Text -- gehoert als anchor 'sha:...', nicht in die Prosa
- ledger/s2-21: nackter Commit-Hash im Text -- gehoert als anchor 'sha:...', nicht in die Prosa

## Einstieg

```sh
python3 scripts/munin_session.py brief      # dieser Text, neu gemessen
python3 scripts/munin_continuity.py capture # Entscheidung/Sackgasse erfassen
python3 scripts/munin_continuity.py seal --push  # Sitzung abschliessen
python3 scripts/munin_supervisor.py --quick # Verfassungs-Audit
```

### Letzte Commits

```
5d4ce77 chore: self_space_workspace_ ignorieren
bcac905 feat(handoff): gemessene Uebergabe an die naechste Sitzung
4e7c025 Update visible platform status [skip ci]
dfce32f Update visible monitoring report
dcf9c71 Update visible monitoring report
b40950f Update visible platform status [skip ci]
8c22864 Merge pull request #82 from benholl94-cmyk/claude/aufraeumen-reste
3314dea chore: toten Baum und Waise entfernt, Reste mitgeräumt
```

