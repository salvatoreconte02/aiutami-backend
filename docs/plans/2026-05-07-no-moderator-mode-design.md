# No-Moderator Mode — Design Document

**Data:** 2026-05-07
**Tipo:** Design (preliminare a implementation plan)
**Scope:** Backend AIutami — modalità di sessione "senza moderatore AI"
**Motivazione:** Abilitare il braccio di controllo del design sperimentale
within-subject della tesi: ogni gruppo fa due task (NASA Moon Survival e
Lost at Sea), uno con moderatore AI ON e uno con moderatore AI OFF, in
ordine controbilanciato. Le altre condizioni (audio, turn-taking, intro,
ASR, raccolta dati) devono rimanere identiche tra i due bracci, per
garantire che il fattore experimental sia esclusivamente la presenza/
assenza degli interventi del moderatore.

---

## 1. Obiettivi

- Aggiungere una **modalità di sessione "no-moderator"** attivabile dall'host
  alla creazione, ortogonale al task plugin scelto (NASA, LAS, generic, MM).
- Garantire che in modalità OFF: **niente LLM moderation calls**, **niente
  TTS del moderatore** durante la discussione e la conclusion.
- Mantenere identico al mod ON: turn-taking, audio WebRTC, ASR, fase
  INDIVIDUAL_RANKING, submission del ranking di gruppo, generazione del
  report PDF finale, **e l'intro del moderatore** (testo statico delle 6
  ground rules — base comune fra le due condizioni sperimentali).
- Mantenere il moderation service interno **agnostico**: la disabilitazione
  vive nel coordinator (`apps/turns/ws_consumer.py`), non nel service
  (`apps/moderation/`).

## 2. Non-obiettivi (out of scope)

- **Cambio del flag a runtime**: la modalità è scelta alla creazione e
  immutabile fino a CLOSED. Niente endpoint `PATCH`, niente WS event
  dedicato, niente gestione di "switch a metà strada".
- **Recap testuale in mod OFF**: nessun summary alternativo nella pagina
  di conclusione. La sessione "scivola" silenziosamente in CONCLUSION.
- **Modifica al moderation service** (`apps/moderation/*`): tutti i guard
  vivono nel coordinator. Il service resta puro.
- **Pre-flight audio test** dei partecipanti: feature separata, già
  discussa e per ora non implementata.
- **Variabile env globale per disabilitare il moderatore**: il design
  sperimentale richiede per-sessione, non globale.

## 3. Decisioni di design (riferimento)

| # | Decisione | Scelta | Razionale |
|---|---|---|---|
| 1 | Configurazione | Flag `moderator_enabled: bool` su `Session`, default `True` | Backward-compat totale, ortogonale al task plugin, scrittura banale |
| 2 | Chi può scegliere | Solo l'host alla creazione (form sessione) | Coerente con flusso attuale, niente API admin separata |
| 3 | Mutabilità | Immutabile dopo `POST /api/sessions/` | Evita confounder sperimentale, evita complessità WS |
| 4 | Intro in mod OFF | **Mantenuta** (testo statico + TTS) | Le 6 ground rules sono base comune fra le 2 condizioni → dato comparabile |
| 5 | Conclusion in mod OFF | **Skip totale** (no LLM, no TTS, transizione silenziosa) | Pulizia sperimentale: zero LLM call dopo l'intro |
| 6 | UI mod OFF | Avatar moderatore visibile ma "spento" (grigio, no pulse) + badge "Sessione senza moderatore" | Continuità visiva fra le 2 sessioni del gruppo + chiarezza testuale |
| 7 | Architettura guard | 3 guard nel coordinator (`ws_consumer.py`), 0 nel service (`moderation/`) | Separazione di responsabilità: il moderator non sa che esiste mod OFF |
| 8 | Report PDF in mod OFF | Generato regolarmente; sezione "Interventi moderatore" mostra "0 interventi" | Stessa pipeline post-sessione → dato comparabile |

## 4. Architettura generale

### 4.1. Nuovo campo su `Session`

`apps/sessions/models.py`:

