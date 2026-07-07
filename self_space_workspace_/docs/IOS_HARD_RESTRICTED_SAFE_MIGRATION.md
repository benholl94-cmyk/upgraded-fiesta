# iOS Hard-Restricted Safe Migration

Generated: `2026-07-06T23:30:29.694973Z`

## Result

This build treats Apple kernel/iOS sets as hard platform boundaries. It does not modify kernel state, bypass the sandbox, depend on jailbreak behavior, install hidden daemons, request private entitlements, or write outside app/container-approved locations.

## Classification

| Requirement | Classification | Mechanisms |
| --- | --- | --- |
| autonomous periodic repo validation outside the foreground app | `allowed` | `app_extensions, bg_app_refresh, bg_processing, shortcuts_app_intents` |
| out-of-app task trigger from Shortcuts or share sheet | `allowed` | `app_extensions, shortcuts_app_intents` |
| local gateway pairing between iPhone and operator service | `allowed` | `local_lan_gateway` |
| safe migration of Apple kernel iOS sets without modifying kernel or bypassing sandbox | `allowed_with_boundary` | `policy_boundary, local_lan_gateway, app_groups` |
| persistent audit trail and issue classification | `allowed` | `manual_operator_task` |

## Safe Out-of-App Mechanisms

| Mechanism | Use | Limit |
| --- | --- | --- |
| `bg_app_refresh` | short refresh and state update jobs that iOS may schedule opportunistically | system scheduled; short runtime; not guaranteed at exact time |
| `bg_processing` | longer maintenance/data-processing jobs while the device is idle | interruptible; requires processing background mode; not a permanent daemon |
| `continued_processing` | user-started work that can continue after the app is backgrounded | must start from foreground/user action; progress/cancel behavior required |
| `background_urlsession` | system-managed uploads/downloads that continue when the app is suspended | network transfer only; completion delivered by system |
| `app_extensions` | Share Sheet, File Provider, Widget, Intent/App Intent, Notification Service, Spotlight indexing | separate extension bundles with constrained APIs and lifecycle |
| `app_groups` | safe data exchange between app and its extensions | only within same developer team/app group entitlement |
| `shortcuts_app_intents` | user-visible automation entry points outside the app UI | user-configured or user-approved automation; no hidden daemon behavior |
| `local_lan_gateway` | iPhone controls a reachable local service with explicit owner token | LAN/local only unless separately deployed behind proper auth/TLS |

## Execution

```sh
python3 local_usr/sys/bin/ios_restricted_migration.py init
python3 local_usr/sys/bin/ios_restricted_migration.py validate
python3 local_usr/sys/bin/ios_restricted_migration.py plan
```
