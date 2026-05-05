# Individual Ranking Collection — Design Document

**Data:** 2026-05-06
**Tipo:** Design (preliminare a implementation plan)
**Scope:** Backend AIutami — task NASA Moon Survival + Lost at Sea
**Motivazione:** Abilitare il calcolo di `synergy_gain` e `assembly_bonus` nel
report empirico (metriche standard Hall 1962, Hall & Watson 1970, Hamada 2020),
oggi presenti come placeholder `None` in
`apps/tasks/{nasa_moon,lost_at_sea}/report.py`.

---

## 1. Obiettivi

- Raccogliere il **ranking individuale pre-discussione** dei 15 oggetti per
  ogni partecipante delle sessioni NASA Moon Survival e Lost at Sea.
- Persistere i ranking individuali su PostgreSQL (per analisi a freddo) e
  usarli per popolare le metriche empiriche `synergy_gain`, `assembly_bonus`,
  `mean_individual_error` nel report di sessione.
- Mantenere il backend **agnostico rispetto al task specifico**: il core di
  `apps/sessions` non importa mai da `apps/tasks/<specific>`. Le decisioni
  task-specifiche passano dal `TaskDefinition` plugin.
- Lasciare invariato il comportamento di `generic` e `murder_mystery`
  (nessuna fase pre-discussione).

## 2. Non-obiettivi (out of scope)

- Visualizzazione dei ranking individuali nel PDF (per partecipante o
  anonimizzata) — solo aggregato.
- Accesso del moderatore AI ai ranking individuali — esplicitamente cieco.
- Configurazione admin/runtime della durata fase (hardcoded 8 min).
- Recovery di task asincroni in caso di crash Daphne (coperto in modo
  pragmatico da lazy check + setTimeout frontend).
- Late join durante la fase individuale (vincolo già presente: i join sono
  consentiti solo in LOBBY).
- Cancellazione/retry del submit esplicito (one-way fino a fine fase).
- Endpoint di export CSV dei ranking individuali (estraibili via Django shell).

## 3. Decisioni di design (riferimento)

| # | Decisione | Scelta | Razionale |
|---|---|---|---|
| 1 | Dove collocare la fase | Nuovo stato esplicito `INDIVIDUAL_RANKING` deciso dal task plugin | Esplicito nello stato, coerente col task-pluggable, contratti audio/moderator non ambigui |
| 2 | Modello dati | Due modelli paralleli `NasaIndividualRanking` + `LostAtSeaIndividualRanking` | Coerenza col pattern attuale (NasaRanking/LostAtSeaRanking sono già paralleli), validazione per-task locale |
| 3 | Quando finisce la fase | Auto-transizione su (a) tutti submit o (b) timer 8 min — niente conferma host | Robusto, allineato al design empirico Hall & Watson |
| 4 | Submit-once vs autosave | **Autosave** (PUT continuo a ogni drag) | Costo trascurabile a 3 utenti (~0.1 PUT/s); zero perdite se utente non submitta |
| 4.bis | Ordine iniziale | Fisso = `NASA_ITEMS` / `LAS_ITEMS` da config | Coerente con frontend esistente, no shuffle |
| 5 | Trigger della finalizzazione al timer | Lazy check sui PUT/POST + frontend setTimeout 8min → `POST /finalize-if-expired/` | Coerente con il pattern WS-push backend-driven; copre il caso "tutti aprono e si addormentano" |
| 6 | Formula synergy_gain | Standard letteratura: `mean(individual_errors) - group_error` (assoluta) | Confrontabile direttamente con tabelle Hall & Watson 1970 |
| 7 | Visibilità nel PDF | Solo aggregato (`synergy_gain`, `assembly_bonus`, `mean_individual_error`) — niente per-partecipante | Privacy minima; i dati restano in DB |
| 8 | Moderatore AI vede ranking individuali | No, mai | Evita confounder per la valutazione empirica; coerente con design Hall & Watson |

## 4. Architettura e ciclo di vita