```python
moderator_enabled = models.BooleanField(
    default=True,
    help_text="Se False, la sessione gira in modalità 'no moderator': "
              "intro pronunciata regolarmente, ma niente LLM moderation "
              "calls né interventi vocali del moderatore durante la "
              "discussione e la conclusion. Usato per il braccio di "
              "controllo del design sperimentale within-subject."
)
```

### 4.2. Esposizione API

- **`POST /api/sessions/`**: `SessionCreateSerializer` accetta
  `moderator_enabled` come campo opzionale write (default `True`).
- **`GET /api/sessions/{id}/`**: `SessionDetailSerializer` espone
  `moderator_enabled` come campo read.
- **WS `STATE_CHANGED`**: il payload usa già
  `SessionDetailSerializer.data`, quindi il flag arriva "gratis" ad ogni
  transizione di stato. Niente WS event nuovo.

### 4.3. Migration

Aggiunta del campo con `default=True` → tutte le sessioni esistenti
diventano implicitamente mod-ON. Coerente con backward-compat.

## 5. Comportamento per fase di sessione

Tabella esaustiva del comportamento del flag in ogni fase del ciclo di
vita di una sessione:

| Fase | Mod ON (oggi) | Mod OFF |
|---|---|---|
| `LOBBY` | Identico | Identico (flag invisibile in questa fase) |
| `INDIVIDUAL_RANKING` (NASA/LAS) | Audio WebRTC OFF, no moderator | Identico (la fase è già "muta" di base) |
| Transizione `LOBBY → ACTIVE` (o `IR → ACTIVE`) | `set_intro_pending` + `mark_session_started` + `TurnManager.set_introducing` | Identico |
| Esecuzione intro | `_execute_intro_message`: testo statico via TTS | Identico (intro è base comune) |
| Fine intro | TurnManager torna IDLE, primo turno disponibile | Identico |
| Fine turno umano (`turns.end_speak`) | `_handle_end_speak` → `_run_moderation_orchestrator` (LLM) → eventuale TTS | **Skip moderation pipeline**: turno chiuso, sessione torna IDLE direttamente |
| Trigger temporale NO_PUSH | LLM decide intervento → eventuale TTS | **Skip**: niente LLM, niente TTS |
| Trigger 25 min ("5 min rimasti") | Notifica WS al frontend + eventuale intervento moderatore | Notifica WS sì, intervento TTS no |
| Trigger 30 min scaduto | `_execute_forced_conclusion` → LLM recap + TTS | **Transizione diretta a `CONCLUSION`** senza recap |
| Tutti pronti alla conclusione | `_execute_forced_conclusion` → idem sopra | **Transizione diretta a `CONCLUSION`** senza recap |
| `CONCLUSION` (host conferma ranking) | Identico | Identico (submission del task) |
| Transizione `CONCLUSION → CLOSED` | Generazione report PDF (LLM analyst) | Identico (analisi post-sessione) |

### 5.1. Punti chiave

- **Intro audio sempre presente**: testo statico via TTS, `apps.tts.service`
  non è LLM. Coerente in entrambe le modalità.
- **Side-effect ACTIVE-specific invariati**: `TurnManager.set_introducing`
  + `set_intro_pending` + `mark_session_started` partono in entrambi i
  casi al `Session.start()`. Sono infrastruttura di turn-taking + timer
  di sessione, non "voce" del moderatore.
- **TRIGGER_LOOP rimane attivo in mod OFF**: continua a girare ogni 5s,
  controlla i timer (NO_PUSH, 25 min, 30 min), gestisce le transizioni
  di stato. I guard saltano solo le invocazioni del moderator service.
- **DiscussionEvent log**: eventi `HUMAN_TURN`, `SYSTEM` registrati come
  oggi. Eventi `AI_INTERVENTION` semplicemente assenti in mod OFF — la
  differenza misurabile principale per la valutazione empirica.

## 6. Punti del codice da modificare

### 6.1. `apps/sessions/models.py`
Aggiungere il campo `moderator_enabled` (vedi §4.1).

### 6.2. `apps/sessions/serializers.py`
- `SessionCreateSerializer`: campo write opzionale (default `True`).
- `SessionDetailSerializer`: campo read.

