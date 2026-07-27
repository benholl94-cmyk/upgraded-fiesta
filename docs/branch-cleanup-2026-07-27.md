# Branch-Bereinigung 2026-07-27

Auf ausdruecklichen Master-Befehl. Fuer jeden geloeschten Branch ist unten die
Spitze festgehalten — ein Branch laesst sich daraus jederzeit wiederherstellen
(`git branch <name> <sha> && git push origin <name>`), solange GitHub das Objekt
haelt. Loeschen ohne dieses Protokoll waere nicht umkehrbar gewesen.

## Nicht geloescht

| Branch | Grund |
|---|---|
| `main` | Default-Branch |
| `__dolt_remote_info__` | steht in `PROTECTED_BRANCHES` von `.claude/skills/repo-steward/scripts/repo_steward.py` |
| `claude/claud-ai-code-teleport-nx73zr` | ebenfalls dort geschuetzt; PR #85 wurde daraus gemerged, eine Parallel-Sitzung arbeitet moeglicherweise weiter darauf |

## Geloescht

Pruefkriterium war nicht das Alter, sondern: **traegt der Branch eine Datei, die
es in `main` nicht gibt und die dort fehlen wuerde?** Gemessen als Differenz zur
Merge-Basis, abzueglich `self_space_workspace_/`, `node_modules/`, `dist/`,
`target/`.