### 4.1. Stati di sessione

Nuovo stato `INDIVIDUAL_RANKING` aggiunto a `apps/sessions/models.py:SessionState`.

```
LOBBY → INDIVIDUAL_RANKING → ACTIVE → CONCLUSION → CLOSED   (NASA Moon, Lost at Sea)
LOBBY → ACTIVE → CONCLUSION → CLOSED                         (generic, murder_mystery)
```

### 4.2. Selezione della transizione (task plugin)

Nuovo metodo astratto su `TaskDefinition`:

```python
def requires_individual_ranking_phase(self) -> bool:
    return False  # default: no fase pre-discussione
```

- Override `True` in `NasaMoonTask` e `LostAtSeaTask`.
- L'orchestrator del "host preme Start" interroga questo metodo:
  - `True` → `LOBBY → INDIVIDUAL_RANKING`, salva `individual_ranking_started_at = now()`.
  - `False` → `LOBBY → ACTIVE` (comportamento attuale invariato).

### 4.3. Contratto della fase `INDIVIDUAL_RANKING`

Per zero ambiguità nei consumer (audio, moderator, frontend):

| Componente | Stato in INDIVIDUAL_RANKING |
|---|---|
| WebSocket sessions | ATTIVO (per pushare cambio stato + countdown UI) |
| WebSocket turns | SPENTO (no turn-taking) |
| WebRTC | SPENTO (peer connection non avviate) |
| Moderatore AI | SPENTO (zero LLM call, zero TTS) |
| ASR | SPENTO |
| HTTP REST individual ranking | ATTIVO (PUT autosave + POST submit + finalize) |

### 4.4. Vincolo architetturale

Il core (`apps/sessions`) non importa mai da `apps/tasks/<specifico>`. Tutte
le decisioni task-specifiche sulla fase individuale passano dal
`TaskDefinition` plugin.

## 5. Modelli dati

### 5.1. `NasaIndividualRanking` (nuovo)

`apps/tasks/nasa_moon/models.py`:

```python
class NasaIndividualRanking(models.Model):
    """Ranking individuale pre-discussione di un partecipante.
    Una riga per (sessione, partecipante). Autosave su PUT, marcato
    is_submitted=True su POST submit esplicito o alla finalizzazione
    della fase INDIVIDUAL_RANKING.
    """
    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "ai_sessions.Session",
        on_delete=models.CASCADE,
        related_name="nasa_individual_rankings",
    )
    participant = models.ForeignKey(
        "ai_sessions.SessionParticipant",
        on_delete=models.CASCADE,
        related_name="nasa_individual_rankings",
    )
    ranked_items = models.JSONField(
        help_text="Lista ordinata dei 15 oggetti (posizione 0 = più importante)."
    )
    is_submitted = models.BooleanField(
        default=False,
        help_text="True quando il partecipante ha confermato esplicitamente, "
                  "oppure quando la fase è stata finalizzata (timer scaduto / "
                  "tutti hanno submittato)."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tasks"
        db_table = "tasks_nasa_individual_ranking"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "participant"],
                name="uniq_nasa_individual_ranking_per_participant",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "is_submitted"]),
        ]
```

### 5.2. `LostAtSeaIndividualRanking` (nuovo)

Identico modulo i nomi: `related_name="lost_at_sea_individual_rankings"`,
`db_table="tasks_lost_at_sea_individual_ranking"`,
constraint `uniq_lost_at_sea_individual_ranking_per_participant`.

### 5.3. Campo nuovo su `Session`

```python
# apps/sessions/models.py — Session
individual_ranking_started_at = models.DateTimeField(
    null=True,
    blank=True,
    help_text="Timestamp di inizio fase INDIVIDUAL_RANKING. NULL per "
              "sessioni che non hanno questa fase. Serve a calcolare la "
              "scadenza del timer di 8 min e per il countdown UI."
)
```

### 5.4. Migrations richieste

