# Individual Ranking Collection — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare la raccolta del ranking individuale pre-discussione per i task NASA Moon Survival e Lost at Sea, abilitando il calcolo di `synergy_gain` e `assembly_bonus` nel report empirico.

**Architecture:** Nuovo stato `INDIVIDUAL_RANKING` nella state machine di `Session`, deciso dal task plugin via `TaskDefinition.requires_individual_ranking_phase()`. Due nuovi modelli paralleli (`NasaIndividualRanking`, `LostAtSeaIndividualRanking`) con autosave (PUT continuo a ogni drag-and-drop) e submit esplicito. Timer 8 minuti con finalizzazione idempotente triggerata da tre percorsi (tutti submit, lazy check, frontend setTimeout). Backend agnostico: il core di `apps/sessions` non importa mai da `apps/tasks/<specifico>`.

**Tech Stack:** Django 5 + Django REST Framework, PostgreSQL 16, Channels (WebSocket), pytest via `manage.py test`, Docker Compose per esecuzione locale.

**Spec di riferimento:** `docs/plans/2026-05-06-individual-ranking-collection-design.md`.

---

## File Structure

### Nuovi file
- `apps/tasks/individual_ranking.py` — funzione `_finalize_individual_ranking_phase(session)` (livello core, agnostico ai task specifici).
- `apps/tasks/nasa_moon/migrations/0006_nasa_individual_ranking.py` (numero esatto da `makemigrations`).
- `apps/tasks/nasa_moon/tests/__init__.py` se non esiste.
- `apps/tasks/nasa_moon/tests/test_individual_ranking.py` — test endpoint NASA + finalize.
- `apps/tasks/lost_at_sea/migrations/0002_lost_at_sea_individual_ranking.py` (numero esatto da `makemigrations`).
- `apps/tasks/lost_at_sea/tests/__init__.py` se non esiste.
- `apps/tasks/lost_at_sea/tests/test_individual_ranking.py` — test endpoint LAS + finalize.
- `apps/sessions/migrations/00XX_add_individual_ranking_state.py` — aggiunge enum + campo Session.
- `apps/tasks/tests/test_individual_ranking_phase.py` — test transizione di stato (regression generic/MM).

### File modificati
- `apps/tasks/base.py` — 5 nuovi metodi opzionali su `TaskDefinition`.
- `apps/tasks/nasa_moon/task.py` — override 5 metodi.
- `apps/tasks/lost_at_sea/task.py` — override 5 metodi.
- `apps/tasks/nasa_moon/models.py` — `+ NasaIndividualRanking`.
- `apps/tasks/lost_at_sea/models.py` — `+ LostAtSeaIndividualRanking`.
- `apps/tasks/nasa_moon/views.py` — `+ NasaIndividualRankingView`, `NasaIndividualRankingSubmitView`, `NasaIndividualRankingFinalizeView`.
- `apps/tasks/lost_at_sea/views.py` — speculare.
- `apps/tasks/nasa_moon/urls.py` — `+ 3 path entry`.
- `apps/tasks/lost_at_sea/urls.py` — speculare.
- `apps/tasks/nasa_moon/report.py` — `collect_nasa_report_context()` popola synergy_gain + `build_nasa_pdf_sections()` rimuove placeholder + prompt LLM rimuove postilla.
- `apps/tasks/lost_at_sea/report.py` — speculare.
- `apps/sessions/models.py` — `+ INDIVIDUAL_RANKING` in `SessionState`, `+ individual_ranking_started_at`, modifica `Session.start()`.
- `apps/sessions/serializers.py` — `SessionStartSerializer.save()` con `update_fields` adattivo + payload `SessionEvent` differenziato.
- `apps/sessions/views.py` — `SessionStartView` con side-effects condizionali (no `TurnManager.set_introducing` / `set_intro_pending` / `mark_session_started` in fase `INDIVIDUAL_RANKING`).

---

## Comando standard di test

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.tasks.tests \
  apps.tasks.nasa_moon.tests \
  apps.tasks.lost_at_sea.tests \
  apps.sessions.tests \
  apps.reports.tests \
  apps.moderation.tests \
  apps.moderation.tests_integration \
  apps.moderation.tests_intro \
  apps.turns.tests_services
```

I 237+ test esistenti devono restare verdi a ogni commit. Comando rapido (solo nuovi test) segnalato in ciascun task.

---

## Task 1: Estendere `TaskDefinition` con i 5 nuovi metodi opzionali

**Files:**
- Modify: `apps/tasks/base.py` (in fondo alla classe `TaskDefinition`, prima di `__repr__`)
- Test: `apps/tasks/tests/test_base.py` (nuovo file se non esiste)

- [ ] **Step 1: Verifica esistenza tests file di base**

```bash
ls apps/tasks/tests/test_base.py 2>&1
```

Se non esiste, crearlo nel passo successivo. Se esiste, estenderlo.

- [ ] **Step 2: Scrivi i test failing**

Crea (o estende) `apps/tasks/tests/test_base.py` con:

```python
"""Test default behavior dei nuovi metodi opzionali su TaskDefinition."""

from django.test import SimpleTestCase

from apps.tasks.base import TaskDefinition


class _StubTask(TaskDefinition):
    """Stub minimale per testare i default."""

    @property
    def key(self) -> str:
        return "_stub"

    @property
    def display_name(self) -> str:
        return "Stub"

    @property
    def min_participants(self) -> int:
        return 2

    @property
    def max_participants(self) -> int:
        return 4

    @property
    def fixed_size(self) -> bool:
        return False


class TaskDefinitionIndividualRankingDefaultsTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = _StubTask()

    def test_requires_individual_ranking_phase_default_false(self) -> None:
        self.assertFalse(self.task.requires_individual_ranking_phase())

    def test_individual_ranking_duration_seconds_default_480(self) -> None:
        self.assertEqual(self.task.individual_ranking_duration_seconds(), 480)

    def test_individual_ranking_model_default_none(self) -> None:
        self.assertIsNone(self.task.individual_ranking_model())

    def test_default_individual_ranking_default_empty(self) -> None:
        self.assertEqual(self.task.default_individual_ranking(), [])

    def test_expected_items_set_default_empty(self) -> None:
        self.assertEqual(self.task.expected_items_set(), set())
```

- [ ] **Step 3: Verifica che i test falliscano**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_base -v 2
```

Atteso: `AttributeError` o test fallimento perché i metodi non esistono ancora.

- [ ] **Step 4: Implementa i 5 metodi opzionali su `TaskDefinition`**

In `apps/tasks/base.py`, dentro la classe `TaskDefinition`, aggiungi una nuova sezione **prima** di `__repr__`:

```python
    # --- Fase pre-discussione: ranking individuale ---
    # I task survival (NASA Moon, Lost at Sea) richiedono che ogni
    # partecipante sottometta un ranking individuale prima della discussione
    # di gruppo, per il calcolo del synergy_gain (Hall 1962, Hall & Watson 1970).
    # Default: nessuna fase pre-discussione (generic, murder_mystery).

    def requires_individual_ranking_phase(self) -> bool:
        """True se il task richiede una fase INDIVIDUAL_RANKING tra LOBBY
        e ACTIVE. Default False."""
        return False

    def individual_ranking_duration_seconds(self) -> int:
        """Durata massima della fase INDIVIDUAL_RANKING in secondi. Default
        480 (8 min). Significativo solo se requires_individual_ranking_phase
        è True."""
        return 480

    def individual_ranking_model(self):
        """Classe del modello Django che persiste i ranking individuali per
        questo task. Default None. I task con fase pre-discussione devono
        ritornare la classe concreta (es. NasaIndividualRanking)."""
        return None

    def default_individual_ranking(self) -> list[str]:
        """Ranking di default (lista ordinata di item) usato per partecipanti
        che non hanno mai toccato la pagina alla scadenza del timer.
        Default lista vuota."""
        return []

    def expected_items_set(self) -> set[str]:
        """Set di item validi attesi nel ranking individuale (validazione PUT).
        Default set vuoto."""
        return set()
```

- [ ] **Step 5: Verifica che i test passino**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_base -v 2
```

Atteso: tutti i test passano.

- [ ] **Step 6: Smoke test sui test esistenti**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests apps.sessions.tests --noinput
```

Atteso: tutti verdi (i nuovi metodi sono additivi e i task esistenti ereditano i default no-op).

- [ ] **Step 7: Commit**

```bash
git add apps/tasks/base.py apps/tasks/tests/test_base.py
git commit -m "feat(tasks): add individual ranking phase hooks to TaskDefinition

- 5 nuovi metodi opzionali con default no-op
- requires_individual_ranking_phase, individual_ranking_duration_seconds
- individual_ranking_model, default_individual_ranking, expected_items_set
- I task esistenti (generic, MM, NASA, LAS) ereditano i default e non cambiano comportamento"
```

---

## Task 2: Override su `NasaMoonTask` e `LostAtSeaTask`

I metodi che ritornano la classe model e i model stessi non esistono ancora — ritorniamo `None` per ora e li popoleremo nel Task 5/6. I metodi `requires_individual_ranking_phase`, `default_individual_ranking`, `expected_items_set` invece possono essere implementati subito.

**Files:**
- Modify: `apps/tasks/nasa_moon/task.py`
- Modify: `apps/tasks/lost_at_sea/task.py`
- Test: `apps/tasks/tests/test_nasa_moon.py` (estensione)
- Test: `apps/tasks/tests/test_lost_at_sea.py` (estensione)

- [ ] **Step 1: Scrivi test failing per NASA**

Aggiungi alla fine di `apps/tasks/tests/test_nasa_moon.py`:

