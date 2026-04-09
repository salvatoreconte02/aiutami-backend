# Task-Pluggable Architecture Refactor

**Data:** 2026-04-08
**Stato:** Piano in attesa di approvazione (NO CODE)
**Autore:** sessione di brainstorming

---

## 1. Obiettivo e motivazione

Il backend AIutami è nato come progetto d'esame su un singolo task (Murder Mystery)
e ha logica MM-specifica sparsa in `sessions`, `moderation`, `reports`. Per la
tesi serve supportare tre task:

- **`murder_mystery`** — identico a oggi (suspects, voting, prompt specifico).
  Serve come test di non-regressione e come secondo task per dimostrare generalità.
- **`nasa_moon_survival`** — nuovo, per la valutazione empirica (Hall & Watson 1970).
  Scenario "stranded on the moon", 15 item da rankare, scoring vs expert ranking,
  prompt moderatore basato sulle 6 procedural ground rules.
- **`generic`** — moderatore "puro" che non sa di alcun task specifico. Serve come
  default/sandbox e soprattutto come **prova architetturale** che il sistema è
  davvero task-agnostic. In CONCLUSION non raccoglie nulla: il moderatore riassume
  la discussione e la sessione chiude.

Requisito duro: **il comportamento di Murder Mystery deve restare identico al
100%** dopo il refactor. Il refactor è puramente strutturale.

Infrastruttura condivisa (invariata): login/signup, lifecycle
`LOBBY → ACTIVE → CONCLUSION → CLOSED`, lobby, WebRTC audio hub, ASR, TTS,
trigger engine temporale, orchestrator moderation, report PDF.

---

## 2. Decisioni architetturali (confermate dall'utente)

| # | Decisione | Scelta |
|---|-----------|--------|
| D1 | Identità task in DB | Host sceglie in creazione tra i 3 task. Campo `Session.context` resta `CharField` ma i valori diventano le chiavi del `TaskRegistry` (`"murder_mystery"`, `"nasa_moon_survival"`, `"generic"`). Validazione contro registry, non contro enum. |
| D2 | Voting/Submission | `SessionVote` **non è core**. Resta un modello MM-only. NASA avrà il proprio modello `NasaRanking`. GENERIC non ha nessun modello di submission. |
| D3 | Prompt LLM | **Ibrido**: core definisce scheletro fisso (output JSON, tono, cooldown, no-saluti, criteri monopolizzazione/esclusione). Il task fornisce un `task_context_block` concatenato dentro lo scheletro. |
| D4 | CONCLUSION in GENERIC | Nessuna attesa utente, nessun `ready_to_conclude`, nessun dato raccolto. Il moderatore fa il riassunto finale e la sessione chiude automaticamente. |

---

## 3. Stato attuale — mappa completa del coupling MM

### 3.1 Hardcoded stringhe/costanti

| File:riga | Cosa |
|-----------|------|
| `apps/sessions/models.py:18-23` | `SessionContext` enum con MM + 3 valori mai usati (THERAPEUTIC, WORKPLACE, ACADEMIC) |
| `apps/sessions/models.py:40-41` | `MURDER_MYSTERY_SUSPECTS = ["Eddie","Mickey","Billy"]`, `MURDER_MYSTERY_GUILTY = "Eddie"` |
| `apps/sessions/views.py:16` | Import di `MURDER_MYSTERY_SUSPECTS/GUILTY` |
| `apps/sessions/serializers.py:19` | Import di `MURDER_MYSTERY_GUILTY` |
| `apps/reports/pdf_service.py:34` | Import di `MURDER_MYSTERY_GUILTY` |
| `apps/reports/pdf_service.py:91` | Titolo PDF `"REPORT SESSIONE MURDER MYSTERY"` |
| `apps/reports/llm_service.py:15-45` | `REPORT_SYSTEM_PROMPT` interamente scritto per MM |
| `apps/moderation/service.py:199,437,587` | `"scenario.type": "murder_mystery"` nei 3 LLM input payload |
| `apps/moderation/service.py:716-787` | `_build_normal_mode_prompt()` MM-scritto ("murder mystery", "indizi", "assassino", "colpevole") |
| `apps/moderation/service.py:656-713` | `_build_forced_summary_system_prompt()` MM-scritto |
| `apps/moderation/service.py:481-517` | `_build_forced_conclusion_system_prompt()` MM-scritto ("selezionare il colpevole") |
| `apps/moderation/service.py:521-540` | `_fallback_forced_conclusion` MM-hardcoded ("colpevole", "votato", "indovinato") |
| `apps/moderation/service.py:811-835` | `_build_forced_summary_prompt` (duplicato?) MM-scritto |
| `apps/moderation/intro.py:7-13` | `INTRO_MESSAGE_TEMPLATE` contiene "quando avrete capito chi è il colpevole, premete 'Pronto alla conclusione'" |
| `apps/moderation/intro.py:22` | Format nomi `len(names) == 3` assume 3 partecipanti |

