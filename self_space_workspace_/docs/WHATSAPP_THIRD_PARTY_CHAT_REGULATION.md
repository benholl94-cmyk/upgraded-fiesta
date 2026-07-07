# WhatsApp Third-Party Chats: Operational Boundary

Checked date: 2026-07-06

## Official Position

WhatsApp third-party chats are a Digital Markets Act interoperability feature
for eligible users in the European region. Meta describes it as optional for
users, available on Android and iOS, and limited to third-party messaging
services that choose to become interoperable and satisfy WhatsApp technical
and security requirements.

Operationally relevant requirements from the official Meta/WhatsApp material:

- Users must opt in; the feature can be turned off.
- Supported third-party services must provide the same level of end-to-end
  encryption as WhatsApp, or a compatible protocol with equivalent guarantees.
- Third-party providers must sign an agreement/reference offer path with Meta.
- Initial scope is user messaging with text and attachments; group support
  depends on partner readiness.
- WhatsApp states that it cannot make the same privacy promise for behavior
  inside a third-party client endpoint.
- The DMA requires interoperability upon request, but does not make WhatsApp a
  generic local automation or private-protocol API.

## System Decision

`local_usr/sys/bin/system_app_chat.py` is deliberately not a WhatsApp client.
It does not connect to Meta servers, does not implement WhatsApp private
protocols, and does not claim third-party provider status.

The implemented scope is lawful internal infrastructure:

- local app-to-app chat
- system status messages
- progress and optimization events
- audit and operational messages
- optional HTTP access on `127.0.0.1`

External WhatsApp interoperability may only be added later through an official
provider route with documented eligibility, security review, production keys,
and operator approval.

## References

- Meta newsroom: `https://about.fb.com/news/2025/11/messaging-interoperability-whatsapp-enables-third-party-chats-for-users-in-europe/`
- Meta engineering: `https://engineering.fb.com/2024/03/06/security/whatsapp-messenger-messaging-interoperability-eu/`
- WhatsApp Help Center: `https://faq.whatsapp.com/916543719558426`
- EU DMA Article 7: `https://digitalmarketsact.com/7/`