```python
# ---------------------------------------------------------------------------
# Individual ranking phase
# ---------------------------------------------------------------------------

class NasaMoonIndividualRankingHooksTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("nasa_moon_survival")

    def test_requires_individual_ranking_phase(self) -> None:
        self.assertTrue(self.task.requires_individual_ranking_phase())

    def test_default_duration_seconds(self) -> None:
        self.assertEqual(self.task.individual_ranking_duration_seconds(), 480)

    def test_default_individual_ranking_is_nasa_items(self) -> None:
        self.assertEqual(self.task.default_individual_ranking(), list(NASA_ITEMS))

    def test_expected_items_set_is_nasa_items_set(self) -> None:
        self.assertEqual(self.task.expected_items_set(), set(NASA_ITEMS))
```

- [ ] **Step 2: Scrivi test failing per LAS**

Aggiungi a `apps/tasks/tests/test_lost_at_sea.py`:

```python
class LostAtSeaIndividualRankingHooksTests(SimpleTestCase):
    def setUp(self) -> None:
        self.task = get_task("lost_at_sea")

    def test_requires_individual_ranking_phase(self) -> None:
        self.assertTrue(self.task.requires_individual_ranking_phase())

    def test_default_duration_seconds(self) -> None:
        self.assertEqual(self.task.individual_ranking_duration_seconds(), 480)

    def test_default_individual_ranking_is_las_items(self) -> None:
        self.assertEqual(self.task.default_individual_ranking(), list(LOST_AT_SEA_ITEMS))

    def test_expected_items_set_is_las_items_set(self) -> None:
        self.assertEqual(self.task.expected_items_set(), set(LOST_AT_SEA_ITEMS))
```

Verifica che le import necessarie siano già presenti (`from apps.tasks.lost_at_sea.config import LOST_AT_SEA_ITEMS`); aggiungile se mancano.

- [ ] **Step 3: Verifica che i test falliscano**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_nasa_moon apps.tasks.tests.test_lost_at_sea -v 2
```

Atteso: i nuovi test falliscono (default ritorna False/[]/set()), il resto passa.

- [ ] **Step 4: Implementa override su `NasaMoonTask`**

In `apps/tasks/nasa_moon/task.py`, **prima della sezione "--- Submission ---"** (riga ~177), aggiungi:

```python
    # --- Individual ranking phase ---

    def requires_individual_ranking_phase(self) -> bool:
        return True

    def default_individual_ranking(self) -> list[str]:
        return list(NASA_ITEMS)

    def expected_items_set(self) -> set[str]:
        return set(NASA_ITEMS)

    def individual_ranking_model(self):
        # Import lazy per evitare problemi di app loading
        from .models import NasaIndividualRanking
        return NasaIndividualRanking
```

Nota: `NasaIndividualRanking` non esiste ancora — verrà creato nel Task 5. L'import lazy dentro il metodo evita errori al boot di Django finché il model non esiste; ma il metodo verrà chiamato solo da test/codice dopo il Task 5. Se vuoi fare TDD strict, puoi temporaneamente ritornare `None` qui e abilitare l'import lazy nel Task 5. Per semplicità: scrivi il codice come sopra, il `from .models import` fallirà solo se chiamato — ma noi lo chiameremo dopo il Task 5. **Verifica esplicitamente** che i test del Task 2 NON triggherino l'invocazione di `individual_ranking_model()`.

- [ ] **Step 5: Implementa override su `LostAtSeaTask`**

In `apps/tasks/lost_at_sea/task.py`, **prima della sezione "--- Submission ---"** (riga ~177), aggiungi simmetrico:

```python
    # --- Individual ranking phase ---

    def requires_individual_ranking_phase(self) -> bool:
        return True

    def default_individual_ranking(self) -> list[str]:
        return list(LOST_AT_SEA_ITEMS)

    def expected_items_set(self) -> set[str]:
        return set(LOST_AT_SEA_ITEMS)

    def individual_ranking_model(self):
        from .models import LostAtSeaIndividualRanking
        return LostAtSeaIndividualRanking
```

- [ ] **Step 6: Verifica che i test passino**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_nasa_moon apps.tasks.tests.test_lost_at_sea -v 2
```

Atteso: tutti verdi (i 4 nuovi test per task passano, ed evitano `individual_ranking_model()`).

- [ ] **Step 7: Smoke test completo**

```bash
docker compose run --rm web python manage.py test apps.tasks --noinput
```

Atteso: tutti verdi.

- [ ] **Step 8: Commit**

```bash
git add apps/tasks/nasa_moon/task.py apps/tasks/lost_at_sea/task.py \
        apps/tasks/tests/test_nasa_moon.py apps/tasks/tests/test_lost_at_sea.py
git commit -m "feat(tasks): NASA Moon and Lost at Sea opt into individual ranking phase

- requires_individual_ranking_phase=True, durata 480s
- default_individual_ranking + expected_items_set legati a NASA_ITEMS / LOST_AT_SEA_ITEMS
- individual_ranking_model con import lazy (sarà valido dopo creazione modello)"
```

---

## Task 3: `INDIVIDUAL_RANKING` enum + campo `Session.individual_ranking_started_at`

**Files:**
- Modify: `apps/sessions/models.py`
- Create: `apps/sessions/migrations/00XX_add_individual_ranking_state.py` (numero generato da `makemigrations`)
- Test: `apps/sessions/tests/test_models.py` (estensione, oppure file esistente — verifica con `ls apps/sessions/tests/`)

- [ ] **Step 1: Verifica struttura test sessions**

```bash
ls apps/sessions/tests/ 2>&1
find apps/sessions -name "test*.py" | head -5
```

Identifica il file dove vivono i test di `Session` model (probabilmente `apps/sessions/tests.py` o `tests/test_models.py`).

- [ ] **Step 2: Scrivi test failing**

Aggiungi al file di test appropriato:

```python
from apps.sessions.models import Session, SessionState


class SessionStateEnumTests(SimpleTestCase):
    def test_individual_ranking_state_exists(self) -> None:
        self.assertEqual(SessionState.INDIVIDUAL_RANKING, "INDIVIDUAL_RANKING")

    def test_individual_ranking_in_choices(self) -> None:
        labels = dict(SessionState.choices)
        self.assertIn("INDIVIDUAL_RANKING", labels)


class SessionIndividualRankingStartedAtTests(TestCase):
    def test_field_exists_and_nullable(self) -> None:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        host = User.objects.create_user(username="host_t3", password="x")
        session = Session.objects.create(
            title="T",
            context="generic",
            min_size=2, max_size=4,
            host=host,
        )
        self.assertIsNone(session.individual_ranking_started_at)
```

Sostituisci `"generic"` con un task valido nel registry se quello fallisce per validazione.

- [ ] **Step 3: Verifica che i test falliscano**

```bash
docker compose run --rm web python manage.py test apps.sessions -v 2 -k IndividualRanking
```

Atteso: AttributeError o errore enum non trovato.

- [ ] **Step 4: Aggiungi `INDIVIDUAL_RANKING` a `SessionState`**

In `apps/sessions/models.py`, modifica la classe `SessionState`:

```python
class SessionState(models.TextChoices):
    LOBBY = "LOBBY", "Lobby"
    INDIVIDUAL_RANKING = "INDIVIDUAL_RANKING", "Individual ranking"
    ACTIVE = "ACTIVE", "Active"
    CONCLUSION = "CONCLUSION", "Conclusion"
    CLOSED = "CLOSED", "Closed"
```

- [ ] **Step 5: Aggiungi il campo `individual_ranking_started_at` a `Session`**

In `apps/sessions/models.py`, dentro la classe `Session`, **dopo `started_at`**:

```python
    started_at = models.DateTimeField(null=True, blank=True)
    individual_ranking_started_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp di inizio fase INDIVIDUAL_RANKING. NULL per "
                  "sessioni senza questa fase. Usato per calcolo timer 8 min.",
    )
    conclusion_at = models.DateTimeField(null=True, blank=True)
```

- [ ] **Step 6: Genera la migration**

```bash
docker compose run --rm web python manage.py makemigrations ai_sessions
```

Atteso: una nuova migration creata in `apps/sessions/migrations/` (es. `0006_session_individual_ranking_started_at_and_more.py`). Verifica che contenga sia `AlterField(state, choices=...)` sia `AddField(individual_ranking_started_at)`.

- [ ] **Step 7: Applica la migration**

```bash
docker compose run --rm web python manage.py migrate
```

- [ ] **Step 8: Verifica che i test passino**

```bash
docker compose run --rm web python manage.py test apps.sessions -v 2 -k IndividualRanking
```

Atteso: verdi.

- [ ] **Step 9: Smoke test**

```bash
docker compose run --rm web python manage.py test apps.sessions --noinput
```

Atteso: tutti verdi.

- [ ] **Step 10: Commit**

```bash
git add apps/sessions/models.py apps/sessions/migrations/ apps/sessions/tests/
git commit -m "feat(sessions): add INDIVIDUAL_RANKING state and individual_ranking_started_at field

- Nuovo stato enum INDIVIDUAL_RANKING tra LOBBY e ACTIVE
- Campo Session.individual_ranking_started_at (nullable) per timer 8 min
- Migration backward-compatible (sessioni esistenti hanno NULL)"
```

---

## Task 4: Modifica `Session.start()` + `SessionStartSerializer.save()` + `SessionStartView`

**Files:**
- Modify: `apps/sessions/models.py:143-150` (`Session.start()`)
- Modify: `apps/sessions/serializers.py:218-230` (`SessionStartSerializer.save()`)
- Modify: `apps/sessions/views.py:96-119` (`SessionStartView`)
- Test: `apps/tasks/tests/test_individual_ranking_phase.py` (nuovo)

- [ ] **Step 1: Scrivi i test failing**

Crea `apps/tasks/tests/test_individual_ranking_phase.py`:

```python
"""Test transizione di stato LOBBY -> INDIVIDUAL_RANKING / ACTIVE in base al task plugin.
Verifica il routing del Session.start e la regression per task senza fase pre-discussione.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.sessions.models import (
    Session, SessionParticipant, SessionState, ParticipantRole,
)

User = get_user_model()


def _create_lobby_session(host, context: str, min_size: int, max_size: int) -> Session:
    session = Session.objects.create(
        title=f"T-{context}",
        context=context,
        min_size=min_size,
        max_size=max_size,
        host=host,
    )
    SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    return session


def _fill_to_min(session: Session) -> None:
    """Aggiunge altri partecipanti finché non si raggiunge min_size."""
    needed = session.min_size - session.participants.count()
    for i in range(needed):
        u = User.objects.create_user(username=f"p_{session.id}_{i}", password="x")
        SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        )


class IndividualRankingPhaseRoutingTests(TestCase):
    def setUp(self) -> None:
        self.host = User.objects.create_user(username="host_p", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.host)

    def test_nasa_moon_starts_in_individual_ranking(self) -> None:
        session = _create_lobby_session(self.host, "nasa_moon_survival", 3, 6)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.INDIVIDUAL_RANKING)
        self.assertIsNotNone(session.individual_ranking_started_at)
        self.assertIsNone(session.started_at)

    def test_lost_at_sea_starts_in_individual_ranking(self) -> None:
        session = _create_lobby_session(self.host, "lost_at_sea", 3, 6)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.INDIVIDUAL_RANKING)
        self.assertIsNotNone(session.individual_ranking_started_at)

    def test_generic_starts_in_active(self) -> None:
        session = _create_lobby_session(self.host, "generic", 2, 8)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.ACTIVE)
        self.assertIsNotNone(session.started_at)
        self.assertIsNone(session.individual_ranking_started_at)

    def test_murder_mystery_starts_in_active(self) -> None:
        session = _create_lobby_session(self.host, "murder_mystery", 3, 3)
        _fill_to_min(session)
        resp = self.client.post(f"/api/sessions/{session.id}/start/", data={})
        self.assertEqual(resp.status_code, 200, resp.json())
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.ACTIVE)
        self.assertIsNotNone(session.started_at)
        self.assertIsNone(session.individual_ranking_started_at)
```

- [ ] **Step 2: Verifica che i test falliscano**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_individual_ranking_phase -v 2
```

Atteso: i due test NASA/LAS falliscono (oggi vanno a ACTIVE), i due test generic/MM passano già.

- [ ] **Step 3: Modifica `Session.start()`**

In `apps/sessions/models.py`, sostituisci il metodo `start()`:

```python
    def start(self):
        # Transizione LOBBY -> INDIVIDUAL_RANKING (per task survival) o ACTIVE.
        if self.state != SessionState.LOBBY:
            raise ValidationError("La sessione non è in stato LOBBY.")
        if self.participants_count < self.min_size:
            raise ValidationError("Numero minimo di partecipanti non raggiunto.")

        from apps.tasks.registry import get_task
        task = get_task(self.context)

        if task.requires_individual_ranking_phase():
            self.state = SessionState.INDIVIDUAL_RANKING
            self.individual_ranking_started_at = timezone.now()
            # started_at resta NULL: verrà impostato quando si transita ad ACTIVE
            # in _finalize_individual_ranking_phase()
        else:
            self.state = SessionState.ACTIVE
            self.started_at = timezone.now()
```

- [ ] **Step 4: Modifica `SessionStartSerializer.save()`**

In `apps/sessions/serializers.py`, sostituisci `save()` di `SessionStartSerializer`:

```python
    @transaction.atomic
    def save(self, **kwargs: Any) -> Session:
        session: Session = self.instance
        session.start()
        session.full_clean()

        if session.state == SessionState.INDIVIDUAL_RANKING:
            from datetime import timedelta
            from apps.tasks.registry import get_task
            session.save(update_fields=["state", "individual_ranking_started_at"])
            task = get_task(session.context)
            deadline = session.individual_ranking_started_at + timedelta(
                seconds=task.individual_ranking_duration_seconds()
            )
            SessionEvent.objects.create(
                session=session,
                type=SessionEventType.STARTED,
                actor=self.context["request"].user,
                payload={
                    "phase": "INDIVIDUAL_RANKING",
                    "individual_ranking_started_at": session.individual_ranking_started_at.isoformat(),
                    "phase_deadline_at": deadline.isoformat(),
                },
            )
        else:
            session.save(update_fields=["state", "started_at"])
            SessionEvent.objects.create(
                session=session,
                type=SessionEventType.STARTED,
                actor=self.context["request"].user,
                payload={"started_at": timezone.now().isoformat()},
            )
        return session
```

- [ ] **Step 5: Modifica `SessionStartView`**

In `apps/sessions/views.py`, individua `SessionStartView.post` (intorno a riga 96). I side-effects `TurnManager.set_introducing`, `set_intro_pending`, `mark_session_started` sono specifici di ACTIVE (preparano il loop turn-taking + intro del moderatore). In INDIVIDUAL_RANKING NON vanno chiamati. Modifica così:

```python
        serializer.is_valid(raise_exception=True)
        session = serializer.save()

        # Side-effects specifici di ACTIVE: preparazione turn-taking + intro
        # moderatore. NON eseguiti se la sessione è entrata in INDIVIDUAL_RANKING:
        # quei side-effects verranno eseguiti dalla finalize della fase
        # individuale (apps/tasks/individual_ranking.py) quando si transita
        # finalmente ad ACTIVE.
        if session.state == SessionState.ACTIVE:
            TurnManager.set_introducing(session_id=str(session.id))
            set_intro_pending(session_id=str(session.id))
            mark_session_started(session_id=session.id)

        detail_data = SessionDetailSerializer(
            session,
            context={"request": request},
        ).data

        _broadcast_session_event(
            session_id=str(session.id),
            event_type="STATE_CHANGED",
            payload=detail_data,
        )

        return Response(detail_data, status=status.HTTP_200_OK)
```

(Mantieni il resto del metodo invariato.)

- [ ] **Step 6: Verifica che i test del Task 4 passino**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_individual_ranking_phase -v 2
```

Atteso: 4 test verdi.

- [ ] **Step 7: Smoke test completo (regression critica)**

```bash
docker compose run --rm web python manage.py test apps.sessions apps.tasks apps.moderation apps.turns --noinput
```

Atteso: tutti verdi. **Se test esistenti per il start fallisco**, verifica che si aspettino state=ACTIVE per task non-survival; quelli per NASA/LAS che si aspettavano state=ACTIVE devono essere aggiornati a state=INDIVIDUAL_RANKING (ma in genere i test esistenti usano `generic` o `murder_mystery` per il flow di start).

- [ ] **Step 8: Commit**

```bash
git add apps/sessions/models.py apps/sessions/serializers.py apps/sessions/views.py \
        apps/tasks/tests/test_individual_ranking_phase.py
git commit -m "feat(sessions): route Start to INDIVIDUAL_RANKING for survival tasks

- Session.start() consulta task.requires_individual_ranking_phase()
- SessionStartSerializer.save() con update_fields adattivo + payload SessionEvent differenziato
- SessionStartView salta TurnManager/intro/mark_started in fase INDIVIDUAL_RANKING
- Test transizione (NASA, LAS, generic, MM)"
```

---

## Task 5: Modello `NasaIndividualRanking`

**Files:**
- Modify: `apps/tasks/nasa_moon/models.py`
- Create: `apps/tasks/nasa_moon/migrations/0006_nasa_individual_ranking.py` (numero da `makemigrations`)
- Test: `apps/tasks/nasa_moon/tests/__init__.py` (vuoto, se non esiste)
- Test: `apps/tasks/nasa_moon/tests/test_individual_ranking.py` (nuovo, parziale — solo modello)

- [ ] **Step 1: Crea cartella tests se non esiste**

```bash
ls apps/tasks/nasa_moon/tests/ 2>&1 || mkdir -p apps/tasks/nasa_moon/tests
test -f apps/tasks/nasa_moon/tests/__init__.py || touch apps/tasks/nasa_moon/tests/__init__.py
```

- [ ] **Step 2: Scrivi test failing del modello**

Crea `apps/tasks/nasa_moon/tests/test_individual_ranking.py`:

```python
"""Test endpoint + modello NasaIndividualRanking.

Suddiviso in classi:
- ModelTests: schema, constraint unicità.
- ViewTests: GET/PUT/POST submit/POST finalize-if-expired (futuri task).
"""

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from apps.sessions.models import Session, SessionParticipant, ParticipantRole
from apps.tasks.nasa_moon.config import NASA_ITEMS

User = get_user_model()


def _make_session(context: str = "nasa_moon_survival") -> tuple[Session, list[SessionParticipant]]:
    host = User.objects.create_user(username=f"h_{context}", password="x")
    session = Session.objects.create(
        title="T", context=context, min_size=3, max_size=6, host=host,
    )
    p_host = SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    others = []
    for i in range(2):
        u = User.objects.create_user(username=f"u_{context}_{i}", password="x")
        others.append(SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        ))
    return session, [p_host, *others]


class NasaIndividualRankingModelTests(TestCase):
    def test_create_and_defaults(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        session, participants = _make_session()
        r = NasaIndividualRanking.objects.create(
            session=session,
            participant=participants[0],
            ranked_items=list(NASA_ITEMS),
        )
        self.assertFalse(r.is_submitted)
        self.assertIsNotNone(r.created_at)
        self.assertEqual(r.ranked_items, list(NASA_ITEMS))

    def test_unique_session_participant(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        session, participants = _make_session()
        NasaIndividualRanking.objects.create(
            session=session, participant=participants[0],
            ranked_items=list(NASA_ITEMS),
        )
        with self.assertRaises(IntegrityError):
            NasaIndividualRanking.objects.create(
                session=session, participant=participants[0],
                ranked_items=list(NASA_ITEMS),
            )
```