### 3.2 Logica branch su contesto MM

| File:riga | Cosa |
|-----------|------|
| `apps/sessions/models.py:109-113` | `clean()`: `if context == MURDER_MYSTERY: min=max=3` |
| `apps/sessions/serializers.py:81-89` | `validate()`: forza `min_size=max_size=3` se MM, altrimenti richiede campi |

### 3.3 Accoppiamenti MM (SessionVote e affini)

| File:riga | Cosa |
|-----------|------|
| `apps/sessions/models.py:231-259` | Model `SessionVote` con `suspect_chosen: CharField` |
| `apps/sessions/views.py:329-421` | `SessionVoteView` (POST voto): valida contro suspects, calcola `is_correct` vs GUILTY |
| `apps/sessions/views.py:424-453` | `SessionVoteStatusView`: ritorna stato voti aggregato |
| `apps/sessions/serializers.py:187-214` | `SessionDetailSerializer.get_votes_summary` |
| `apps/sessions/services.py:113-138` | `_collect_report_data`: raccoglie SessionVote + calcola correttezza |
| `apps/reports/pdf_service.py:103-111` | Raccoglie voti e calcola vs GUILTY |

### 3.4 Moduli già generici (OK, nessun cambiamento)

- `apps/asr/` tutto
- `apps/tts/` tutto
- `apps/webrtc/` tutto
- `apps/turns/` tutto
- `apps/moderation/state.py`, `pending_messages.py`, `orchestrator.py`, `timers_state.py`, `triggers.py` (trigger engine è task-agnostic)
- `apps/sessions/permissions.py`, `routing.py`, `ws_consumer.py`, `urls.py`
- `apps/reports/views.py`, `urls.py`

### 3.5 Trigger temporali — già generici

Tutti i trigger (NO_PUSH, TIMER_25, TIMER_30, INACTIVE_USER_TEXT/VOICE,
READY_TO_CONCLUDE, RESERVATION, FORCED_SUMMARY, FORCED_CONCLUSION) non
referenziano MM. L'unica specificità MM è dentro i **prompt passati al
moderation service**, non nei trigger stessi. Significa che il task GENERIC
riutilizza gli stessi trigger senza modifiche.

### 3.6 Test impattati

- `apps/sessions/tests.py`: `SessionVoteModelTests`, `VoteEndpointTests`, + quasi
  tutti gli altri test creano sessioni MM con min/max=3 nella fixture setUp
- `apps/reports/tests.py`: `ReportPDFServiceTests`, `ReportDownloadEndpointTests`,
  `ReportLLMServiceTests` (ha nomi "Eddie" nei dati)
- `apps/turns/tests_services.py` e `tests/test_services.py`: setup MM
- `apps/moderation/tests*.py`: **quasi tutti generici** (testano trigger e state),
  nessun hardcoded MM significativo

---

## 4. Design dell'interfaccia `TaskDefinition`

### 4.1 Struttura cartelle finale

```
apps/
  tasks/
    __init__.py
    apps.py
    base.py              # ABC TaskDefinition + dataclass helpers
    registry.py          # _REGISTRY dict, register(), get_task(), all_keys()
    migrations/
    tests/
      test_registry.py
      test_generic.py
      test_murder_mystery.py
      test_nasa_moon.py

    generic/
      __init__.py        # registra GenericTask alla import
      task.py            # class GenericTask(TaskDefinition)
      prompts.py         # task_context_block strings (vuoto o minimo)

    murder_mystery/
      __init__.py        # registra MurderMysteryTask
      task.py
      prompts.py         # stringhe estratte da moderation/service.py
      config.py          # SUSPECTS, GUILTY
      models.py          # SessionVote (spostato qui, vedi §6 per migration)
      views.py           # SessionVoteView, SessionVoteStatusView
      serializers.py     # VoteSerializer, votes_summary helper
      urls.py            # /api/sessions/<id>/vote/, /vote-status/
      report.py          # build_report_prompt(), build_report_pdf_sections()

    nasa_moon/
      __init__.py        # registra NasaMoonTask
      task.py
      prompts.py         # scenario + 6 ground rules Hall & Watson 1970
      config.py          # NASA_ITEMS (15), EXPERT_RANKING, rationale
      models.py          # NasaRanking (participant → ordered list of 15 items)
      views.py           # NasaRankingView, NasaRankingStatusView
      serializers.py
      urls.py            # /api/sessions/<id>/ranking/, /ranking-status/
      report.py          # scoring vs expert, pdf sections
      migrations/
```

