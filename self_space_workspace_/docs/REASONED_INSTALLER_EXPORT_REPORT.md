# Reasoned Live-DateTime Installer Export Report

Generated UTC: `2026-07-06T23:30:30.203659Z`

## Result

Gefahrenstufe ist ein Steuerungssignal, kein automatischer Ablehnungsgrund. Blockiert wird nur ein konkret unzulässiger Mechanismus oder Zweck. Hohe Gefahr wird mit Controls, Audit, Operator-Gate und reproduzierbarem Export behandelt.

## Risk Decision

- Decision: `allowed_with_controls`
- Risk level: `high`
- Reason: Risk level controls execution requirements; it is not an automatic refusal.
- Controls: `branch/permission check, commit scope manifest, fail closed, no secret artifacts, redacted logs, rollback note, rotation metadata, secret references only`

## Exports

- `/workspace/exports/reasoned_system_payload_20260706T233030Z.tar.gz` sha256 `abc271416aeedc4f96c49417c7cd5429480a03adb909aa7615f14d9636aa438e`
- `/workspace/exports/reasoned_system_payload_20260706T233030Z.zip` sha256 `c09becb073f1f9cc8eb96168d4884c65a17b650c7b3cb7131609db6242be4c2c`

## Install

```sh
python3 install_reasoned_system.py --source reasoned_system_payload --target .
```