- [ ] **Step 3: Verifica che i test falliscano**

```bash
docker compose run --rm web python manage.py test apps.tasks.nasa_moon.tests.test_individual_ranking -v 2
```

Atteso: ModuleNotFoundError o ImportError per `NasaIndividualRanking`.

- [ ] **Step 4: Crea il modello**

In `apps/tasks/nasa_moon/models.py`, **alla fine del file**:

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
                  "oppure quando la fase è stata finalizzata."
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

    def __str__(self) -> str:
        return (
            f"NasaIndividualRanking[{self.session_id}/{self.participant_id} "
            f"submitted={self.is_submitted}]"
        )
```

- [ ] **Step 5: Genera la migration**

```bash
docker compose run --rm web python manage.py makemigrations
```

Atteso: nuova migration `0006_nasaindividualranking.py` (o numero successivo) in `apps/tasks/nasa_moon/migrations/`.

- [ ] **Step 6: Applica la migration**

```bash
docker compose run --rm web python manage.py migrate
```

- [ ] **Step 7: Verifica i test del modello**

```bash
docker compose run --rm web python manage.py test apps.tasks.nasa_moon.tests.test_individual_ranking -v 2
```

Atteso: 2 test passano.

- [ ] **Step 8: Smoke test**

```bash
docker compose run --rm web python manage.py test apps.tasks --noinput
```

- [ ] **Step 9: Commit**

```bash
git add apps/tasks/nasa_moon/models.py apps/tasks/nasa_moon/migrations/ \
        apps/tasks/nasa_moon/tests/
git commit -m "feat(tasks/nasa_moon): add NasaIndividualRanking model

- One row per (session, participant) con autosave + is_submitted flag
- UniqueConstraint (session, participant), index su (session, is_submitted)
- ranked_items JSONField, FK a SessionParticipant"
```

---

## Task 6: Modello `LostAtSeaIndividualRanking`

Identico al Task 5 con nomi LAS. Procedi più velocemente, simmetricamente.

**Files:**
- Modify: `apps/tasks/lost_at_sea/models.py`
- Create: `apps/tasks/lost_at_sea/migrations/0002_lost_at_sea_individual_ranking.py`
- Test: `apps/tasks/lost_at_sea/tests/__init__.py` (se non esiste)
- Test: `apps/tasks/lost_at_sea/tests/test_individual_ranking.py` (nuovo)

- [ ] **Step 1: Crea cartella tests**

```bash
ls apps/tasks/lost_at_sea/tests/ 2>&1 || mkdir -p apps/tasks/lost_at_sea/tests
test -f apps/tasks/lost_at_sea/tests/__init__.py || touch apps/tasks/lost_at_sea/tests/__init__.py
```

- [ ] **Step 2: Scrivi test failing**

Crea `apps/tasks/lost_at_sea/tests/test_individual_ranking.py` simmetrico al Task 5:

```python
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from apps.sessions.models import Session, SessionParticipant, ParticipantRole
from apps.tasks.lost_at_sea.config import LOST_AT_SEA_ITEMS

User = get_user_model()


def _make_session() -> tuple[Session, list[SessionParticipant]]:
    host = User.objects.create_user(username="h_las", password="x")
    session = Session.objects.create(
        title="T", context="lost_at_sea", min_size=3, max_size=6, host=host,
    )
    p_host = SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    others = []
    for i in range(2):
        u = User.objects.create_user(username=f"u_las_{i}", password="x")
        others.append(SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        ))
    return session, [p_host, *others]


class LostAtSeaIndividualRankingModelTests(TestCase):
    def test_create_and_defaults(self) -> None:
        from apps.tasks.lost_at_sea.models import LostAtSeaIndividualRanking
        session, participants = _make_session()
        r = LostAtSeaIndividualRanking.objects.create(
            session=session,
            participant=participants[0],
            ranked_items=list(LOST_AT_SEA_ITEMS),
        )
        self.assertFalse(r.is_submitted)
        self.assertIsNotNone(r.created_at)
        self.assertEqual(r.ranked_items, list(LOST_AT_SEA_ITEMS))

    def test_unique_session_participant(self) -> None:
        from apps.tasks.lost_at_sea.models import LostAtSeaIndividualRanking
        session, participants = _make_session()
        LostAtSeaIndividualRanking.objects.create(
            session=session, participant=participants[0],
            ranked_items=list(LOST_AT_SEA_ITEMS),
        )
        with self.assertRaises(IntegrityError):
            LostAtSeaIndividualRanking.objects.create(
                session=session, participant=participants[0],
                ranked_items=list(LOST_AT_SEA_ITEMS),
            )
```

- [ ] **Step 3: Verifica che falliscano**

```bash
docker compose run --rm web python manage.py test apps.tasks.lost_at_sea.tests.test_individual_ranking -v 2
```

- [ ] **Step 4: Crea modello `LostAtSeaIndividualRanking`**

In `apps/tasks/lost_at_sea/models.py`, **alla fine del file**:

```python
class LostAtSeaIndividualRanking(models.Model):
    """Ranking individuale pre-discussione (Lost at Sea).
    Vedi NasaIndividualRanking per la semantica completa.
    """

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        "ai_sessions.Session",
        on_delete=models.CASCADE,
        related_name="lost_at_sea_individual_rankings",
    )
    participant = models.ForeignKey(
        "ai_sessions.SessionParticipant",
        on_delete=models.CASCADE,
        related_name="lost_at_sea_individual_rankings",
    )
    ranked_items = models.JSONField(
        help_text="Lista ordinata dei 15 oggetti (posizione 0 = più importante)."
    )
    is_submitted = models.BooleanField(
        default=False,
        help_text="True quando il partecipante ha confermato esplicitamente, "
                  "oppure quando la fase è stata finalizzata."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "tasks"
        db_table = "tasks_lost_at_sea_individual_ranking"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "participant"],
                name="uniq_lost_at_sea_individual_ranking_per_participant",
            ),
        ]
        indexes = [
            models.Index(fields=["session", "is_submitted"]),
        ]

    def __str__(self) -> str:
        return (
            f"LostAtSeaIndividualRanking[{self.session_id}/{self.participant_id} "
            f"submitted={self.is_submitted}]"
        )
```

- [ ] **Step 5: Migration**

```bash
docker compose run --rm web python manage.py makemigrations
docker compose run --rm web python manage.py migrate
```

- [ ] **Step 6: Verifica test**

```bash
docker compose run --rm web python manage.py test apps.tasks.lost_at_sea.tests -v 2
```

Atteso: tutti verdi.

- [ ] **Step 7: Commit**

```bash
git add apps/tasks/lost_at_sea/models.py apps/tasks/lost_at_sea/migrations/ \
        apps/tasks/lost_at_sea/tests/
git commit -m "feat(tasks/lost_at_sea): add LostAtSeaIndividualRanking model

Speculare a NasaIndividualRanking: stesso schema, stessi vincoli.
Tabella tasks_lost_at_sea_individual_ranking."
```

---

## Task 7: Funzione `_finalize_individual_ranking_phase`

**Files:**
- Create: `apps/tasks/individual_ranking.py`
- Test: `apps/tasks/tests/test_individual_ranking_finalize.py` (nuovo)

- [ ] **Step 1: Scrivi i test failing**

Crea `apps/tasks/tests/test_individual_ranking_finalize.py`:

```python
"""Test della funzione _finalize_individual_ranking_phase (idempotente,
crea righe di default per partecipanti senza ranking, transita ad ACTIVE).
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole

User = get_user_model()


def _make_session_in_individual_ranking() -> tuple[Session, list[SessionParticipant]]:
    host = User.objects.create_user(username="h_fin", password="x")
    session = Session.objects.create(
        title="T", context="nasa_moon_survival", min_size=3, max_size=6,
        host=host, state=SessionState.INDIVIDUAL_RANKING,
        individual_ranking_started_at=timezone.now() - timedelta(seconds=10),
    )
    p_host = SessionParticipant.objects.create(
        session=session, user=host, role=ParticipantRole.HOST,
    )
    others = []
    for i in range(2):
        u = User.objects.create_user(username=f"u_fin_{i}", password="x")
        others.append(SessionParticipant.objects.create(
            session=session, user=u, role=ParticipantRole.PARTICIPANT,
        ))
    return session, [p_host, *others]


class FinalizeIndividualRankingPhaseTests(TestCase):
    def test_transitions_to_active_and_sets_started_at(self) -> None:
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, _ = _make_session_in_individual_ranking()
        result = _finalize_individual_ranking_phase(session)
        session.refresh_from_db()
        self.assertTrue(result)
        self.assertEqual(session.state, SessionState.ACTIVE)
        self.assertIsNotNone(session.started_at)

    def test_creates_default_ranking_for_participants_without_row(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        from apps.tasks.nasa_moon.config import NASA_ITEMS
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, participants = _make_session_in_individual_ranking()
        _finalize_individual_ranking_phase(session)
        rankings = NasaIndividualRanking.objects.filter(session=session)
        self.assertEqual(rankings.count(), 3)
        for r in rankings:
            self.assertTrue(r.is_submitted)
            self.assertEqual(r.ranked_items, list(NASA_ITEMS))

    def test_marks_existing_unsubmitted_as_submitted(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, participants = _make_session_in_individual_ranking()
        custom_items = list(reversed(participants[0].session.context))  # placeholder; vedi sotto
        from apps.tasks.nasa_moon.config import NASA_ITEMS
        custom = list(reversed(NASA_ITEMS))
        NasaIndividualRanking.objects.create(
            session=session, participant=participants[0],
            ranked_items=custom, is_submitted=False,
        )
        _finalize_individual_ranking_phase(session)
        r = NasaIndividualRanking.objects.get(session=session, participant=participants[0])
        self.assertTrue(r.is_submitted)
        # I dati custom sono preservati: la finalize non li sovrascrive
        self.assertEqual(r.ranked_items, custom)

    def test_idempotent_returns_false_on_second_call(self) -> None:
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        session, _ = _make_session_in_individual_ranking()
        first = _finalize_individual_ranking_phase(session)
        second = _finalize_individual_ranking_phase(session)
        self.assertTrue(first)
        self.assertFalse(second)

    def test_returns_false_if_state_not_individual_ranking(self) -> None:
        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        host = User.objects.create_user(username="h_no", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival", min_size=3, max_size=6,
            host=host, state=SessionState.LOBBY,
        )
        result = _finalize_individual_ranking_phase(session)
        self.assertFalse(result)
        session.refresh_from_db()
        self.assertEqual(session.state, SessionState.LOBBY)
```

- [ ] **Step 2: Verifica che falliscano**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_individual_ranking_finalize -v 2
```

Atteso: ImportError per `apps.tasks.individual_ranking`.

- [ ] **Step 3: Crea il modulo**

Crea `apps/tasks/individual_ranking.py`:

```python
"""Finalizzazione della fase INDIVIDUAL_RANKING.

