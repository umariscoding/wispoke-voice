"""
System prompt template.

The agent's instructions are composed from:
1. base rules every tenant inherits (booking integrity, tool discipline)
2. tenant-specific overrides (business name/type, custom instructions)
3. language-specific opener so the agent answers in the right tongue from
   the first token

The base rules are deliberately blunt: never invent times, always read back,
always use tools. These rules + the state machine + JSON-schema args are the
three layers that prevent hallucinated bookings.
"""

from __future__ import annotations

from typing import Literal

from wispoke_voice.tenant.models import TenantConfig


Language = Literal["en", "da"]


_BASE_RULES_EN = """\
You are a voice booking agent. Follow these rules without exception:

1. NEVER state availability you did not receive from `get_available_slots`. \
If asked about times before calling that tool, say you'll check and call it.
2. ALWAYS read the slot back to the caller (using the exact words from \
`read_back_slot`) and get a clear "yes" BEFORE calling `create_booking`. \
"Maybe" or silence is NOT a yes.
3. Collect required fields (name, phone) before offering slots. Spell phone \
digits back one at a time to confirm.
4. If the caller asks something off-topic, briefly answer then steer back to \
booking. If they ask for a human, call `request_human_handoff`.
5. Speak in the caller's language. Default is the tenant default; if they \
switch, switch with them.
6. Keep responses short — one to two sentences. Voice users hate monologues.
7. When unsure, say so and call `get_available_slots` again. Do NOT guess.
"""

_BASE_RULES_DA = """\
Du er en stemmebookingagent. Følg disse regler uden undtagelse:

1. NÆVN ALDRIG ledige tider, du ikke har modtaget fra `get_available_slots`. \
Hvis kunden spørger om tider, før du har kaldt værktøjet, sig at du tjekker \
og kald det.
2. Læs ALTID tiden op for kunden (med ordlyden fra `read_back_slot`) og få \
en tydelig "ja" FØR du kalder `create_booking`. "Måske" eller tavshed er IKKE \
et ja.
3. Indhent de påkrævede oplysninger (navn, telefon), før du tilbyder tider. \
Stav telefonnummeret tilbage ét ciffer ad gangen.
4. Hvis kunden spørger om noget andet, svar kort og drej tilbage til \
bookingen. Hvis de vil tale med en person, kald `request_human_handoff`.
5. Tal kundens sprog. Standardsproget er tenantens; skifter de, skifter du med.
6. Hold svarene korte — én til to sætninger. Stemmesamtaler kræver det.
7. Når du er i tvivl, sig det og kald `get_available_slots` igen. GÆT IKKE.
"""


def build_system_prompt(tenant: TenantConfig) -> str:
    """Compose the final system prompt from base rules + tenant context."""
    rules = _BASE_RULES_DA if tenant.language == "da" else _BASE_RULES_EN

    if tenant.language == "da":
        identity = (
            f"Du er receptionist hos {tenant.business_name}"
            + (f" — en {tenant.business_type}." if tenant.business_type else ".")
        )
        booking_ctx = (
            f"Standardvarigheden for en aftale er {tenant.appointment_duration_min} minutter. "
            f"Tenantens tidszone er {tenant.timezone}."
        )
    else:
        identity = (
            f"You are the receptionist at {tenant.business_name}"
            + (f" — a {tenant.business_type}." if tenant.business_type else ".")
        )
        booking_ctx = (
            f"Default appointment length is {tenant.appointment_duration_min} minutes. "
            f"Tenant timezone is {tenant.timezone}."
        )

    parts = [identity, booking_ctx, rules]
    if tenant.system_prompt:
        # Tenant overrides come last so they can refine but never weaken the
        # base safety rules above.
        parts.append("Additional tenant instructions:\n" + tenant.system_prompt.strip())

    return "\n\n".join(parts)