Regola d'oro: **il core (`apps/sessions`, `apps/moderation`, `apps/reports`,
`apps/turns`, `apps/asr`, `apps/tts`, `apps/webrtc`) NON importa nulla da
`apps.tasks.<specific>`**. Accede sempre via `apps.tasks.registry.get_task(key)`
e interagisce solo con metodi dell'interfaccia astratta.

### 4.2 Interfaccia `TaskDefinition` (ABC)

```python
# apps/tasks/base.py (schema, non codice finale)

class TaskDefinition(ABC):
    key: str                       # "murder_mystery"
    display_name: str              # "Murder Mystery"

    # Capienza
    min_participants: int
    max_participants: int
    fixed_size: bool               # True per MM (3/3), False altrimenti

    # --- Prompt building (moderation) ---
    def llm_scenario_payload(self) -> dict:
        """Ritorna il dict da inserire come 'scenario' nell'LLM input
        (es. {'type': 'murder_mystery', 'objective': '...'} per MM,
        {} per GENERIC)."""

    def task_context_block(self, mode: Literal["normal","forced_summary","forced_conclusion"]) -> str:
        """Blocco di testo task-specifico che il core concatenerà dentro
        lo scheletro del system prompt in posizione ben definita (es. sotto
        la sezione '## Scenario'). Può essere stringa vuota (GENERIC)."""

    def fallback_forced_conclusion_body(self, summary: str, conclusion_reason: str) -> str:
        """Testo di fallback quando LLM forced_conclusion fallisce.
        Per GENERIC: solo riepilogo + ringraziamento.
        Per MM: riepilogo + 'selezionate il colpevole' + ringraziamento.
        Per NASA: riepilogo + 'sottomettete il ranking finale' + ringraziamento."""

    # --- Intro message ---
    def intro_message_tail(self) -> str:
        """Parte finale dell'intro message (dopo 'Avrete 30 minuti').
        MM: '...Quando avrete capito chi è il colpevole, premete Pronto alla conclusione.'
        NASA: '...Al termine sottometterete il vostro ranking dei 15 oggetti.'
        GENERIC: '' (niente, fine)."""

    # --- Conclusion / submission ---
    requires_submission: bool      # MM=True, NASA=True, GENERIC=False

    def submission_urls(self) -> list | None:
        """Lista URL patterns da montare sotto /api/sessions/<id>/task/...
        Oppure None per GENERIC."""

    def all_submissions_received(self, session) -> bool:
        """Chiamato dal services.close_session per sapere se si può chiudere.
        GENERIC ritorna sempre True. MM: tutti i participant hanno votato.
        NASA: tutti i participant hanno sottomesso un ranking."""

    # --- Report ---
    def report_title(self) -> str:
        """Titolo PDF. MM='REPORT SESSIONE MURDER MYSTERY',
        NASA='REPORT NASA MOON SURVIVAL', GENERIC='REPORT SESSIONE'."""

    def build_report_llm_prompt(self, session, transcript_text: str) -> str:
        """System prompt task-specifico per llm_service.generate_report_text.
        GENERIC: prompt generico (riassunto discussione, partecipazione,
        qualità dello scambio)."""

    def build_report_pdf_sections(self, session, doc_context: dict) -> list:
        """Ritorna lista di flowables ReportLab aggiuntivi task-specifici
        da inserire nel PDF (votes table per MM, ranking + scoring per NASA,
        lista vuota per GENERIC)."""
```

### 4.3 Registry

```python
# apps/tasks/registry.py (schema)

_REGISTRY: dict[str, TaskDefinition] = {}

def register(task: TaskDefinition) -> None: ...
def get_task(key: str) -> TaskDefinition:  # raise KeyError se non registrato
def all_keys() -> list[str]: ...
def task_choices() -> list[tuple[str, str]]:  # per serializer validation
```