1. `apps/sessions/migrations/00XX_add_individual_ranking_state.py`
   - Aggiunge `INDIVIDUAL_RANKING` a `SessionState.choices`.
   - Aggiunge campo `individual_ranking_started_at`.
2. `apps/tasks/nasa_moon/migrations/00XX_nasa_individual_ranking.py`
   - Crea tabella `tasks_nasa_individual_ranking`.
3. `apps/tasks/lost_at_sea/migrations/00XX_lost_at_sea_individual_ranking.py`
   - Crea tabella `tasks_lost_at_sea_individual_ranking`.

### 5.5. Note progettuali

- **`is_submitted` invece di `is_final`**: distinto dal pattern di
  `NasaRanking.is_final` perché la finalizzazione qui può avvenire in due modi
  (esplicita o automatica al timer), mentre `is_final` del ranking di gruppo è
  solo esplicita dell'host. Naming diverso = semantica diversa.
- **FK a `SessionParticipant`** (non a `User`): coerenza con
  `NasaRanking.submitted_by`. Il ranking è legato al ruolo nella sessione,
  non all'utente nudo.
- **`ranked_items: JSONField`**: stesso pattern di `NasaRanking.ranked_items`.
  Validazione (lunghezza, set match) lato view.
- **UniqueConstraint `(session, participant)`**: l'autosave fa
  `update_or_create` su quel constraint.

## 6. Endpoint REST

Quattro endpoint per task, simmetrici tra NASA e LAS.

### 6.1. NASA Moon

```
GET    /api/tasks/nasa-moon/sessions/{session_id}/individual-ranking/
PUT    /api/tasks/nasa-moon/sessions/{session_id}/individual-ranking/
POST   /api/tasks/nasa-moon/sessions/{session_id}/individual-ranking/submit/
POST   /api/tasks/nasa-moon/sessions/{session_id}/individual-ranking/finalize-if-expired/
```

### 6.2. Lost at Sea

```
GET    /api/tasks/lost-at-sea/sessions/{session_id}/individual-ranking/
PUT    /api/tasks/lost-at-sea/sessions/{session_id}/individual-ranking/
POST   /api/tasks/lost-at-sea/sessions/{session_id}/individual-ranking/submit/
POST   /api/tasks/lost-at-sea/sessions/{session_id}/individual-ranking/finalize-if-expired/
```

### 6.3. Semantica

#### `GET /individual-ranking/`

Restituisce il ranking del **chiamante** (non degli altri).

- **Permission**: membro della sessione, qualunque ruolo.
- **Risposta 200**:
  ```json
  {
    "ranked_items": ["...15 strings..."] | null,
    "is_submitted": false,
    "updated_at": "2026-05-06T...",
    "phase_deadline_at": "2026-05-06T..."
  }
  ```
  - `ranked_items: null` = nessuna riga ancora creata (frontend mostra
    `NASA_ITEMS`/`LAS_ITEMS` di default).
  - `phase_deadline_at = individual_ranking_started_at + 480s`.

#### `PUT /individual-ranking/` (autosave)

- **Body**: `{"ranked_items": [...15 strings...]}`.
- **Permission**: membro della sessione.
- **Validazioni** (in ordine):
  - `session.state == INDIVIDUAL_RANKING` → altrimenti 409.
  - `ranked_items` lista di esattamente 15 stringhe → 400 altrimenti.
  - Set deve coincidere con `task.expected_items_set()` → 400 altrimenti
    (no item invalidi, no mancanti, no duplicati).
  - Lazy timer check: se `now() > phase_deadline_at` → scatena
    `_finalize_individual_ranking_phase()` e risponde 409
    `{"detail": "Phase already expired"}`.
  - Lazy own-state check: se la riga esistente ha `is_submitted=True` → 409
    (no editing dopo submit esplicito).
- **Effetto**: `update_or_create` con `is_submitted=False`.
- **Risposta**: 200 (update) o 201 (create).

#### `POST /individual-ranking/submit/`