Funzione idempotente che chiude la fase pre-discussione di una sessione e
transita ad ACTIVE. Triggerata da:
1) POST /individual-ranking/submit/ quando l'ultimo partecipante submitta;
2) Lazy check sui PUT/POST quando il timer è scaduto;
3) POST /individual-ranking/finalize-if-expired/ chiamato dal frontend al
   setTimeout 8 min.

La funzione vive nel core (apps.tasks) per restare agnostica al task
specifico: delega a TaskDefinition.individual_ranking_model() e
default_individual_ranking() la conoscenza del modello concreto.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.moderation.intro import set_intro_pending
from apps.moderation.timers_state import mark_session_started
from apps.sessions.models import Session, SessionState
from apps.tasks.registry import get_task
from apps.turns.services import TurnManager


def _finalize_individual_ranking_phase(session: Session) -> bool:
    """Chiude INDIVIDUAL_RANKING e transita ad ACTIVE.

    Idempotente: chiamabile in sicurezza N volte; solo la prima esegue la
    transizione.

    Returns:
        True se la finalizzazione è effettivamente avvenuta in questa chiamata,
        False se la sessione non era in INDIVIDUAL_RANKING (già transizionata
        o stato sbagliato).
    """
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        if session.state != SessionState.INDIVIDUAL_RANKING:
            return False

        task = get_task(session.context)
        Model = task.individual_ranking_model()
        default_items = task.default_individual_ranking()

        if Model is None:
            # Stato inconsistente: fase INDIVIDUAL_RANKING ma il task non
            # espone un modello individuale. Non dovrebbe mai accadere se
            # i task sono configurati correttamente.
            raise RuntimeError(
                f"Task {task.key!r} è in INDIVIDUAL_RANKING ma "
                f"individual_ranking_model() ritorna None."
            )

        for participant in session.participants.all():
            ranking, created = Model.objects.get_or_create(
                session=session,
                participant=participant,
                defaults={
                    "ranked_items": list(default_items),
                    "is_submitted": True,
                },
            )
            if not created and not ranking.is_submitted:
                ranking.is_submitted = True
                ranking.save(update_fields=["is_submitted", "updated_at"])

        session.state = SessionState.ACTIVE
        session.started_at = timezone.now()
        session.save(update_fields=["state", "started_at"])

    # Side-effects ACTIVE-specific (fuori transazione DB)
    TurnManager.set_introducing(session_id=str(session.id))
    set_intro_pending(session_id=str(session.id))
    mark_session_started(session_id=session.id)

    # WS broadcast del cambio stato (lazy import per evitare cicli)
    from apps.sessions.serializers import SessionDetailSerializer
    from apps.sessions.views import _broadcast_session_event

    detail_data = SessionDetailSerializer(session).data
    _broadcast_session_event(
        session_id=str(session.id),
        event_type="STATE_CHANGED",
        payload=detail_data,
    )
    return True
```

- [ ] **Step 4: Verifica i test del Task 7**

```bash
docker compose run --rm web python manage.py test apps.tasks.tests.test_individual_ranking_finalize -v 2
```

Atteso: 5 test verdi.

- [ ] **Step 5: Smoke test**

```bash
docker compose run --rm web python manage.py test apps.tasks apps.sessions apps.moderation apps.turns --noinput
```

- [ ] **Step 6: Commit**

```bash
git add apps/tasks/individual_ranking.py apps/tasks/tests/test_individual_ranking_finalize.py
git commit -m "feat(tasks): add _finalize_individual_ranking_phase

- Idempotent finalize con select_for_update sulla session
- Crea righe default per partecipanti senza ranking (timer expired senza azioni)
- Marca pending come submitted senza sovrascrivere ranked_items
- Transita a ACTIVE + side-effects (TurnManager, intro pending, mark_session_started)
- WS broadcast STATE_CHANGED via SessionDetailSerializer"
```

---

## Task 8: Endpoint NASA — GET / PUT `/individual-ranking/` + autosave

**Files:**
- Modify: `apps/tasks/nasa_moon/views.py` (aggiungi `NasaIndividualRankingView`)
- Modify: `apps/tasks/nasa_moon/urls.py` (+ path)
- Test: `apps/tasks/nasa_moon/tests/test_individual_ranking.py` (estensione)

- [ ] **Step 1: Estendi il file di test con casi GET/PUT**

Aggiungi a `apps/tasks/nasa_moon/tests/test_individual_ranking.py`:

```python
from datetime import timedelta
from django.utils import timezone
from rest_framework.test import APIClient
from apps.sessions.models import SessionState


def _put_session_in_individual_ranking(session: Session) -> None:
    session.state = SessionState.INDIVIDUAL_RANKING
    session.individual_ranking_started_at = timezone.now()
    session.save(update_fields=["state", "individual_ranking_started_at"])