Registrazione: ogni `apps/tasks/<x>/__init__.py` importa la propria task class
e chiama `register()`. `apps/tasks/apps.py` (`TasksConfig.ready()`) fa
`from . import generic, murder_mystery, nasa_moon` per forzare la registrazione
al boot Django.

### 4.4 Come il core usa TaskDefinition — 5 punti di integrazione

| Punto | File core | Cosa cambia |
|-------|-----------|-------------|
| 1. Validazione creazione session | `sessions/serializers.py`, `sessions/models.py:clean` | Usa `task = get_task(context)`; se `task.fixed_size`, forza `min=max=task.min_participants`. Altrimenti accetta min/max passati purché rispettino i limiti del task. |
| 2. System prompt LLM | `moderation/service.py` (3 `_build_*` + `_fallback_*`) | Ognuno dei 3 prompt builder diventa: `base_prompt + task.task_context_block(mode)`. I payload `llm_input["scenario"]` usano `task.llm_scenario_payload()`. Il fallback conclusion usa `task.fallback_forced_conclusion_body(...)`. |
| 3. Intro message | `moderation/intro.py` | `INTRO_MESSAGE_TEMPLATE` diventa scheletro + `task.intro_message_tail()`. La formattazione nomi va generalizzata (`intro.py:22`) per supportare `len(names)` variabile. |
| 4. Close session / attesa submission | `sessions/services.py:close_session` e `_collect_report_data` | Usa `task.all_submissions_received(session)` invece dell'attuale logica MM-specifica sui voti. `_collect_report_data` delega la parte task-specifica a `task.build_report_pdf_sections()` e `task.build_report_llm_prompt()`. |
| 5. Submission endpoints | `sessions/urls.py` | Include dinamicamente `task.submission_urls()` per ogni task registrato sotto un prefisso task-specifico, es. `/api/sessions/<id>/task/mm/vote/`, `/api/sessions/<id>/task/nasa/ranking/`. |

---

## 5. Migrazione step-by-step

Ogni step è un **commit indipendente** e lascia il codice e i test **verdi**.
Ordine pensato per minimizzare rischio e mantenere Murder Mystery funzionante
end-to-end ad ogni step.

### Step 0 — Scaffolding (nessun cambio di comportamento)

- Creare `apps/tasks/` con `base.py` (ABC vuota), `registry.py`, `apps.py`.
- Aggiungere `"apps.tasks"` a `INSTALLED_APPS` (prima di sessions? no, dopo — l'ordine
  non conta perché tasks non ha modelli al momento dello Step 0).
- Test `test_registry.py` che verifica register/get/all_keys.
- **Verifica**: tutti i test esistenti passano, `manage.py check` ok.

### Step 1 — MurderMysteryTask come wrapper "invisibile"

- Creare `apps/tasks/murder_mystery/task.py` con `MurderMysteryTask(TaskDefinition)`.
- `task_context_block()` ritorna stringa vuota per ora (i prompt core restano quelli
  di oggi, immutati).
- `llm_scenario_payload()` ritorna `{"type":"murder_mystery","objective":"..."}`
  identico a quello che oggi sta in `service.py:198-201`.
- `intro_message_tail()` ritorna la stringa esistente "Quando avrete capito chi è
  il colpevole…".
- `fallback_forced_conclusion_body()` ritorna il testo esatto di oggi.
- `min_participants=max_participants=3`, `fixed_size=True`.
- `requires_submission=True`.
- `report_title()` ritorna "REPORT SESSIONE MURDER MYSTERY".
- Per ora `build_report_*`, `submission_urls`, `all_submissions_received` possono
  essere stub che importano/chiamano la logica esistente in `sessions/views.py` e
  `reports/pdf_service.py` (via import indiretto — accettabile temporaneamente).
- Registrare in `apps/tasks/murder_mystery/__init__.py`.
- **Il core non usa ancora la task.** Questo step solo crea il plugin in parallelo.
- **Verifica**: tutti i test passano; `get_task("murder_mystery")` funziona.

### Step 2 — Session model e validation passano a registry

- `sessions/models.py`: `SessionContext` enum → eliminare i 3 valori inutilizzati
  (THERAPEUTIC, WORKPLACE, ACADEMIC). Rinominare `MURDER_MYSTERY = "MURDER_MYSTERY"`
  → valore stringa `"murder_mystery"` (lowercase, coerente con registry key).
  **Migration necessaria**: data migration che aggiorna le righe esistenti.