- **Body**: vuoto.
- **Permission**: membro della sessione.
- **Validazioni**:
  - `session.state == INDIVIDUAL_RANKING` → altrimenti 409.
  - Esiste riga per il partecipante (deve aver fatto almeno un PUT) → 400 altrimenti.
  - Non già `is_submitted=True` → 409 altrimenti.
- **Effetto**: marca `is_submitted=True`. Se dopo questo submit **tutti** i
  partecipanti hanno `is_submitted=True`, chiama
  `_finalize_individual_ranking_phase()` immediatamente (chiusura precoce).
- **Risposta 200**: `{"success": true, "is_submitted": true, "all_submitted": bool}`.

#### `POST /individual-ranking/finalize-if-expired/` (idempotente)

Chiamato dal frontend al setTimeout di 8 min.

- **Body**: vuoto.
- **Permission**: membro della sessione (qualunque ruolo: è una richiesta
  "autoritativa di sistema" che chiunque può scatenare).
- **Effetto**:
  - `session.state != INDIVIDUAL_RANKING` → 200 `{"finalized": false, "reason": "wrong_state"}`.
  - `now() < phase_deadline_at` → 200 `{"finalized": false, "reason": "not_expired"}`.
  - altrimenti → chiama `_finalize_individual_ranking_phase()` → 200 `{"finalized": true}`.
- **Idempotenza**: due chiamate consecutive non producono effetti diversi.
  Race condition gestita con `SELECT ... FOR UPDATE` su `Session` dentro la
  finalize.

### 6.4. Routing

File `urls.py` di ciascuna app task (`apps/tasks/nasa_moon/urls.py`,
`apps/tasks/lost_at_sea/urls.py`) — pattern già esistente, basta aggiungere
4 path entry per task.

## 7. Flusso end-to-end e finalizzazione

### 7.1. Punti di transizione

**`LOBBY → INDIVIDUAL_RANKING`** (host preme "Avvia"):

La transizione tocca **due luoghi** del codice attuale:

**(A) `Session.start()` in `apps/sessions/models.py:143-150`** — è il metodo
che oggi imposta `state = ACTIVE` e `started_at = now()`. Va modificato così
(pseudocodice):

```python
def start(self):
    if self.state != SessionState.LOBBY:
        raise ValidationError("La sessione non è in stato LOBBY.")
    if self.participants_count < self.min_size:
        raise ValidationError("Numero minimo di partecipanti non raggiunto.")

    from apps.tasks.registry import get_task
    task = get_task(self.context)

    if task.requires_individual_ranking_phase():
        self.state = SessionState.INDIVIDUAL_RANKING
        self.individual_ranking_started_at = timezone.now()
        # `started_at` NON viene impostato qui: resta NULL finché non si
        # transita davvero ad ACTIVE in _finalize_individual_ranking_phase().
    else:
        self.state = SessionState.ACTIVE
        self.started_at = timezone.now()
```

**(B) `SessionStartSerializer.save()` in `apps/sessions/serializers.py:218-230`** —
è il caller. Oggi fa `session.save(update_fields=["state", "started_at"])`,
e poi crea un `SessionEvent` di tipo `STARTED`. Entrambi vanno resi adattivi:

```python
@transaction.atomic
def save(self, **kwargs):
    session = self.instance
    session.start()
    session.full_clean()

    if session.state == SessionState.INDIVIDUAL_RANKING:
        session.save(update_fields=["state", "individual_ranking_started_at"])
        # nuovo SessionEventType (vedi sotto) o STARTED riusato col payload diverso
        SessionEvent.objects.create(
            session=session,
            type=SessionEventType.STARTED,  # decisione: vedi 7.1.bis
            actor=self.context["request"].user,
            payload={
                "phase": "INDIVIDUAL_RANKING",
                "individual_ranking_started_at": session.individual_ranking_started_at.isoformat(),
                "phase_deadline_at": (
                    session.individual_ranking_started_at
                    + timedelta(seconds=task.individual_ranking_duration_seconds())
                ).isoformat(),
            },
        )
    else:
        session.save(update_fields=["state", "started_at"])
        SessionEvent.objects.create(
            session=session,
            type=SessionEventType.STARTED,
            actor=self.context["request"].user,
            payload={"started_at": session.started_at.isoformat()},
        )
    return session
```