### 6.3. `apps/sessions/migrations/00XX_*.py`
Migration auto-generata per l'aggiunta del campo. Backward-compatible.

### 6.4. `apps/turns/ws_consumer.py` — i 3 guard

Tutti i guard sono pattern `if not session.moderator_enabled: skip` o
omissione mirata di una chiamata. Posizioni esatte:

#### (a) `_execute_intro_message()` — riga ~1357
**Nessun guard.** L'intro va in entrambe le modalità.

#### (b) `_handle_end_speak()` — riga ~303-559
Aggiungere guard subito dopo lo step 1 (chiusura turno umano via
`TurnManager.end_speak`) e prima dello step 3 (`_set_moderation_in_progress(True)`,
riga ~364):

```python
# Mod OFF: skip totale della pipeline di moderazione.
# Il turno umano è già chiuso, la sessione torna IDLE direttamente,
# il prossimo speaker può prenotarsi.
session_obj = await self._get_session_obj(self.session_id)
if not session_obj.moderator_enabled:
    return
```

Saltati: `_set_moderation_in_progress`, `_run_moderation_orchestrator`
(LLM), tutti i `static_messages_to_speak`, l'eventuale TTS dell'intervento
(riga ~451-522), il blocco `should_transition_to_conclusion` (riga
~524-542) — perché in mod OFF la conclusion arriva solo dal trigger_loop
o da "tutti pronti".

#### (c) `_trigger_loop()` — riga ~1085-1200

Tre punti dentro il loop:

- **Static messages dell'orchestrator (riga ~1164-1168)**: in mod OFF
  saltati interamente. Sono contenuto generato dal moderator service.
- **Transizione a CONCLUSION (riga ~1173-1189)**: **mantenuta** in
  entrambe le modalità (state change + WS broadcast).
- **`_execute_forced_conclusion()` (riga ~1191)**: **saltata in mod OFF**.

```python
if trig_result.should_transition_to_conclusion and not message_was_queued:
    await self._set_conclusion_reason("timer_expired")
    transitioned = await self._transition_session_to_conclusion()
    if transitioned:
        # ... broadcast STATE_CHANGED ...
        if session_obj.moderator_enabled:
            await self._execute_forced_conclusion()
```

Per evitare query DB ripetute dentro il loop, caricare `session_obj` una
volta per tick (subito dopo `_get_session_state`) e riutilizzarlo.

#### (d) `_flush_pending_tts_messages()` — riga ~1453-1485
Stessa logica del punto (c). Chiama `_execute_forced_conclusion()` alla
riga ~1485 solo se `moderator_enabled`.