- `Session.clean()`: sostituire la logica hardcoded con
  ```
  task = get_task(self.context)
  if task.fixed_size:
      if self.min_size != task.min_participants or self.max_size != task.max_participants:
          raise ValidationError(...)
  ```
- `serializers.py:validate`: idem, usa `get_task(context)`.
- `serializers.py:19`: rimuovere import di `MURDER_MYSTERY_GUILTY` (da qui in poi
  lo importa solo la view del voting, che rimane per ora).
- **Test da aggiornare**: quelli che usano `SessionContext.MURDER_MYSTERY` passano
  alla nuova stringa. Il comportamento resta identico.
- **Verifica**: tutti i test passano, migration runs clean, MM funziona e2e.

### Step 3 — Estrazione prompt LLM moderator (core passa a schema ibrido)

- Creare `apps/tasks/murder_mystery/prompts.py` con 3 stringhe corrispondenti al
  contenuto "di scenario" dei prompt attuali (`## Scenario\nI partecipanti stanno
  giocando a un murder mystery...`). Queste diventano i `task_context_block` per
  ciascun mode.
- `MurderMysteryTask.task_context_block(mode)` ritorna la stringa corrispondente.
- `apps/moderation/service.py`:
  - I 3 `_build_*_prompt()` vengono riscritti come scheletri generici (output JSON
    format, tono, cooldown, criteri monopolizzazione/esclusione, no-saluti) +
    un placeholder tipo `{task_context_block}` che il caller sostituisce.
  - Il metodo pubblico che costruisce il prompt riceve `task_key` come parametro
    (oppure prende `session` e legge `session.context`), chiama `get_task(key)`,
    concatena il task block nel punto giusto.
  - Stesso trattamento per `_fallback_forced_conclusion` che ora delega a
    `task.fallback_forced_conclusion_body(summary, conclusion_reason)`.
  - Payload LLM: `llm_input["scenario"] = task.llm_scenario_payload()`.
- Propagare `task_key` (o `session_id`) fino ai call sites in `orchestrator.py`
  se non è già disponibile. Da verificare nei dettagli dell'orchestrator.
- **Test**: i test moderation esistenti devono passare. Aggiungere
  `test_prompt_composition.py` che verifica: il prompt finale per MM contiene
  ancora le parole chiave "murder mystery", "indizi", "colpevole", e contiene
  anche lo scheletro generico. Per GENERIC (quando esisterà) il prompt NON
  conterrà quelle parole.
- **Verifica**: comportamento MM identico. Log `[MODERATION][LLM][REQUEST]`
  identici per una sessione MM.

### Step 4 — Intro message parametrizzato

- `apps/moderation/intro.py`: template diventa scheletro senza la frase finale
  MM-specifica. Aggiunge `task.intro_message_tail()`.
- Formattazione nomi (`intro.py:22`) generalizzata a `len(names)` qualunque.
- Chi chiama `build_intro_message()` passa `task_key` (o `session`).
- **Verifica**: i `tests_intro.py` passano, intro MM identico a oggi.

### Step 5 — Report PDF e LLM parametrizzati

- `apps/reports/llm_service.py`: `REPORT_SYSTEM_PROMPT` sparisce. Il metodo
  `generate_report_text` prende `session` → `task = get_task(session.context)`
  → `system_prompt = task.build_report_llm_prompt(session, transcript_text)`.
- Per MM: `MurderMysteryTask.build_report_llm_prompt()` ritorna il prompt
  attuale (spostato in `apps/tasks/murder_mystery/report.py`).
- `apps/reports/pdf_service.py`:
  - Titolo da `task.report_title()`.
  - Sezione voti (attualmente `pdf_service.py:103-111`) spostata dentro
    `MurderMysteryTask.build_report_pdf_sections()`. Il core itera le sezioni
    restituite e le appende a `story`.
  - Rimuove import di `MURDER_MYSTERY_GUILTY` dal core.
- `sessions/services.py:_collect_report_data`: la parte che raccoglie voti e
  calcola correttezza sparisce dal core e finisce dentro `MurderMysteryTask`.
  Il core chiama `task.collect_report_context(session)` che ritorna un dict
  arbitrario passato poi a PDF/LLM.
- **Verifica**: `apps/reports/tests.py` passa. Report MM generato e identico a
  prima (diff PDF binario impossibile, ma contenuto testuale equivalente).