Nota su `full_clean()`: oggi viene chiamato dopo `start()` per validare il
modello. La migration deve aggiungere `INDIVIDUAL_RANKING` a
`SessionState.choices` *prima* che il codice deployato chiami `full_clean()`,
altrimenti la validazione fallirebbe per una sessione mai avviata.

**WS push del cambio stato**: il broadcast WebSocket `STATE_CHANGED`
(payload con `state: "INDIVIDUAL_RANKING"` e `phase_deadline_at`) avviene
dove avviene oggi per `STARTED → ACTIVE` (vedi `apps/sessions/views.py`).
Questo consumer va reso simmetrico: pusha sia per `INDIVIDUAL_RANKING` sia
per `ACTIVE` quando la transizione avviene da `LOBBY`.

### 7.1.bis. SessionEventType nuovo (decisione minore)

Riusiamo `SessionEventType.STARTED` con payload differente, oppure aggiungiamo
un nuovo type `INDIVIDUAL_RANKING_STARTED`? La spec opta per **riusare
STARTED** con un campo `phase` nel payload — minimizza churn nello schema
e rispetta il principio "STARTED = la sessione è uscita dalla lobby". Se in
futuro emergesse necessità di filtri più granulari nei log, si può separare.

**`INDIVIDUAL_RANKING → ACTIVE`**: solo via
`_finalize_individual_ranking_phase()` (sezione 7.2). Non c'è nessun altro
percorso valido per questa transizione.

### 7.2. `_finalize_individual_ranking_phase(session)` — pseudocodice

Modulo nuovo: `apps/tasks/individual_ranking.py` (livello core, agnostico:
delega al plugin per il modello concreto).

```python
def _finalize_individual_ranking_phase(session: Session) -> bool:
    """Chiude INDIVIDUAL_RANKING e transita a ACTIVE.
    Idempotente. Returns True se la finalizzazione è avvenuta in questa
    chiamata, False se era già stata fatta."""

    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        if session.state != SessionState.INDIVIDUAL_RANKING:
            return False

        task = get_task(session.context)
        Model = task.individual_ranking_model()
        default_items = task.default_individual_ranking()

        for p in session.participants.all():
            ranking, created = Model.objects.get_or_create(
                session=session,
                participant=p,
                defaults={
                    "ranked_items": default_items,
                    "is_submitted": True,
                },
            )
            if not created and not ranking.is_submitted:
                ranking.is_submitted = True
                ranking.save(update_fields=["is_submitted", "updated_at"])

        session.state = SessionState.ACTIVE
        session.started_at = timezone.now()
        session.save(update_fields=["state", "started_at"])

    # Fuori transazione
    _broadcast_session_event(
        session_id=str(session.id),
        event_type="STATE_CHANGED",
        payload={"state": "ACTIVE", "started_at": session.started_at.isoformat()},
    )
    mark_session_started(session.id)
    return True
```

### 7.3. Nuovi metodi `TaskDefinition`

```python
def requires_individual_ranking_phase(self) -> bool:
    return False

def individual_ranking_duration_seconds(self) -> int:
    return 480  # 8 min

def individual_ranking_model(self) -> Optional[Type[Model]]:
    return None

def default_individual_ranking(self) -> list[str]:
    return []

def expected_items_set(self) -> set[str]:
    """Set di item validi per il ranking individuale (validazione PUT)."""
    return set()
```

Override su `NasaMoonTask` e `LostAtSeaTask`. Default no-op per
`generic` e `murder_mystery`.

### 7.4. Punti di trigger della finalizzazione