In mod OFF il loop arriva qui ma `pending` sarà vuoto (nessun messaggio
accodato dall'orchestrator) → no-op naturale; il guard è solo difesa in
profondità.

### 6.5. `apps/moderation/*`
**Nessuna modifica.** Il moderator service resta puro. Tutti i guard
vivono nel coordinator.

### 6.6. `apps/sessions/views.py` (`SessionStartView`)
**Nessuna modifica.** I side-effect ACTIVE-specific (`TurnManager.set_introducing`
+ `set_intro_pending` + `mark_session_started`) si attivano in entrambe
le modalità — l'intro deve partire e i timer devono cominciare a contare.

### 6.7. `apps/reports/*`
**Nessuna modifica funzionale.** Il report PDF è già robusto al caso
"interventions_log vuoto" — in mod OFF la sezione "Interventi del
moderatore" mostrerà naturalmente "0 interventi" o sarà omessa
condizionalmente. Verificare nel plan.

## 7. UI / API surface

### 7.1. Backend (questo design)
- `POST /api/sessions/` accetta `moderator_enabled: bool` (default True).
- `GET /api/sessions/{id}/` restituisce il campo.
- Eventi WS `STATE_CHANGED` includono il campo (via `SessionDetailSerializer`).

### 7.2. Frontend (out of scope di questo design — brief al Claude del frontend)

Questo design **non implementa il frontend**, ma esplicita i requisiti
visivi necessari per la pulizia sperimentale:

- **Pagina creazione sessione**: toggle switch "Moderazione AI attiva",
  default ON. POST con `moderator_enabled` nel body.
- **Durante la sessione (mod OFF)**:
  - Avatar moderatore visibile in posizione centrale, ma reso
    visivamente "spento" — grigio chiaro, senza animazione `aiPulse`,
    senza bordo verde quando "parlerebbe".
  - Badge in header tipo "Sessione senza moderatore" con icona, visibile
    in tutta la sessione.
  - Durante l'intro (TTS attivo) l'avatar si "accende" e pulsa come
    oggi; dopo `turns.ai_ended` dell'intro, torna grigio per il resto
    della sessione.
- **Pagina di conclusion**: nessuna voce di recap, solo `STATE_CHANGED →
  CONCLUSION` via WS, frontend mostra la pagina di conferma del ranking
  di gruppo come oggi.

### 7.3. Visibilità del flag al frontend

Il flag è immutabile dopo creazione, quindi non serve push WS dedicato.
Il frontend lo legge:
1. Al `GET /api/sessions/{id}/` quando il partecipante entra nella
   sessione (tipico flow di mount della SessionPage).
2. In ogni `STATE_CHANGED` (payload include il flag tramite
   `SessionDetailSerializer`).

Niente race condition: il valore è scritto una volta sola alla
creazione e dopo è solo letto. Niente endpoint `PATCH`, niente WS event
dedicato.

## 8. Testing strategy

### 8.1. Unit test sul model + serializer
**`apps/sessions/tests.py`** (estensione):
- `test_session_default_moderator_enabled_true`: nuova sessione senza
  flag → default True.
- `test_session_create_with_moderator_disabled`: POST con `false` →
  persistenza corretta.
- `test_session_detail_includes_moderator_enabled`: GET ritorna il
  campo.
- `test_session_detail_payload_in_state_changed`: il broadcast
  `STATE_CHANGED` include il campo.

### 8.2. Unit test sui guard
**`apps/turns/tests_moderator_disabled.py`** (nuovo):
- `test_end_speak_skips_moderation_when_moderator_disabled`: mock di
  `_run_moderation_orchestrator`, assertion **non chiamato**.
- `test_trigger_loop_transitions_to_conclusion_silently_when_disabled`:
  mock di `_execute_forced_conclusion`, assertion non chiamato; verifica
  transizione + broadcast.
- `test_trigger_loop_skips_static_messages_when_disabled`: mock di
  `_execute_static_messages`, assertion non chiamato.
- `test_intro_runs_in_both_modes`: mod OFF, mock di TTSService,
  assertion `synthesize_stream` **chiamato**.
- `test_flush_pending_skips_forced_conclusion_when_disabled`: stato
  IDLE, messaggio in coda con `trigger_conclusion=True`, mod OFF →
  forced_conclusion non chiamato, transizione di stato avviene.

### 8.3. Regression test per mod ON
**Almeno 2 test** che confermano comportamento attuale invariato:
- `test_end_speak_runs_moderation_when_moderator_enabled`.
- `test_trigger_loop_executes_forced_conclusion_when_enabled`.

### 8.4. Smoke test
Run completo della suite (~430 test attesi, +~10 dei nuovi):
```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests apps.sessions.tests_discussion_event \
  apps.moderation.tests apps.moderation.tests_integration \
  apps.moderation.tests_intro \
  apps.turns.tests_services apps.turns.tests_disconnect \
  apps.turns.tests_moderator_disabled \
  apps.reports.tests \
  apps.tasks.tests.test_registry \
  apps.tasks.tests.test_murder_mystery_registration \
  apps.tasks.tests.test_generic apps.tasks.tests.test_nasa_moon \
  apps.tasks.tests.test_lost_at_sea apps.tasks.tests.test_base \
  apps.tasks.tests.test_individual_ranking_phase \
  apps.tasks.tests.test_individual_ranking_finalize \
  apps.tasks.nasa_moon.tests.test_individual_ranking \
  apps.tasks.lost_at_sea.tests.test_individual_ranking \
  apps.webrtc.tests.test_audio_hub apps.webrtc.tests.test_consumer
```

I 426 test esistenti restano verdi (la feature è strettamente additiva).

### 8.5. Test live in produzione (manuale, post-deploy)
1. Crea sessione NASA mod ON → flow normale.
2. Crea sessione NASA mod OFF → intro audio, poi nessuna voce del
   moderatore per tutto il resto, sessione finisce silenziosamente al
   timer o al "tutti pronti".
3. UI: badge "Sessione senza moderatore" visibile, avatar moderatore
   grigio post-intro, niente pulse durante turni umani.

## 9. Deploy e rollout

Sequenza standard backend → VPS (vedi `CLAUDE.md`):

1. Migration applicata al DB di prod (1 nuova: campo aggiunto, default
   True per backward-compat).
2. Deploy backend.
3. Deploy frontend (toggle in pagina creazione + UI mod OFF).
4. Sessioni esistenti al deploy: nessun impatto (default True). Le
   nuove sessioni create dopo il deploy possono usare il flag.

Migration backward compat: il campo ha `default=True`, sessioni
precedenti non subiscono effetti.

## 10. Rischi e mitigazioni

| Rischio | Probabilità | Mitigazione |
|---|---|---|
| Frontend non aggiornato → host non vede il toggle, tutte le sessioni mod ON | Alta | Coordinare deploy backend ↔ frontend. Backend è deploy-safe da solo perché default True. |
| Guard mancato in qualche callsite poco evidente del moderation flow | Media | I 3 guard sono nel coordinator (`ws_consumer.py`), copertura completa. Test unit specifici. Se emerge un punto sfuggito, è un fix mirato. |
| Race condition lettura/scrittura flag durante sessione attiva | Bassa | Flag immutabile dopo creazione → impossibile per costruzione. |
| Timer 30 min in mod OFF non scatena conclusion | Bassa | La transizione di stato resta abilitata, solo `_execute_forced_conclusion` è guardian. Test specifico. |
| Report PDF rotto in mod OFF (sezione interventi vuota) | Bassa | Il code path è già robusto a `interventions_log` vuoto (testato in altri scenari). Verifica nel plan. |

## 11. File e luoghi di intervento

| File | Tipo | Cambiamento |
|---|---|---|
| `apps/sessions/models.py` | Mod | `+moderator_enabled` field |
| `apps/sessions/migrations/00XX_*.py` | New | Migration per il campo |
| `apps/sessions/serializers.py` | Mod | `SessionCreateSerializer` write field, `SessionDetailSerializer` read field |
| `apps/sessions/tests.py` | Mod | +4 test su model + serializer |
| `apps/turns/ws_consumer.py` | Mod | 3 guard nei punti specificati in §6.4 |
| `apps/turns/tests_moderator_disabled.py` | New | +5 test sui guard, +2 regression mod ON |
| `apps/moderation/*` | Invariati | Nessuna modifica funzionale |
| `apps/reports/*` | Invariati | Verifica robustezza a interventions_log vuoto (test esistente o nuovo nel plan) |

## 12. Open questions (non bloccanti per la spec)

- **Categoria di static_messages_to_speak da skippare in `_trigger_loop`**:
  oggi tutti i `static_messages_to_speak` sono generati dal moderator
  service e in mod OFF possono essere saltati interamente. Se in futuro
  servisse distinguere tra "voce del moderatore" e "system event puro"
  (es. notifica `TIMER_25` separata dal contenuto vocale), introdurre un
  campo `category` nei messaggi. Per ora non necessario.
- **Permessi di lettura flag**: chiunque (membro o non) può leggere
  `moderator_enabled` via GET? Oggi il GET è ristretto ai membri della
  sessione, quindi automaticamente coperto. Se un giorno servisse
  esposizione pubblica (es. lobby pre-join), valutare permission
  separato — non necessario ora.
- **Future estensioni**: se in futuro si volessero più "modalità" (es.
  "moderator-light", "moderator-silent-but-text", ecc.), il flag
  boolean diventa restrittivo. Si potrebbe migrare a un enum
  `moderator_mode: TextChoices`. Out of scope ora; il refactor è
  banale (boolean → choices).