### Step 6 — Vote endpoints migrano a `apps/tasks/murder_mystery/`

- Spostare `SessionVoteView`, `SessionVoteStatusView` da `apps/sessions/views.py`
  a `apps/tasks/murder_mystery/views.py`.
- Spostare lo snippet di votes_summary da `sessions/serializers.py:187-214`
  a `apps/tasks/murder_mystery/serializers.py` (e renderlo una funzione helper
  chiamata da fuori se serve nel SessionDetail).
- **Modello `SessionVote`**: qui c'è una scelta pragmatica:
  - **Opzione A (pura)**: spostare il modello in `apps/tasks/murder_mystery/models.py`.
    Richiede Django data migration: nuova tabella sotto app `tasks_murder_mystery`,
    copia dati, drop vecchia tabella. Lavoro non banale.
  - **Opzione B (pragmatica, RACCOMANDATA)**: lasciare la tabella fisica nello
    schema `sessions` (zero migration dati), ma **spostare le Python class in
    `apps/tasks/murder_mystery/models.py` usando `Meta.app_label = "sessions"`**.
    Nessuna data migration, nessun cambio di tabella. Il core `apps/sessions`
    smette di definire il modello e di importarlo. L'unico punto che lo importa
    è il MurderMysteryTask plugin. Regola "core non sa nulla dei voti" rispettata
    nei fatti (nessun import di SessionVote da fuori `apps/tasks/murder_mystery/`).
  - **Scelgo B** salvo parere contrario dell'utente.
- URL `/api/sessions/<id>/vote/` e `/vote-status/`: registrate dentro
  `apps/tasks/murder_mystery/urls.py`, incluse in `aiutami/urls.py` sotto prefisso
  `api/tasks/murder-mystery/sessions/<id>/...` (nuovo contratto API). Il vecchio
  path può essere mantenuto come alias per transizione frontend, oppure rimosso
  visto che il frontend va comunque risincronizzato.
- `sessions/services.py:close_session`: attesa "tutti hanno votato" diventa
  `task.all_submissions_received(session)`.
- **Verifica**: tutti i test di `SessionVoteModelTests` e `VoteEndpointTests`
  passano, migrati in `apps/tasks/murder_mystery/tests/`.

### Step 7 — Creazione del task GENERIC

- `apps/tasks/generic/task.py`: `GenericTask(TaskDefinition)`:
  - `key="generic"`, `display_name="Discussione generica"`
  - `min_participants=2`, `max_participants=8`, `fixed_size=False`
  - `task_context_block(mode)` ritorna `""` (scheletro core basta)
  - `llm_scenario_payload()` ritorna `{}` o dict minimale
  - `intro_message_tail()` ritorna `""` (fine intro dopo "Buona discussione!")
  - `requires_submission=False`
  - `all_submissions_received()` ritorna sempre `True`
  - `submission_urls()` ritorna `None`
  - `fallback_forced_conclusion_body()` ritorna solo riassunto + ringraziamento,
    nessuna istruzione di voto
  - `report_title()` = "Report sessione"
  - `build_report_llm_prompt()` ritorna prompt generico (riassunto qualitativo
    della discussione, partecipazione equilibrata, temi emersi)
  - `build_report_pdf_sections()` ritorna `[]`
- Test end-to-end: creare sessione GENERIC con 3 partecipanti, discussione fake,
  transizione in CONCLUSION → sessione chiude automaticamente senza aspettare
  voti.
- **Verifica**: GENERIC funziona. MM continua identico.

### Step 8 — Creazione del task NASA_MOON_SURVIVAL

- `apps/tasks/nasa_moon/config.py`: costanti con i 15 item e l'expert ranking
  (verbatim dai PDF in `docs/nasa_moon_survival/`). Segnalare l'incoerenza
  interna del PDF (water/oxygen, vedi MEMORY.md 2026-04-08) con un commento.
- `apps/tasks/nasa_moon/prompts.py`:
  - `SCENARIO_BLOCK_NORMAL`: descrive lo scenario "stranded on moon" e le 6
    procedural ground rules di Hall & Watson 1970 come regole che il moderatore
    deve enforceare.
  - `SCENARIO_BLOCK_FORCED_SUMMARY`: ricapitolazione orientata alle ground rules.
  - `SCENARIO_BLOCK_FORCED_CONCLUSION`: invito a sottomettere il ranking finale.