| # | Quando | Innescato da |
|---|---|---|
| 1 | Tutti hanno `is_submitted=True` | `POST /submit/` (chiusura precoce) |
| 2 | `now() > phase_deadline_at` durante un input | Lazy check su `PUT` o `POST submit` |
| 3 | Frontend setTimeout 8 min | `POST /finalize-if-expired/` |

Tutti i percorsi convergono nella stessa funzione idempotente.

## 8. Calcolo `synergy_gain` nel report

### 8.1. Modifica a `collect_nasa_report_context(session)`

Simmetrica per LAS (`collect_lost_at_sea_report_context`).

```python
def collect_nasa_report_context(session) -> Dict[str, Any]:
    from .models import NasaRanking, NasaIndividualRanking

    base = { ... ranking di gruppo come oggi ... }

    individual_rankings = list(
        NasaIndividualRanking.objects.filter(session=session, is_submitted=True)
    )

    if individual_rankings and base.get("has_ranking"):
        individual_errors = [compute_error_score(r.ranked_items) for r in individual_rankings]
        group_error = base["error_score"]
        mean_individual_error = sum(individual_errors) / len(individual_errors)

        base["individual_errors"] = individual_errors
        base["mean_individual_error"] = mean_individual_error
        base["synergy_gain"] = mean_individual_error - group_error
        base["assembly_bonus"] = group_error < min(individual_errors)
        base["individual_count"] = len(individual_errors)
    # else: i campi restano None come oggi (sessione legacy senza fase individuale)

    return base
```

### 8.2. Formule (standard letteratura Hall 1962, Hall & Watson 1970)

- `group_error` = `compute_error_score(group_ranking.ranked_items)` (esistente).
- `individual_errors[i]` = `compute_error_score(rankings[i].ranked_items)`.
- `mean_individual_error` = `sum(individual_errors) / len(individual_errors)`.
- `synergy_gain` = `mean_individual_error - group_error`.
  - Positivo → il gruppo ha fatto meglio della media individuale.
  - Negativo → process loss.
- `assembly_bonus` = `group_error < min(individual_errors)`.
  - True → vera sinergia (gruppo > miglior individuo).

### 8.3. PDF `build_nasa_pdf_sections` (e LAS)

Sostituire il placeholder esistente "N/A — richiede la fase di ranking
individuale (in arrivo)" in `apps/tasks/nasa_moon/report.py:206-220` con
output reale quando `synergy_gain is not None`. Esempio:

```
Synergy gain: +8.3 punti
(differenza tra error medio individuale 43.7 e error di gruppo 35.4 — il gruppo
ha migliorato rispetto alla media individuale)

Assembly bonus: SÌ
(il gruppo ha fatto meglio del miglior individuo: 35.4 vs 38.0)
```

Nessuna tabella per-partecipante (decisione 7).

### 8.4. Prompt LLM del report

`build_nasa_report_llm_prompt` e `build_lost_at_sea_report_llm_prompt`
**già menzionano** `synergy_gain` condizionalmente (vedi
`apps/tasks/nasa_moon/report.py:42-44` e analogo LAS). Modifiche minime:

- Rimuovere la postilla "the experimental flow is not fully active yet" che
  diventa obsoleta.
- Mantenere la condizionale "if `synergy_gain` is provided, comment ...".

## 9. Testing strategy

### 9.1. Unit test (Django TestCase)

1. **`apps/tasks/nasa_moon/tests/test_individual_ranking.py`** (nuovo):
   - GET su sessione senza riga → `ranked_items: null`.
   - PUT validi creano/aggiornano la riga, `is_submitted=False`.
   - PUT con item invalidi / duplicati / lunghezza errata → 400.
   - PUT in stato sessione sbagliato → 409.
   - PUT dopo `is_submitted=True` → 409.
   - POST submit valido → marca `is_submitted=True`.
   - POST submit quando tutti hanno submittato → trigger
     `_finalize_individual_ranking_phase` → state diventa `ACTIVE`.
   - POST finalize-if-expired prima della scadenza → no-op
     `finalized: false`.
   - POST finalize-if-expired dopo scadenza → finalize, state diventa
     `ACTIVE`.
   - Finalize crea righe di default per partecipanti senza riga.
   - Finalize è idempotente (chiamata 2 volte = una sola transizione).

