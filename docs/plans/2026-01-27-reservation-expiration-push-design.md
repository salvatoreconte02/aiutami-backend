# Design: Push automatico RESERVATION_EXPIRED

**Data:** 2026-01-27
**Stato:** Da implementare

## Problema

Con l'architettura attuale, l'evento `RESERVATION_EXPIRED` viene generato solo in modo "lazy" quando un client esegue un'azione (richiede stato, prova a parlare, ecc.). Il frontend non riceve automaticamente la notifica allo scadere degli 8 secondi della finestra di prenotazione.

## Soluzione

Implementare un push automatico dal server usando un task asyncio che:
1. Si avvia quando viene emesso `RESERVATION_WINDOW_STARTED`
2. Aspetta 8 secondi
3. Verifica se la reservation è ancora attiva
4. Se sì, invia `RESERVATION_EXPIRED` via WebSocket

## Architettura

```
TurnsConsumer (ws_consumer.py)
    │
    ├── _handle_end_speak()
    │       │
    │       └── Se reservation attiva → crea asyncio task
    │
    └── _schedule_reservation_expiration()  [NUOVO]
            │
            ├── await asyncio.sleep(8)
            ├── TurnManager.expire_reservation_if_pending()  [NUOVO]
            └── channel_layer.group_send() → RESERVATION_EXPIRED
```

## Flusso temporale

```
T=0s   Utente A termina di parlare (end_speak)
       ├── Broadcast: RESERVATION_WINDOW_STARTED {user_id: B, expires_at: T+8s}
       └── Avvia task: _schedule_reservation_expiration(session_id, user_B)

T=0-8s Possibili scenari:
       ├── Utente B chiama request_speak → reservation consumata
       └── Nessuna azione → task continua

T=8s   Task si sveglia:
       ├── Verifica: reservation ancora attiva in Redis?
       ├── Se SÌ → Broadcast: RESERVATION_EXPIRED {user_id: B}
       └── Se NO → Niente (già consumata)
```

## Modifiche

### 1. services.py - Nuovo metodo TurnManager

```python
@classmethod
def expire_reservation_if_pending(
    cls,
    session_id: str,
    expected_user_id: int
) -> Optional[TurnEvent]:
    """
    Chiamato dal timer asincrono. Expira la reservation SOLO se
    è ancora attiva per lo stesso utente.

    Restituisce l'evento RESERVATION_EXPIRED o None.
    """
    state = cls._load_state(session_id)

    # Reservation già consumata?
    if state.reservation_user_id != expected_user_id:
        return None

    # Expira la reservation
    state.reservation_user_id = None
    state.reservation_expires_at = None
    state.version += 1

    cls._save_state(session_id, state)

    return TurnEvent(
        type="RESERVATION_EXPIRED",
        payload={
            "user_id": expected_user_id,
            "expired_at": timezone.now().isoformat(),
        },
    )
```

### 2. ws_consumer.py - Nuovo metodo e modifica

```python
async def _schedule_reservation_expiration(
    self,
    session_id: str,
    user_id: int
):
    """
    Task asincrono che aspetta la scadenza della finestra
    e invia RESERVATION_EXPIRED se la reservation è ancora attiva.
    """
    await asyncio.sleep(PRIORITY_WINDOW_SECONDS)

    # Verifica e expira
    event = TurnManager.expire_reservation_if_pending(session_id, user_id)

    if event:
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "turns.event",
                "event_type": event.type,
                "payload": event.payload,
            },
        )
```

Chiamata in `_handle_end_speak()` dopo il broadcast:

```python
for event in events:
    if event.type == "RESERVATION_WINDOW_STARTED":
        asyncio.create_task(
            self._schedule_reservation_expiration(
                session_id=self.session_id,
                user_id=event.payload["user_id"],
            )
        )
```

## Edge case

| Scenario | Comportamento |
|----------|---------------|
| Utente usa la reservation entro 8s | `reservation_user_id` diventa `None`, task non fa nulla |
| Utente si disconnette durante la finestra | Task continua, invia `RESERVATION_EXPIRED` agli altri |
| Server si riavvia durante i 8s | Task perso, check lazy esistente gestisce alla prossima azione |

## Test da aggiungere

1. `test_reservation_expired_event_sent_after_timeout` - Verifica che l'evento venga inviato dopo 8 secondi
2. `test_reservation_used_no_expired_event` - Verifica che l'evento NON venga inviato se usata in tempo

## File coinvolti

- `apps/turns/services.py`
- `apps/turns/ws_consumer.py`
- `apps/turns/tests.py`