- `apps/tasks/nasa_moon/models.py`: `NasaRanking(participant, ranked_items: JSONField)`.
- `apps/tasks/nasa_moon/views.py`: `NasaRankingView` (POST lista ordinata di 15 item),
  `NasaRankingStatusView` (stato submission di gruppo).
- `apps/tasks/nasa_moon/report.py`:
  - Scoring vs expert (somma differenze assolute)
  - PDF section con tabella: item / team rank / expert rank / diff
- `NasaMoonTask(TaskDefinition)`:
  - `min_participants=3`, `max_participants=6`, `fixed_size=False`
  - `requires_submission=True`
  - `all_submissions_received()`: tutti i participant hanno una NasaRanking
- Migration per tabella `tasks_nasa_moon_nasaranking`.
- Test: submission validation (lista di 15, no duplicati, solo item validi),
  scoring.

### Step 9 — Pulizie finali e documentazione

- Rimuovere costanti MM ormai morte dal core (se ne restano).
- Aggiornare `CLAUDE.md` §"Repository Structure" con la nuova app `tasks`.
- Scrivere `apps/tasks/README.md` breve: come creare un nuovo task.
- Aggiornare `docs/specs/` se esistono spec che citano MM-specifico.
- Aggiornare il contratto API per il frontend (file separato tipo
  `docs/frontend-api-contract.md`): i 3 task_key validi, gli endpoint submission
  per task, cosa attendere in CONCLUSION per ciascun task.

---

## 6. Test: cosa aggiornare e aggiungere

### Aggiornamenti

- Tutti i test che creano sessioni hardcoded `context=SessionContext.MURDER_MYSTERY`
  passano alla stringa `"murder_mystery"`.
- `VoteEndpointTests` e `SessionVoteModelTests` migrano sotto
  `apps/tasks/murder_mystery/tests/`.
- `ReportPDFServiceTests` e `ReportLLMServiceTests` vengono splittati:
  parte generica resta in `apps/reports/tests.py`, parte MM-specifica si sposta.

### Nuovi test

1. `apps/tasks/tests/test_registry.py` — register, get, unknown key raises.
2. `apps/tasks/tests/test_base_contract.py` — ogni task registrato implementa
   tutti i metodi astratti e ritorna tipi coerenti.
3. `apps/tasks/tests/test_prompt_composition.py` — verifica che il prompt finale
   per MM contenga il blocco task MM, per GENERIC non lo contenga, per NASA
   contenga le ground rules.
4. `apps/tasks/generic/tests/test_generic_lifecycle.py` — end-to-end con
   sessione generic: crea, start, active, conclusion, close (senza submission).
5. `apps/tasks/nasa_moon/tests/` — submission validation, scoring,
   all_submissions_received, report sections.
6. `apps/tasks/murder_mystery/tests/` — suite migrata dai test sessions/reports.

### Test di non-regressione critici (Murder Mystery)

Prima di Step 1 e alla fine di ogni step, eseguire:
- `apps/sessions/tests.py` → tutto verde
- `apps/moderation/tests.py tests_integration.py tests_intro.py` → tutto verde
- `apps/reports/tests.py` → tutto verde
- Un test end-to-end manuale: creare sessione MM, 3 partecipanti, completare
  turni, votare, chiudere, scaricare PDF. Il PDF deve essere equivalente a
  quello pre-refactor (titolo, sezione voti, summary).

---

## 7. Criteri di accettazione (definition of done)

Il refactor è finito quando **tutti** i seguenti sono veri:

1. Esiste `apps/tasks/` con `base.py`, `registry.py`, e 3 sottopacchetti
   `generic/`, `murder_mystery/`, `nasa_moon/`, ognuno registrato al boot Django.
2. Nessun file sotto `apps/sessions/`, `apps/moderation/`, `apps/reports/`,
   `apps/turns/`, `apps/asr/`, `apps/tts/`, `apps/webrtc/` contiene le stringhe
   `"murder_mystery"`, `"Eddie"`, `"Mickey"`, `"Billy"`, `"colpevole"`,
   `"assassino"`, `"suspects"`, `"indizi"`, `"MURDER_MYSTERY"`. Verificabile con
   `grep -r` (escludendo commenti storici o docstring di contesto).
3. Nessun import da `apps.tasks.<specific>` fuori da `apps/tasks/` stesso.
   Verificabile con grep su `from apps.tasks.murder_mystery`,
   `from apps.tasks.nasa_moon`, `from apps.tasks.generic`.