2. **`apps/tasks/lost_at_sea/tests/test_individual_ranking.py`** — simmetrico.

3. **`apps/tasks/tests/test_individual_ranking_phase.py`** (nuovo) — copre la
   transizione di stato a livello core:
   - Sessione `nasa_moon_survival`: start → state diventa
     `INDIVIDUAL_RANKING`.
   - Sessione `lost_at_sea`: start → state diventa `INDIVIDUAL_RANKING`.
   - Sessione `generic`: start → state diventa `ACTIVE` (regression).
   - Sessione `murder_mystery`: start → state diventa `ACTIVE` (regression).

4. **`apps/reports/tests.py`** — estensione:
   - `collect_nasa_report_context` con N ranking individuali → calcola
     `synergy_gain`, `assembly_bonus`, `mean_individual_error`.
   - Edge case: zero ranking individuali (sessione legacy) → campi restano
     `None`.
   - Stesso per `collect_lost_at_sea_report_context`.

### 9.2. Integration test

Pattern già esistente (`apps/moderation/tests_integration.py`): client REST +
WS. Non strettamente necessario nella prima iterazione — valutare dopo se
i test unit non bastano per coprire la finalizzazione + WS push.

### 9.3. Comando di esecuzione

```
docker compose run --rm web python manage.py test --noinput \
  apps.tasks.nasa_moon.tests.test_individual_ranking \
  apps.tasks.lost_at_sea.tests.test_individual_ranking \
  apps.tasks.tests.test_individual_ranking_phase \
  apps.reports.tests \
  apps.sessions.tests
```

Target: i 237+ test esistenti restano verdi, +nuovi.

## 10. Deploy e rollout

**Strategia: backend-first, frontend dopo, niente feature flag.**

Sequenza:

1. **Implementazione + test backend in locale** (modelli, endpoint, transizioni,
   finalizzazione, report). Tutti i test verdi.
2. **Brief al Claude del frontend**: al termine dell'implementazione backend,
   produciamo un documento dettagliato (in questa stessa repo, ad esempio in
   `docs/plans/2026-05-06-individual-ranking-frontend-brief.md` oppure
   inviato direttamente nella sessione frontend) che descrive:
   - nuovo stato `INDIVIDUAL_RANKING` e cosa significa per la UI;
   - nuova pagina dedicata al ranking individuale (pubblica a *tutti* i
     partecipanti, non solo l'host — divergenza significativa rispetto alla
     pagina attuale del ranking di gruppo);
   - meccanica autosave (PUT debounced) e submit esplicito;
   - countdown UI degli 8 minuti calcolato da `phase_deadline_at`;
   - chiamata a `POST /finalize-if-expired/` allo scadere del setTimeout;
   - reazione al WS `STATE_CHANGED` con `state: ACTIVE` per navigare alla
     pagina di discussione esistente.
3. **Implementazione frontend** (lavoro parallelo nella repo separata).
4. **Deploy coordinato**: prima frontend (carica artefatti statici, pronto
   ma inattivo perché il backend ancora non emette `INDIVIDUAL_RANKING`),
   poi backend con migrations. Da questo momento le sessioni NASA/LAS nuove
   useranno il flow.
5. Sessioni in corso al deploy backend: nessuna è in `INDIVIDUAL_RANKING`
   (stato nuovo), zero impatto.

Migration backward compat: `individual_ranking_started_at` ha `null=True`,
sessioni precedenti non subiscono effetti. Lo stato `INDIVIDUAL_RANKING` è
additivo all'enum.