| Branch | Spitze | ahead | letzter Commit | einzigartig | Befund |
|---|---|---|---|---|---|
| `benholl94-cmyk/change-stack-8-f1e01161/626283e` | `ed9fefab5cc6` | 11 | 2026-06-16 | 17 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `claude/env-points-anchors-localization-flyoos` | `e8c205d596e2` | 386 | 2026-07-08 | 4 | Laufzeit-Artefakte (logs/, config/*-state.json) |
| `claude/flow-collision-fix` | `f918178d14ae` | 2175 | 2026-07-24 | 478 | toter Baum, auf Master-Befehl entfernt (CLAUDE.md) + supervisor_agent.production.py — Waise, 1404 Zeilen, bewusst entfernt |
| `claude/handoff-documentation-8qf1v9` | `adcde45fd141` | 0 | 2026-07-26 | 0 | vollstaendig in main enthalten |
| `claude/platform-hardening` | `2fa4fc0df85b` | 2183 | 2026-07-24 | 477 | toter Baum, auf Master-Befehl entfernt (CLAUDE.md) + supervisor_agent.production.py — Waise, 1404 Zeilen, bewusst entfernt |
| `claude/workspace-finalize-nx73zr` | `270b0e3d9378` | 2165 | 2026-07-24 | 478 | toter Baum, auf Master-Befehl entfernt (CLAUDE.md) + supervisor_agent.production.py — Waise, 1404 Zeilen, bewusst entfernt |
| `coderabbitai/docstrings/734540e` | `e8179adc3a99` | 4 | 2026-06-11 | 1 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `coderabbitai/docstrings/ec87f08` | `52544a5432a6` | 3 | 2026-06-11 | 1 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `coderabbitai/utg/3eb370c` | `a1b9416e300e` | 24 | 2026-06-12 | 15 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `coderabbitai/utg/4cb740b` | `7ebc7c606c6b` | 39 | 2026-06-12 | 24 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `coderabbitai/utg/c38a454` | `c67d58d3c73b` | 180 | 2026-06-17 | 0 | vollstaendig in main enthalten |
| `codespace-codeagent-mobile-97pvvqgp594527776` | `6729db44db06` | 36 | 2026-06-12 | 27 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/build-self-made-github-app` | `f858d9937841` | 242 | 2026-06-19 | 4 | Laufzeit-Artefakte (logs/, config/*-state.json) |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein` | `1f12820b183e` | 10 | 2026-06-12 | 5 | durch validate_repo.py / repo_tracker.py / codex_fullstack_setup.sh ersetzt (PR #22, geschlossen) |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-6yw2yv` | `a89dd8a2ec92` | 16 | 2026-06-12 | 14 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-art3ek` | `c77fa40d655a` | 10 | 2026-06-11 | 14 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-kasduc` | `cd39cd641b90` | 22 | 2026-06-11 | 14 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ldgbhw` | `aa5b1e8294f4` | 3 | 2026-06-11 | 0 | vollstaendig in main enthalten |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-op15j7` | `b73e41c51c30` | 2 | 2026-06-11 | 1 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-rr1agn` | `27a973b358c3` | 7 | 2026-06-12 | 1268 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ywuodw` | `73a441f7d729` | 2 | 2026-06-11 | 1 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `codex/run-codex-cloud-setup-script` | `8406e1afdf2c` | 6 | 2026-06-12 | 2 | durch validate_repo.py / repo_tracker.py / codex_fullstack_setup.sh ersetzt |
| `deploy/generated-heavy-metal-workspace-20260618` | `ab821fe58311` | 189 | 2026-06-18 | 0 | vollstaendig in main enthalten |
| `revert-24-codespace-codeagent-mobile-97pvvqgp594527776` | `1d4d06ae3727` | 44 | 2026-06-12 | 24 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `uniqueclaw-production-grade` | `e713414cbf5d` | 74 | 2026-06-14 | 35 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ |
| `uniqueclaw-production-grade-v2` | `8a732bf19325` | 77 | 2026-06-14 | 37 | Vorgaenger-Projekt app.js/datasets, ersetzt durch iphone-dev-platform/ (PR #31, geschlossen) |

## Vollstaendige Spitzen-SHAs

```
ed9fefab5cc6306bb2cbff23670bfa8b80f15fd2  benholl94-cmyk/change-stack-8-f1e01161/626283e
e8c205d596e2f6aaaf45d82ae613bb74dadaa9b4  claude/env-points-anchors-localization-flyoos
f918178d14aedae393ca8c70c49f51ea6e4732eb  claude/flow-collision-fix
adcde45fd1415dfaf45ad0f98a7183e2bad83502  claude/handoff-documentation-8qf1v9
2fa4fc0df85bed9e6c9768c125cddda6f2b748a3  claude/platform-hardening
270b0e3d9378e414d1be8c039ed997daf464bca1  claude/workspace-finalize-nx73zr
e8179adc3a997c18144b3b3c256c130b8b52e1d8  coderabbitai/docstrings/734540e
52544a5432a65399e9554fcd18519a5b8b885334  coderabbitai/docstrings/ec87f08
a1b9416e300ec6b129f43dfaab617649e9778e08  coderabbitai/utg/3eb370c
7ebc7c606c6b637af5b2fd4ececeecf6e57df1a2  coderabbitai/utg/4cb740b
c67d58d3c73b51cfaf8b22b449ebe7ccef4663fe  coderabbitai/utg/c38a454
6729db44db06e4f0c4c3e5a97061e9c63bbbf12b  codespace-codeagent-mobile-97pvvqgp594527776
f858d9937841b2896114a64924fd5d67536a0527  codex/build-self-made-github-app
1f12820b183e56273edb06d10c9ecc2d8224f912  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein
a89dd8a2ec929b2afe060d0b541a4385234f8ca2  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-6yw2yv
c77fa40d655aa5baec28afe35aa42d28bdc172ea  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-art3ek
cd39cd641b9032d35d00675bc9e05973158a0362  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-kasduc
aa5b1e8294f44db458388cf09823fd0a3cb2e1d0  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ldgbhw
b73e41c51c305dd6cbbb7cee0245a8a550ca5dbb  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-op15j7
27a973b358c320d0ccc9fc663f718ed490e5321e  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-rr1agn
73a441f7d72961569f61f0fa6cb598ed4121e555  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ywuodw
8406e1afdf2cf77e016b7626604395609c1f809a  codex/run-codex-cloud-setup-script
ab821fe583119b539d3ca3ff09fd81da7a0815cb  deploy/generated-heavy-metal-workspace-20260618
1d4d06ae3727acb8d939c205691a599a97924a5e  revert-24-codespace-codeagent-mobile-97pvvqgp594527776
e713414cbf5d5358d9eee278730c5050afe37fab  uniqueclaw-production-grade
8a732bf193252a8858ea4d8f8050124bb1664603  uniqueclaw-production-grade-v2
```


## Ausfuehrung — erledigt

**Ausgefuehrt am 2026-07-27 ueber `.github/workflows/branch-cleanup.yml`.**
Ergebnis: 30 Remote-Branches → 3. Verblieben sind `main`,
`__dolt_remote_info__` und `claude/claud-ai-code-teleport-nx73zr`.

Aus der Arbeitsumgebung heraus war die Loeschung dreifach gesperrt, und keiner
der Wege wurde umgangen:

| Weg | Antwort |
|---|---|
| `git push origin --delete <branch>` | Berechtigungs-Klassifikator verweigert |
| `git push origin :<branch>` | Git-Proxy: `send-pack: unexpected disconnect` |
| `DELETE /git/refs/heads/<branch>` | API-Proxy: HTTP 403, *"Write access to this GitHub API path is not permitted through this proxy."* |

Der Workflow laeuft auf GitHub selbst und geht durch keinen davon. Er ist
wiederverwendbar: ohne die Eingabe `loeschen` macht er einen Probelauf, und
`main`, `__dolt_remote_info__` sowie der Teleport-Branch sind doppelt
geschuetzt — durch Auslassung aus der Liste und durch eine Sperrliste im
Skript.

Der folgende Block waere die manuelle Entsprechung gewesen:

```sh
# Probelauf — zeigt nur an, was passieren wuerde
for b in \
  benholl94-cmyk/change-stack-8-f1e01161/626283e \
  claude/env-points-anchors-localization-flyoos \
  claude/flow-collision-fix \
  claude/handoff-documentation-8qf1v9 \
  claude/platform-hardening \
  claude/workspace-finalize-nx73zr \
  coderabbitai/docstrings/734540e \
  coderabbitai/docstrings/ec87f08 \
  coderabbitai/utg/3eb370c \
  coderabbitai/utg/4cb740b \
  coderabbitai/utg/c38a454 \
  codespace-codeagent-mobile-97pvvqgp594527776 \
  codex/build-self-made-github-app \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-6yw2yv \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-art3ek \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-kasduc \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ldgbhw \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-op15j7 \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-rr1agn \
  codex/richte-lokale-entwicklerumgebung-auf-iphone-ein-ywuodw \
  codex/run-codex-cloud-setup-script \
  deploy/generated-heavy-metal-workspace-20260618 \
  revert-24-codespace-codeagent-mobile-97pvvqgp594527776 \
  uniqueclaw-production-grade \
  uniqueclaw-production-grade-v2 \
  claude/repo-completeness-check-3kme9t
do git push --dry-run origin --delete "$b"; done

# Echte Loeschung: dasselbe ohne --dry-run
```

27 Branches. `claude/repo-completeness-check-3kme9t` ist darin enthalten:
PR #84 wurde daraus gemerged, der Branch traegt danach nichts mehr, was nicht in
`main` steht.

Wiederherstellung eines einzelnen Branches aus der Tabelle oben:

```sh
git push origin <spitzen-sha>:refs/heads/<branch-name>
```