4. `Session.context` accetta solo le 3 chiavi registrate nel registry. Tentare
   di creare una sessione con `context="foo"` restituisce 400.
5. Il comportamento di Murder Mystery è identico a prima del refactor:
   - Vincolo 3/3 funziona
   - Flow voto (POST + status) funziona
   - Moderatore LLM riceve lo stesso payload scenario e produce messaggi di
     qualità equivalente (prompt finali contengono ancora le parti MM)
   - Intro message identico
   - Report PDF contiene titolo "REPORT SESSIONE MURDER MYSTERY" e sezione voti
6. GENERIC funziona end-to-end: creazione, lobby, active, conclusion (moderatore
   fa riassunto via `call_llm_for_conclusion`), close automatico senza attendere
   input. Nessun riferimento a voting nel PDF finale.
7. NASA_MOON_SURVIVAL funziona end-to-end: creazione con 3-6 partecipanti,
   active, conclusion, ogni participant sottomette ranking di 15 item, report
   contiene scoring vs expert.
8. Suite test completa passa (`make test`).
9. Aggiungere un 4° task fittizio di prova richiede: creare una cartella in
   `apps/tasks/`, implementare `TaskDefinition`, registrare nel registry.
   **Zero cambiamenti al codice core.** Questo è il test architetturale finale.
10. `CLAUDE.md` aggiornato.

---

## 8. Rischi e mitigazioni

| Rischio | Mitigazione |
|---------|-------------|
| Rompere MM durante il refactor | Step incrementali con test verdi ad ogni commit; test di non-regressione manuali end-to-end dopo step 3, 6, 9 |
| Migration DB complicata spostando SessionVote | Opzione B (pragmatica): solo classi Python si spostano, tabella fisica resta — zero data migration |
| Propagare `task_key` a troppi call site | Usare `session.context` come single source of truth, passare `session` anziché `task_key` dove possibile |
| Prompt MM attualmente distribuiti tra 4 metodi (normal, forced_summary, forced_conclusion, _build_forced_summary_prompt duplicato) | Approfittare del refactor per chiarire: c'è un duplicato sospetto tra `_build_forced_summary_system_prompt` (riga 656) e `_build_forced_summary_prompt` (riga 811). Da indagare in Step 3 |
| Frontend disallineato su DESERT_SURVIVAL/BRAINSTORMING | Affrontato in parallelo nella repo frontend dopo il completamento del backend. Fornire contratto API chiaro come deliverable del refactor |
| NASA ground rules non ancora consolidate come prompt | Step 8 può essere rimandato/iterato dopo approvazione prof Garzotto. Step 1-7 (MM + GENERIC) bastano a chiudere il refactor architetturale |

---

## 9. Cosa NON è incluso in questo piano

- **Frontend**: risincronizzazione contratti e rimozione BRAINSTORMING — lavoro
  separato sulla repo frontend.
- **Deploy HTTPS produzione**: rimandato post-refactor (vedi MEMORY.md).
- **Prompt NASA finali basati su Hall & Watson 1970**: lo Step 8 prevede una
  versione iniziale, ma il contenuto testuale esatto delle 6 ground rules nei
  prompt va rifinito dopo approvazione prof.
- **Valutazione empirica**: pre-registrazione, design sperimentale, recruiting.
- **Trigger temporali "rivisti"**: analisi fatta (§3.5), conclusione = sono già
  tutti generici, non richiedono modifica per supportare GENERIC/NASA.

---

## 10. Decisioni confermate (2026-04-08)

1. **SessionVote**: Opzione **A pura**. Nuova tabella dentro l'app
   `apps/tasks/murder_mystery/` (es. `tasks_murder_mystery_sessionvote`),
   data migration che copia le righe dalla vecchia tabella `session_vote`,
   drop della vecchia tabella. Lo Step 6 include la migration con verifica
   dei conteggi pre/post.
2. **API URLs**: breaking change diretto. I path vote passano a
   `/api/tasks/murder-mystery/sessions/<id>/vote/` (e `/vote-status/`).
   Nessun alias di compatibilità perché il frontend viene riscritto da zero.
3. **Codice morto in `moderation/service.py`**: durante lo Step 3, se `grep`
   conferma che `_build_forced_summary_prompt` (riga 811) non è chiamato da
   nessuna parte, viene rimosso. Se invece risulta usato, si indaga prima
   di toccarlo.