**Perché non una feature flag**: introduce complessità (env var, branching
nel TaskDefinition, override_settings nei test) per coprire un caso di
rollout che è naturalmente già a basso rischio (il VPS è uno solo, il
deploy è manuale e coordinato, non c'è rolling/canary su più nodi).
Si valuterà di aggiungerla solo se emerge un bisogno operativo concreto.

## 11. Rischi e mitigazioni

| Rischio | Probabilità | Mitigazione |
|---|---|---|
| Frontend non aggiornato al deploy backend → sessioni NASA/LAS non avviabili | Media (rollout manuale) | Sequenza esplicita in §10: deploy frontend prima, backend dopo. Eventualmente revert backend (`git revert` + redeploy) finché i due non sono allineati |
| Tutti i partecipanti chiudono il browser → setTimeout perso → fase non finalizza | Bassa | Lazy check sui successivi PUT di altri (improbabile ma possibile in scenari estremi). In ultima istanza un endpoint admin manuale (out of scope ora) |
| Race condition: due `POST /submit/` simultanei dell'ultimo partecipante | Bassa | `select_for_update` su `Session` nella finalize garantisce idempotenza |
| Migration `INDIVIDUAL_RANKING` non in produzione ma codice deployato | Media | Standard ordering: `migrate` prima di restart del web |
| Crash Daphne durante INDIVIDUAL_RANKING | Bassa | Lazy check al riavvio: il primo PUT/POST trigger di chiunque finalizza se necessario |

## 12. File e luoghi di intervento

| File | Tipo | Cambiamento |
|---|---|---|
| `apps/sessions/models.py` | Mod | `+INDIVIDUAL_RANKING` in `SessionState`, `+individual_ranking_started_at` |
| `apps/sessions/migrations/00XX_*.py` | New | Migration per campo + enum |
| `apps/sessions/serializers.py` | Mod | Endpoint start consulta `task.requires_individual_ranking_phase()` |
| `apps/tasks/base.py` | Mod | +5 metodi nuovi su `TaskDefinition` con default no-op |
| `apps/tasks/individual_ranking.py` | New | `_finalize_individual_ranking_phase(session)` |
| `apps/tasks/nasa_moon/models.py` | Mod | `+NasaIndividualRanking` |
| `apps/tasks/nasa_moon/migrations/00XX_*.py` | New | Crea tabella |
| `apps/tasks/nasa_moon/views.py` | Mod | `+NasaIndividualRankingView` (GET/PUT), `+NasaIndividualRankingSubmitView`, `+NasaIndividualRankingFinalizeView` |
| `apps/tasks/nasa_moon/urls.py` | Mod | +4 path entry |
| `apps/tasks/nasa_moon/task.py` | Mod | Override 5 nuovi metodi `TaskDefinition` |
| `apps/tasks/nasa_moon/report.py` | Mod | `collect_nasa_report_context` popola synergy_gain, etc.; `build_nasa_pdf_sections` rimuove placeholder |
| `apps/tasks/lost_at_sea/*` | Mod | Simmetrico a `nasa_moon/*` |
| `apps/tasks/{nasa_moon,lost_at_sea}/tests/test_individual_ranking.py` | New | Test unit per task |
| `apps/tasks/tests/test_individual_ranking_phase.py` | New | Test transizioni a livello core |
| `apps/reports/tests.py` | Mod | Test extension per synergy_gain |

## 13. Open questions (non bloccanti per la spec)

- Permessi di accesso al `POST /finalize-if-expired/`: oggi propongo
  "membro qualunque della sessione". Se in futuro emerge un caso d'uso di
  abuso (utenti che chiudono prematuramente la fase chiamando l'endpoint
  prima della scadenza) si può restringere a "host", ma il check
  `now() < phase_deadline_at` lato backend è già la difesa primaria — il
  permesso è solo difesa in profondità.
- Naming dell'endpoint REST top-level dei task: oggi `/api/tasks/<task>/...`,
  ma alcuni preferiscono `/api/<task>/...` senza prefisso. Mantenuto il
  pattern esistente per coerenza.