class NasaIndividualRankingGetPutTests(TestCase):
    def setUp(self) -> None:
        self.session, self.participants = _make_session()
        _put_session_in_individual_ranking(self.session)
        self.host_user = self.participants[0].user
        self.client = APIClient()
        self.client.force_authenticate(user=self.host_user)
        self.url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/"

    def test_get_returns_null_when_no_row(self) -> None:
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200, resp.json())
        body = resp.json()
        self.assertIsNone(body["ranked_items"])
        self.assertFalse(body["is_submitted"])
        self.assertIsNotNone(body["phase_deadline_at"])

    def test_put_creates_row(self) -> None:
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertIn(resp.status_code, (200, 201), resp.json())
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        r = NasaIndividualRanking.objects.get(session=self.session, participant=self.participants[0])
        self.assertEqual(r.ranked_items, list(NASA_ITEMS))
        self.assertFalse(r.is_submitted)

    def test_put_invalid_length(self) -> None:
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)[:14]}, format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_put_invalid_items(self) -> None:
        bad = list(NASA_ITEMS)
        bad[0] = "Oggetto inesistente"
        resp = self.client.put(self.url, data={"ranked_items": bad}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_put_duplicates(self) -> None:
        bad = list(NASA_ITEMS)
        bad[1] = bad[0]
        resp = self.client.put(self.url, data={"ranked_items": bad}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_put_in_wrong_state(self) -> None:
        self.session.state = SessionState.LOBBY
        self.session.save(update_fields=["state"])
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_put_after_submit_blocked(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        NasaIndividualRanking.objects.create(
            session=self.session, participant=self.participants[0],
            ranked_items=list(NASA_ITEMS), is_submitted=True,
        )
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertEqual(resp.status_code, 409)

    def test_put_after_deadline_finalizes_and_returns_409(self) -> None:
        # Sposta indietro il timestamp di inizio per simulare scadenza
        self.session.individual_ranking_started_at = (
            timezone.now() - timedelta(seconds=500)
        )
        self.session.save(update_fields=["individual_ranking_started_at"])
        resp = self.client.put(
            self.url, data={"ranked_items": list(NASA_ITEMS)}, format="json",
        )
        self.assertEqual(resp.status_code, 409)
        # La sessione è stata finalizzata e portata ad ACTIVE
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.ACTIVE)
```

- [ ] **Step 2: Verifica che i test falliscano (404 perché URL non esiste)**

```bash
docker compose run --rm web python manage.py test apps.tasks.nasa_moon.tests.test_individual_ranking -v 2 -k GetPut
```

- [ ] **Step 3: Implementa `NasaIndividualRankingView`**

In `apps/tasks/nasa_moon/views.py`, **alla fine del file** (dopo `NasaRankingSubmitView`):

```python
from datetime import timedelta

from .models import NasaIndividualRanking


class NasaIndividualRankingView(APIView):
    """GET/PUT del ranking individuale del chiamante.

    GET ritorna ranked_items=null se la riga non esiste.
    PUT è autosave: ogni drag-and-drop manda un PUT.
    """

    permission_classes = [permissions.IsAuthenticated]

    def _participant(self, session: Session, user) -> Optional[SessionParticipant]:
        return SessionParticipant.objects.filter(session=session, user=user).first()

    def _phase_deadline(self, session: Session) -> Optional["datetime.datetime"]:
        if not session.individual_ranking_started_at:
            return None
        from apps.tasks.registry import get_task
        task = get_task(session.context)
        return session.individual_ranking_started_at + timedelta(
            seconds=task.individual_ranking_duration_seconds()
        )

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)
        participant = self._participant(session, request.user)
        if participant is None:
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )
        deadline = self._phase_deadline(session)
        try:
            r = NasaIndividualRanking.objects.get(
                session=session, participant=participant,
            )
            return Response({
                "ranked_items": r.ranked_items,
                "is_submitted": r.is_submitted,
                "updated_at": r.updated_at.isoformat(),
                "phase_deadline_at": deadline.isoformat() if deadline else None,
            })
        except NasaIndividualRanking.DoesNotExist:
            return Response({
                "ranked_items": None,
                "is_submitted": False,
                "updated_at": None,
                "phase_deadline_at": deadline.isoformat() if deadline else None,
            })

    def put(self, request, session_id: str):
        from django.utils import timezone

        session = get_object_or_404(Session, pk=session_id)
        if session.state != SessionState.INDIVIDUAL_RANKING:
            return Response(
                {"detail": "Il ranking individuale e modificabile solo in fase INDIVIDUAL_RANKING."},
                status=status.HTTP_409_CONFLICT,
            )

        # Lazy timer check: se scaduto, finalizza e rifiuta
        deadline = self._phase_deadline(session)
        if deadline and timezone.now() >= deadline:
            from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
            _finalize_individual_ranking_phase(session)
            return Response(
                {"detail": "Phase already expired."},
                status=status.HTTP_409_CONFLICT,
            )

        participant = self._participant(session, request.user)
        if participant is None:
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        ranked_items = request.data.get("ranked_items")
        if not isinstance(ranked_items, list):
            return Response(
                {"detail": "ranked_items deve essere una lista."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(ranked_items) != len(NASA_ITEMS):
            return Response(
                {"detail": f"Il ranking deve contenere {len(NASA_ITEMS)} oggetti."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if set(ranked_items) != set(NASA_ITEMS):
            return Response(
                {"detail": "Il ranking contiene oggetti non validi o mancanti."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(set(ranked_items)) != len(ranked_items):
            return Response(
                {"detail": "Il ranking contiene oggetti duplicati."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Lazy own-state check: no editing dopo submit esplicito
        existing = NasaIndividualRanking.objects.filter(
            session=session, participant=participant,
        ).first()
        if existing and existing.is_submitted:
            return Response(
                {"detail": "Il tuo ranking individuale è già stato confermato."},
                status=status.HTTP_409_CONFLICT,
            )

        ranking, created = NasaIndividualRanking.objects.update_or_create(
            session=session,
            participant=participant,
            defaults={
                "ranked_items": ranked_items,
                "is_submitted": False,
            },
        )

        return Response(
            {
                "ranked_items": ranking.ranked_items,
                "is_submitted": False,
                "updated_at": ranking.updated_at.isoformat(),
                "phase_deadline_at": deadline.isoformat() if deadline else None,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
```

Aggiungi anche l'import necessario all'inizio di `views.py` se manca:

```python
from typing import Optional
```

- [ ] **Step 4: Aggiungi URL**

In `apps/tasks/nasa_moon/urls.py`, aggiungi alla lista dei `urlpatterns`:

```python
from .views import (
    NasaRankingView, NasaRankingStatusView, NasaRankingSubmitView,
    NasaIndividualRankingView,
)

# ... dentro urlpatterns ...
    path(
        "sessions/<uuid:session_id>/individual-ranking/",
        NasaIndividualRankingView.as_view(),
        name="nasa_individual_ranking",
    ),
```

- [ ] **Step 5: Verifica i test**

```bash
docker compose run --rm web python manage.py test apps.tasks.nasa_moon.tests.test_individual_ranking -v 2 -k GetPut
```

Atteso: 8 test passano.

- [ ] **Step 6: Commit**

```bash
git add apps/tasks/nasa_moon/views.py apps/tasks/nasa_moon/urls.py \
        apps/tasks/nasa_moon/tests/test_individual_ranking.py
git commit -m "feat(tasks/nasa_moon): add GET/PUT /individual-ranking/ endpoint with autosave

- GET ritorna ranked_items=null se non esiste
- PUT autosave (no submit) con validazione lunghezza/set/duplicati
- Lazy timer check: PUT dopo deadline -> finalize + 409
- Lazy own-state check: PUT dopo is_submitted=True -> 409"
```

---

## Task 9: Endpoint NASA — POST `/submit/` + POST `/finalize-if-expired/`

**Files:**
- Modify: `apps/tasks/nasa_moon/views.py` (aggiungi 2 view)
- Modify: `apps/tasks/nasa_moon/urls.py` (+ 2 path)
- Test: `apps/tasks/nasa_moon/tests/test_individual_ranking.py` (estensione)

- [ ] **Step 1: Test failing per Submit**

Aggiungi a `apps/tasks/nasa_moon/tests/test_individual_ranking.py`:

```python
class NasaIndividualRankingSubmitTests(TestCase):
    def setUp(self) -> None:
        self.session, self.participants = _make_session()
        _put_session_in_individual_ranking(self.session)
        self.client = APIClient()
        self.url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/submit/"
        self.put_url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/"

    def _client_for(self, participant):
        c = APIClient()
        c.force_authenticate(user=participant.user)
        return c

    def test_submit_marks_is_submitted(self) -> None:
        from apps.tasks.nasa_moon.models import NasaIndividualRanking
        c = self._client_for(self.participants[0])
        c.put(self.put_url, data={"ranked_items": list(NASA_ITEMS)}, format="json")
        resp = c.post(self.url)
        self.assertEqual(resp.status_code, 200, resp.json())
        r = NasaIndividualRanking.objects.get(
            session=self.session, participant=self.participants[0],
        )
        self.assertTrue(r.is_submitted)

    def test_submit_without_existing_row_returns_400(self) -> None:
        c = self._client_for(self.participants[0])
        resp = c.post(self.url)
        self.assertEqual(resp.status_code, 400)

    def test_submit_already_submitted_returns_409(self) -> None:
        c = self._client_for(self.participants[0])
        c.put(self.put_url, data={"ranked_items": list(NASA_ITEMS)}, format="json")
        c.post(self.url)
        resp = c.post(self.url)
        self.assertEqual(resp.status_code, 409)

    def test_last_submit_triggers_finalize(self) -> None:
        # Tutti e 3 fanno PUT + submit; l'ultimo deve scattare la finalize
        for p in self.participants:
            c = self._client_for(p)
            c.put(self.put_url, data={"ranked_items": list(NASA_ITEMS)}, format="json")
            c.post(self.url)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.ACTIVE)


class NasaIndividualRankingFinalizeIfExpiredTests(TestCase):
    def setUp(self) -> None:
        self.session, self.participants = _make_session()
        _put_session_in_individual_ranking(self.session)
        self.client = APIClient()
        self.client.force_authenticate(user=self.participants[0].user)
        self.url = f"/api/tasks/nasa-moon/sessions/{self.session.id}/individual-ranking/finalize-if-expired/"

    def test_no_op_if_state_wrong(self) -> None:
        self.session.state = SessionState.LOBBY
        self.session.save(update_fields=["state"])
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["finalized"])

    def test_no_op_if_not_expired(self) -> None:
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["finalized"])

    def test_finalizes_if_expired(self) -> None:
        from datetime import timedelta
        from django.utils import timezone
        self.session.individual_ranking_started_at = (
            timezone.now() - timedelta(seconds=500)
        )
        self.session.save(update_fields=["individual_ranking_started_at"])
        resp = self.client.post(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["finalized"])
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, SessionState.ACTIVE)

    def test_idempotent(self) -> None:
        from datetime import timedelta
        from django.utils import timezone
        self.session.individual_ranking_started_at = (
            timezone.now() - timedelta(seconds=500)
        )
        self.session.save(update_fields=["individual_ranking_started_at"])
        self.client.post(self.url)
        resp2 = self.client.post(self.url)
        self.assertEqual(resp2.status_code, 200)
        self.assertFalse(resp2.json()["finalized"])
```

- [ ] **Step 2: Verifica fail**

```bash
docker compose run --rm web python manage.py test apps.tasks.nasa_moon.tests.test_individual_ranking -v 2 -k "Submit or FinalizeIfExpired"
```

Atteso: 404 per gli URL nuovi.

- [ ] **Step 3: Implementa `NasaIndividualRankingSubmitView`**

In `apps/tasks/nasa_moon/views.py`, aggiungi:

```python
class NasaIndividualRankingSubmitView(APIView):
    """POST: marca is_submitted=True. Se tutti hanno submittato → finalize."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        from django.utils import timezone
        from datetime import timedelta

        session = get_object_or_404(Session, pk=session_id)
        if session.state != SessionState.INDIVIDUAL_RANKING:
            return Response(
                {"detail": "Submit possibile solo in fase INDIVIDUAL_RANKING."},
                status=status.HTTP_409_CONFLICT,
            )

        # Lazy timer check anche qui
        from apps.tasks.registry import get_task
        task = get_task(session.context)
        deadline = (
            session.individual_ranking_started_at
            + timedelta(seconds=task.individual_ranking_duration_seconds())
            if session.individual_ranking_started_at
            else None
        )
        if deadline and timezone.now() >= deadline:
            from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
            _finalize_individual_ranking_phase(session)
            return Response(
                {"detail": "Phase already expired."},
                status=status.HTTP_409_CONFLICT,
            )

        participant = SessionParticipant.objects.filter(
            session=session, user=request.user,
        ).first()
        if participant is None:
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        ranking = NasaIndividualRanking.objects.filter(
            session=session, participant=participant,
        ).first()
        if ranking is None:
            return Response(
                {"detail": "Devi prima compilare un ranking (PUT)."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ranking.is_submitted:
            return Response(
                {"detail": "Il tuo ranking è già stato confermato."},
                status=status.HTTP_409_CONFLICT,
            )

        ranking.is_submitted = True
        ranking.save(update_fields=["is_submitted", "updated_at"])

        # Trigger finalize se tutti hanno submittato
        total = SessionParticipant.objects.filter(session=session).count()
        submitted = NasaIndividualRanking.objects.filter(
            session=session, is_submitted=True,
        ).count()
        all_submitted = (submitted == total)

        if all_submitted:
            from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
            _finalize_individual_ranking_phase(session)

        return Response({
            "success": True,
            "is_submitted": True,
            "all_submitted": all_submitted,
        })


class NasaIndividualRankingFinalizeView(APIView):
    """POST idempotente: finalizza la fase se il timer è scaduto."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id: str):
        from django.utils import timezone
        from datetime import timedelta

        session = get_object_or_404(Session, pk=session_id)
        if not SessionParticipant.objects.filter(
            session=session, user=request.user,
        ).exists():
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if session.state != SessionState.INDIVIDUAL_RANKING:
            return Response({"finalized": False, "reason": "wrong_state"})

        from apps.tasks.registry import get_task
        task = get_task(session.context)
        if not session.individual_ranking_started_at:
            return Response({"finalized": False, "reason": "never_started"})

        deadline = session.individual_ranking_started_at + timedelta(
            seconds=task.individual_ranking_duration_seconds()
        )
        if timezone.now() < deadline:
            return Response({"finalized": False, "reason": "not_expired"})

        from apps.tasks.individual_ranking import _finalize_individual_ranking_phase
        _finalize_individual_ranking_phase(session)
        return Response({"finalized": True})
```

- [ ] **Step 4: Aggiungi URL**

In `apps/tasks/nasa_moon/urls.py`:

```python
from .views import (
    NasaRankingView, NasaRankingStatusView, NasaRankingSubmitView,
    NasaIndividualRankingView,
    NasaIndividualRankingSubmitView,
    NasaIndividualRankingFinalizeView,
)

# ... dentro urlpatterns ...
    path(
        "sessions/<uuid:session_id>/individual-ranking/submit/",
        NasaIndividualRankingSubmitView.as_view(),
        name="nasa_individual_ranking_submit",
    ),
    path(
        "sessions/<uuid:session_id>/individual-ranking/finalize-if-expired/",
        NasaIndividualRankingFinalizeView.as_view(),
        name="nasa_individual_ranking_finalize",
    ),
```

- [ ] **Step 5: Verifica test passino**

```bash
docker compose run --rm web python manage.py test apps.tasks.nasa_moon.tests.test_individual_ranking -v 2
```

Atteso: tutti verdi (submit + finalize-if-expired).

- [ ] **Step 6: Commit**

```bash
git add apps/tasks/nasa_moon/views.py apps/tasks/nasa_moon/urls.py \
        apps/tasks/nasa_moon/tests/test_individual_ranking.py
git commit -m "feat(tasks/nasa_moon): add submit + finalize-if-expired endpoints

- POST /submit/ marca is_submitted=True; ultimo submit -> finalize
- POST /finalize-if-expired/ idempotente, chiamato dal frontend al setTimeout 8 min"
```

---

## Task 10: Endpoint LAS — GET/PUT/Submit/Finalize (speculare a NASA)

Speculare al Task 8+9. I test sono identici modulo nomi delle costanti e del modello.

**Files:**
- Modify: `apps/tasks/lost_at_sea/views.py`
- Modify: `apps/tasks/lost_at_sea/urls.py`
- Test: `apps/tasks/lost_at_sea/tests/test_individual_ranking.py` (estensione)

- [ ] **Step 1: Estendi i test**

Aggiungi a `apps/tasks/lost_at_sea/tests/test_individual_ranking.py` le 3 test class speculare al Task 8+9 (`LostAtSeaIndividualRankingGetPutTests`, `LostAtSeaIndividualRankingSubmitTests`, `LostAtSeaIndividualRankingFinalizeIfExpiredTests`). Sostituzioni meccaniche:
- `NASA_ITEMS` → `LOST_AT_SEA_ITEMS`
- `NasaIndividualRanking` → `LostAtSeaIndividualRanking`
- `nasa_moon` → `lost_at_sea`
- `nasa-moon` → `lost-at-sea`
- helper `_put_session_in_individual_ranking` lo importi/duplichi nel file (è già stato definito nei test NASA, ma per isolamento test LAS è meglio una copia).

- [ ] **Step 2: Verifica failing**

```bash
docker compose run --rm web python manage.py test apps.tasks.lost_at_sea.tests.test_individual_ranking -v 2
```

- [ ] **Step 3: Implementa le 3 view in `apps/tasks/lost_at_sea/views.py`**

Copia le 3 classi da `apps/tasks/nasa_moon/views.py` (`NasaIndividualRankingView`, `NasaIndividualRankingSubmitView`, `NasaIndividualRankingFinalizeView`), sostituzioni:
- `NasaIndividualRanking` → `LostAtSeaIndividualRanking`
- `NASA_ITEMS` → `LOST_AT_SEA_ITEMS`
- prefisso classe `Nasa` → `LostAtSea`

L'import del modello e della costante:
```python
from .models import LostAtSeaIndividualRanking
from .config import LOST_AT_SEA_ITEMS
```

- [ ] **Step 4: Aggiorna `apps/tasks/lost_at_sea/urls.py`**

Aggiungi le 3 route, simmetriche al Task 8+9.

- [ ] **Step 5: Verifica test passino**

```bash
docker compose run --rm web python manage.py test apps.tasks.lost_at_sea.tests.test_individual_ranking -v 2
```

- [ ] **Step 6: Commit**

```bash
git add apps/tasks/lost_at_sea/views.py apps/tasks/lost_at_sea/urls.py \
        apps/tasks/lost_at_sea/tests/test_individual_ranking.py
git commit -m "feat(tasks/lost_at_sea): add individual ranking endpoints (GET/PUT/submit/finalize)

Speculare a NASA Moon: stessa semantica, stessi codici di stato, stessi vincoli."
```

---

## Task 11: Aggiorna `collect_nasa_report_context` con synergy_gain

**Files:**
- Modify: `apps/tasks/nasa_moon/report.py`
- Test: `apps/reports/tests.py` (estensione)

- [ ] **Step 1: Test failing**

In `apps/reports/tests.py` (o file tests dedicato `apps/tasks/nasa_moon/tests/test_report.py` se preferisci scope-locale), aggiungi:

```python
class NasaReportContextSynergyTests(TestCase):
    def test_synergy_gain_computed_when_individual_rankings_exist(self) -> None:
        from apps.tasks.nasa_moon.models import NasaRanking, NasaIndividualRanking
        from apps.tasks.nasa_moon.report import collect_nasa_report_context
        from apps.tasks.nasa_moon.config import NASA_ITEMS, compute_error_score

        # Setup sessione + ranking di gruppo
        host = User.objects.create_user(username="rep_h", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival",
            min_size=3, max_size=6, host=host,
            state=SessionState.CLOSED,
        )
        p_host = SessionParticipant.objects.create(
            session=session, user=host, role=ParticipantRole.HOST,
        )
        # group ranking molto buono (uguale all'expert ranking, error 0)
        from apps.tasks.nasa_moon.config import EXPERT_RANKING
        sorted_items = sorted(EXPERT_RANKING.keys(), key=lambda k: EXPERT_RANKING[k])
        NasaRanking.objects.create(
            session=session, submitted_by=p_host,
            ranked_items=sorted_items, is_final=True,
        )
        # 3 ranking individuali con errori vari
        for i, items in enumerate([
            list(NASA_ITEMS),  # default order: error elevato
            sorted_items,       # perfect: error 0
            list(reversed(sorted_items)),  # peggio: error massimo
        ]):
            u = User.objects.create_user(username=f"rep_p_{i}", password="x")
            p = SessionParticipant.objects.create(session=session, user=u)
            NasaIndividualRanking.objects.create(
                session=session, participant=p,
                ranked_items=items, is_submitted=True,
            )

        ctx = collect_nasa_report_context(session)
        self.assertIsNotNone(ctx["synergy_gain"])
        self.assertIsNotNone(ctx["mean_individual_error"])
        self.assertEqual(ctx["individual_count"], 3)
        # group_error = 0, mean_individual_error > 0 → synergy_gain > 0
        self.assertGreater(ctx["synergy_gain"], 0)
        self.assertTrue(ctx["assembly_bonus"])  # group < min(individual)

    def test_legacy_session_no_individual_rankings_keeps_none(self) -> None:
        from apps.tasks.nasa_moon.report import collect_nasa_report_context
        # Sessione senza individual rankings (legacy o no fase eseguita)
        host = User.objects.create_user(username="rep_legacy_h", password="x")
        session = Session.objects.create(
            title="T", context="nasa_moon_survival",
            min_size=3, max_size=6, host=host, state=SessionState.CLOSED,
        )
        ctx = collect_nasa_report_context(session)
        self.assertIsNone(ctx["synergy_gain"])
        self.assertIsNone(ctx["individual_errors"])
        self.assertIsNone(ctx["assembly_bonus"])
```

(Nota: gli import `from apps.sessions.models import ...` devono essere a top del file dei test, controlla quelli già presenti.)

- [ ] **Step 2: Verifica failing**

```bash
docker compose run --rm web python manage.py test apps.reports.tests.NasaReportContextSynergyTests -v 2
```

- [ ] **Step 3: Modifica `collect_nasa_report_context`**

In `apps/tasks/nasa_moon/report.py`, sostituisci la funzione esistente:

```python
def collect_nasa_report_context(session) -> Dict[str, Any]:
    """Raccoglie ranking di gruppo + ranking individuali per il report.

    Calcola synergy_gain e assembly_bonus se ci sono ranking individuali
    submitted; altrimenti i campi restano None (sessioni legacy).
    """
    from .models import NasaRanking, NasaIndividualRanking

    base: Dict[str, Any] = {
        "synergy_gain": None,
        "individual_errors": None,
        "assembly_bonus": None,
        "mean_individual_error": None,
        "individual_count": 0,
    }

    try:
        ranking = NasaRanking.objects.get(session=session)
        ranked_items = ranking.ranked_items
        error_score = compute_error_score(ranked_items)

        items_detail = []
        for i, item in enumerate(ranked_items):
            team_rank = i + 1
            expert_rank = EXPERT_RANKING[item]
            diff = abs(team_rank - expert_rank)
            items_detail.append({
                "item": item,
                "team_rank": team_rank,
                "expert_rank": expert_rank,
                "diff": diff,
            })

        base.update({
            "ranked_items": ranked_items,
            "error_score": error_score,
            "max_error_score": MAX_ERROR_SCORE,
            "items_detail": items_detail,
            "has_ranking": True,
        })
    except NasaRanking.DoesNotExist:
        base.update({"has_ranking": False})

    # Synergy gain calc (solo se ci sono ranking individuali submitted)
    individual_rankings = list(
        NasaIndividualRanking.objects.filter(session=session, is_submitted=True)
    )
    if individual_rankings and base.get("has_ranking"):
        individual_errors = [
            compute_error_score(r.ranked_items) for r in individual_rankings
        ]
        group_error = base["error_score"]
        mean_individual_error = sum(individual_errors) / len(individual_errors)
        base["individual_errors"] = individual_errors
        base["mean_individual_error"] = mean_individual_error
        base["synergy_gain"] = mean_individual_error - group_error
        base["assembly_bonus"] = group_error < min(individual_errors)
        base["individual_count"] = len(individual_errors)

    return base
```

- [ ] **Step 4: Verifica test passino**

```bash
docker compose run --rm web python manage.py test apps.reports.tests.NasaReportContextSynergyTests -v 2
```

- [ ] **Step 5: Commit**

```bash
git add apps/tasks/nasa_moon/report.py apps/reports/tests.py
git commit -m "feat(tasks/nasa_moon): compute synergy_gain + assembly_bonus in report context

- collect_nasa_report_context popola synergy_gain, mean_individual_error,
  individual_errors, assembly_bonus, individual_count
- Sessioni legacy senza ranking individuali: campi restano None"
```

---

## Task 12: Aggiorna `build_nasa_pdf_sections` per output reale + prompt LLM

**Files:**
- Modify: `apps/tasks/nasa_moon/report.py` (sezione PDF + prompt LLM)

- [ ] **Step 1: Modifica la sezione PDF placeholder**

In `apps/tasks/nasa_moon/report.py`, dentro `build_nasa_pdf_sections`, sostituisci il blocco "Synergy gain (placeholder...)" e "Assembly bonus (placeholder)" con:

```python
    # Synergy gain
    synergy = context.get("synergy_gain")
    mean_ind = context.get("mean_individual_error")
    if synergy is None:
        elements.append(Paragraph(
            "Synergy gain: <i>N/A &mdash; nessun ranking individuale registrato.</i>",
            body_style,
        ))
    else:
        sign = "+" if synergy >= 0 else ""
        comment = (
            "il gruppo ha migliorato rispetto alla media individuale"
            if synergy > 0
            else "il gruppo ha peggiorato rispetto alla media individuale (process loss)"
            if synergy < 0
            else "il gruppo ha eguagliato la media individuale"
        )
        elements.append(Paragraph(
            f"Synergy gain: <b>{sign}{synergy:.1f}</b> "
            f"(media individuale {mean_ind:.1f} - error gruppo {error_score} — {comment})",
            body_style,
        ))

    # Assembly bonus
    assembly = context.get("assembly_bonus")
    individual_errors = context.get("individual_errors")
    if assembly is True and individual_errors:
        elements.append(Paragraph(
            f"Assembly bonus: <b>SI</b> &mdash; il gruppo ha fatto meglio "
            f"del miglior individuo: {error_score} vs {min(individual_errors)}.",
            body_style,
        ))
    elif assembly is False and individual_errors:
        elements.append(Paragraph(
            f"Assembly bonus: <b>NO</b> &mdash; almeno un partecipante "
            f"individualmente ha fatto meglio del gruppo "
            f"({min(individual_errors)} vs {error_score}).",
            body_style,
        ))
    # Se None, non mostrare nulla
```

- [ ] **Step 2: Aggiorna il prompt LLM (rimuovi postilla obsoleta)**

In `apps/tasks/nasa_moon/report.py`, nella funzione `build_nasa_report_llm_prompt`, sezione "RANKING RESULT":

```
- If `synergy_gain` is provided, comment whether the group's discussion
  improved over the average individual baseline. If null, do not mention it.
```

(rimuovi: "the experimental flow is not fully active yet").

- [ ] **Step 3: Verifica regression**

```bash
docker compose run --rm web python manage.py test apps.tasks apps.reports --noinput
```

Atteso: verde.

- [ ] **Step 4: Commit**

```bash
git add apps/tasks/nasa_moon/report.py
git commit -m "feat(tasks/nasa_moon): replace synergy_gain placeholder with real PDF output

- build_nasa_pdf_sections mostra synergy_gain con segno e interpretazione
- assembly_bonus mostra il delta esplicito vs miglior individuo
- Prompt LLM: rimossa postilla obsoleta sull'assenza del flow individuale"
```

---

## Task 13: Speculare per Lost at Sea — report context + PDF + prompt

**Files:**
- Modify: `apps/tasks/lost_at_sea/report.py`
- Test: `apps/reports/tests.py` (estensione speculare)

- [ ] **Step 1: Test speculare**

Aggiungi a `apps/reports/tests.py` `LostAtSeaReportContextSynergyTests` (speculare al Task 11), sostituendo `nasa_moon` → `lost_at_sea` e nomi.

- [ ] **Step 2: Modifica `collect_lost_at_sea_report_context`**

Speculare al Task 11 (stesso pattern, modello e import diversi).

- [ ] **Step 3: Modifica `build_lost_at_sea_pdf_sections`**

Speculare al Task 12 (le righe da sostituire vivono in
`apps/tasks/lost_at_sea/report.py:195-223`).

- [ ] **Step 4: Aggiorna il prompt LLM**

Stessa modifica del Task 12 step 2.

- [ ] **Step 5: Verifica**

```bash
docker compose run --rm web python manage.py test apps.tasks.lost_at_sea apps.reports --noinput
```

- [ ] **Step 6: Commit**

```bash
git add apps/tasks/lost_at_sea/report.py apps/reports/tests.py
git commit -m "feat(tasks/lost_at_sea): compute synergy_gain + update PDF/prompt

Speculare a NASA Moon: stessa logica synergy_gain/assembly_bonus,
stesso prompt cleanup."
```

---

## Task 14: Smoke test integrato + run completa

**Files:**
- Solo esecuzione test, nessuna modifica al codice (a meno di trovare regressioni).

- [ ] **Step 1: Run completa di tutta la suite di test backend**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.tasks \
  apps.sessions \
  apps.reports \
  apps.moderation \
  apps.turns
```

Atteso: tutti i test verdi (i 237+ esistenti + ~30-50 nuovi).

- [ ] **Step 2: Verifica numero test**

```bash
docker compose run --rm web python manage.py test --noinput 2>&1 | tail -5
```

Cerca la riga `Ran NNN tests in ... OK`. Documentalo nel commit message.

- [ ] **Step 3: Verifica cosa NON è stato toccato (regression check)**

```bash
docker compose run --rm web python manage.py test \
  apps.moderation.tests_integration apps.turns.tests_services --noinput
```

Atteso: verdi. Se qualcosa fallisce, è una regressione: indaga.

- [ ] **Step 4: Solo se ci sono fix necessari, committa**

(Nessun commit se tutti i test sono verdi.)

---

## Self-Review

**Spec coverage:**
- §3 decisioni 1-8 → tutte coperte: 1/3 (Task 3+4), 2 (Task 5+6), 4/4.bis (Task 8+10), 5 (Task 9+10 finalize-if-expired), 6/7 (Task 11-13), 8 (out-of-scope nel prompt LLM, lasciato cieco).
- §4 architettura → Task 3+4 (state machine, plugin hook).
- §4.3 contratto fase (audio/moderator OFF) → Task 4 step 5 esplicita lo skip dei side-effects ACTIVE-only.
- §5 modelli → Task 5+6.
- §6 endpoint REST → Task 8+9 NASA, Task 10 LAS.
- §7 finalize → Task 7 funzione + Task 8/9/10 trigger.
- §8 synergy_gain report → Task 11+13 context, Task 12+13 PDF e prompt.
- §9 testing → coperto per ogni task con casi specifici.
- §10 deploy → fuori scope di questo plan (l'utente ha esplicitato che il brief frontend si scrive *dopo* l'implementazione).
- §11 rischi → mitigati nei test (idempotenza Task 7, timer check Task 8/9/10).
- §12 file e luoghi → coperti.

**Placeholder scan:** nessun TBD/TODO. I "Speculare a..." nei task LAS sono accompagnati dal task di riferimento esatto (Task 5/6/8+9/11/12) — ma per non vincolare il lettore a leggere fuori ordine, nei task speculari le sostituzioni meccaniche sono enumerate esplicitamente.

**Type consistency:** `NasaIndividualRanking`/`LostAtSeaIndividualRanking` usati ovunque coerentemente. `_finalize_individual_ranking_phase` con stessa firma in tutti i task. `phase_deadline_at` come chiave del payload GET coerente in NASA/LAS.

---

**Plan complete and saved to `docs/plans/2026-05-06-individual-ranking-collection-implementation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - dispatch un subagent fresco per ogni task, review tra task, iterazione veloce.

**2. Inline Execution** - eseguo i task in questa session con `superpowers:executing-plans`, batch con checkpoint per review.

**Which approach?**
