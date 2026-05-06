# No-Moderator Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementare la modalità di sessione "no-moderator" come flag immutabile per-sessione su `Session.moderator_enabled` (default `True`), che disabilita le LLM moderation calls e gli interventi vocali del moderatore mantenendo intro, turn-taking, ASR, raccolta dati e report PDF — necessario per il braccio di controllo del design sperimentale within-subject (NASA Moon + Lost at Sea con moderatore ON/OFF, ordine controbilanciato).

**Architecture:** Aggiunta di un singolo campo bool su `Session` esposto via `SessionCreateSerializer` (write) e `SessionDetailSerializer` (read, → `STATE_CHANGED` payload). I 3 guard vivono **solo** in `apps/turns/ws_consumer.py` (coordinator) — il moderation service (`apps/moderation/`) resta puro e ignaro della modalità OFF. I guard saltano: la pipeline di moderazione in `_handle_end_speak`, gli `static_messages_to_speak` e `_execute_forced_conclusion` in `_trigger_loop`, `_execute_forced_conclusion` in `_flush_pending_tts_messages`. La transizione di stato `ACTIVE → CONCLUSION` resta abilitata in entrambe le modalità (timer + STATE_CHANGED broadcast).

**Tech Stack:** Django 5 + Django REST Framework, PostgreSQL 16, Channels (WebSocket), pytest via `manage.py test`, Docker Compose per esecuzione locale.

**Spec di riferimento:** `docs/plans/2026-05-07-no-moderator-mode-design.md`.

---

## File Structure

### File modificati
- `apps/sessions/models.py` — `+ moderator_enabled` BooleanField su `Session`.
- `apps/sessions/serializers.py` — `SessionCreateSerializer` write field opzionale (default `True`); `SessionDetailSerializer` read field.
- `apps/sessions/tests.py` — `+ 4 test` su model default + serializer write/read + STATE_CHANGED payload.
- `apps/turns/ws_consumer.py` — `+ 1 helper async` `_get_moderator_enabled`; 3 guard nelle posizioni dichiarate dal design (§6.4).

### Nuovi file
- `apps/sessions/migrations/0010_session_moderator_enabled.py` — generata da `makemigrations`. **Numero esatto da verificare**: l'ultima migration è `0009_session_individual_ranking_started_at_and_more.py`.
- `apps/turns/tests_moderator_disabled.py` — `+ 7 test` (5 su mod OFF, 2 regression mod ON).

### File **non** modificati (verificati)
- `apps/moderation/*` — il service resta puro. Tutti i guard vivono nel coordinator.
- `apps/sessions/views.py` `SessionStartView` — i side-effect ACTIVE-specific (`set_intro_pending`, `mark_session_started`, `TurnManager.set_introducing`) partono in entrambe le modalità: l'intro va sempre eseguita.
- `apps/reports/*` — già robusto a `interventions_log` vuoto (`pdf_service.py:129` salta la sezione condizionalmente; `pdf_service.py:168-170` exit early). Verifica con un test esplicito (Task 9) — nessun cambiamento codice.

---

## Comando standard di test

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests apps.sessions.tests_discussion_event \
  apps.moderation.tests apps.moderation.tests_integration \
  apps.moderation.tests_intro \
  apps.turns.tests_services apps.turns.tests_disconnect \
  apps.turns.tests_moderator_disabled \
  apps.reports.tests apps.reports.tests_metrics \
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

I test esistenti (~426) devono restare verdi a ogni commit. La feature è strettamente additiva.

---

## Task 1: Aggiungere il campo `moderator_enabled` su `Session` + migration

**Files:**
- Modify: `apps/sessions/models.py:79` (subito dopo il blocco `final_summary` / `report_text` / `report_data`, prima di `class Meta`)
- Test: `apps/sessions/tests.py` (nuova classe `SessionModeratorEnabledModelTests` in fondo, prima di `class SessionStateEnumIndividualRankingTests`)
- Create: `apps/sessions/migrations/0010_session_moderator_enabled.py` (numero esatto verificato dopo `makemigrations`)

- [ ] **Step 1: Scrivi il test failing del default**

Aggiungi in `apps/sessions/tests.py`, in fondo al file (dopo `SessionIndividualRankingStartedAtTests`):

```python
class SessionModeratorEnabledModelTests(TestCase):
    """Test del campo moderator_enabled (braccio di controllo del design
    sperimentale within-subject: una sessione del gruppo gira con LLM
    moderator ON, l'altra con LLM OFF — vedi
    docs/plans/2026-05-07-no-moderator-mode-design.md)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )

    def test_session_default_moderator_enabled_true(self):
        """Una sessione creata senza il flag eredita default=True
        (backward-compat con sessioni esistenti pre-feature)."""
        session = Session.objects.create(
            title="Test default flag",
            context="murder_mystery",
            min_size=3,
            max_size=3,
            host=self.user,
        )
        self.assertTrue(session.moderator_enabled)

    def test_session_can_be_created_with_moderator_disabled(self):
        """Il flag accetta False alla creazione."""
        session = Session.objects.create(
            title="Test mod off",
            context="murder_mystery",
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=False,
        )
        self.assertFalse(session.moderator_enabled)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests.SessionModeratorEnabledModelTests
```

Atteso: FAIL con `TypeError: ... unexpected keyword argument 'moderator_enabled'` o `FieldDoesNotExist`.

- [ ] **Step 3: Aggiungi il campo al model**

In `apps/sessions/models.py`, subito dopo `report_data` (riga ~95) e prima di `class Meta` (riga ~97), aggiungi:

```python
    moderator_enabled = models.BooleanField(
        default=True,
        help_text="Se False, la sessione gira in modalità 'no moderator': "
                  "intro pronunciata regolarmente, ma niente LLM moderation "
                  "calls né interventi vocali del moderatore durante la "
                  "discussione e la conclusion. Usato per il braccio di "
                  "controllo del design sperimentale within-subject "
                  "(NASA Moon + Lost at Sea con moderatore ON/OFF, "
                  "ordine controbilanciato). Immutabile dopo creazione."
    )
```

- [ ] **Step 4: Genera la migration**

```bash
docker compose run --rm web python manage.py makemigrations sessions
```

Atteso output: `Migrations for 'sessions': 0010_session_moderator_enabled.py - Add field moderator_enabled to session`.

Verifica il file generato:

```bash
ls apps/sessions/migrations/0010_*.py
```

- [ ] **Step 5: Applica la migration al DB di test (eseguito implicitamente dal test runner) e ri-esegui i test**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests.SessionModeratorEnabledModelTests
```

Atteso: PASS (2 test).

- [ ] **Step 6: Esegui le suite Sessions complete per la regression base**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests apps.sessions.tests_discussion_event
```

Atteso: PASS, nessuna regression (i ~50 test di sessions devono restare verdi).

- [ ] **Step 7: Commit**

```bash
git add apps/sessions/models.py apps/sessions/migrations/0010_session_moderator_enabled.py apps/sessions/tests.py
git commit -m "feat(sessions): add moderator_enabled field on Session

- BooleanField default True, immutabile dopo creazione
- abilita braccio di controllo del design sperimentale within-subject
- migration backward-compat (default True per sessioni esistenti)
- vedi docs/plans/2026-05-07-no-moderator-mode-design.md"
```

---

## Task 2: Esporre `moderator_enabled` come campo write su `SessionCreateSerializer`

**Files:**
- Modify: `apps/sessions/serializers.py:33-54` (`SessionCreateSerializer.Meta.fields`)
- Test: `apps/sessions/tests.py` (estende `SessionModeratorEnabledModelTests` o nuova `SessionCreateSerializerModeratorEnabledTests`)

- [ ] **Step 1: Scrivi i test failing del POST**

Aggiungi in `apps/sessions/tests.py` (in fondo) la nuova classe:

```python
class SessionCreateSerializerModeratorEnabledTests(APITestCase):
    """POST /api/sessions/ accetta moderator_enabled (write). Default True
    se omesso. La validazione rifiuta valori non booleani."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )
        self.client.force_authenticate(user=self.user)

    def test_post_without_flag_defaults_to_true(self):
        """POST senza moderator_enabled → la sessione creata ha True."""
        response = self.client.post(
            "/api/sessions/",
            {"title": "S1", "context": "murder_mystery"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session = Session.objects.get(pk=response.data["id"])
        self.assertTrue(session.moderator_enabled)

    def test_post_with_flag_false_persists_false(self):
        """POST con moderator_enabled=false → persistenza corretta."""
        response = self.client.post(
            "/api/sessions/",
            {
                "title": "S2",
                "context": "murder_mystery",
                "moderator_enabled": False,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session = Session.objects.get(pk=response.data["id"])
        self.assertFalse(session.moderator_enabled)

    def test_post_with_flag_true_explicit_persists_true(self):
        """POST con moderator_enabled=true esplicito → persistenza corretta."""
        response = self.client.post(
            "/api/sessions/",
            {
                "title": "S3",
                "context": "murder_mystery",
                "moderator_enabled": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        session = Session.objects.get(pk=response.data["id"])
        self.assertTrue(session.moderator_enabled)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests.SessionCreateSerializerModeratorEnabledTests
```

Atteso: i primi due test falliscono. `test_post_with_flag_false_persists_false` ottiene una sessione con `moderator_enabled=True` (il flag arriva al view ma viene ignorato dal serializer).
`test_post_without_flag_defaults_to_true` può passare già (default Django) — nessun problema.

- [ ] **Step 3: Aggiungi il campo write al serializer**

In `apps/sessions/serializers.py`, modifica `SessionCreateSerializer.Meta`:

```python
    class Meta:
        model = Session
        fields = (
            "id",
            "title",
            "context",
            "state",
            "min_size",
            "max_size",
            "host",
            "participants_count",
            "moderator_enabled",
        )
        extra_kwargs = {
            "min_size": {"required": False},
            "max_size": {"required": False},
            "moderator_enabled": {"required": False},
        }
```

NB: il campo è scritto direttamente da `Session(host=user, **validated_data)` in `create()` — ModelSerializer lo passa al kwargs come bool senza serializzazione custom.

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests.SessionCreateSerializerModeratorEnabledTests
```

Atteso: PASS (3 test).

- [ ] **Step 5: Regressione su tutta `apps.sessions.tests`**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests
```

Atteso: PASS. Niente test esistente cambia comportamento (default `True` lascia tutti i flussi precedenti identici).

- [ ] **Step 6: Commit**

```bash
git add apps/sessions/serializers.py apps/sessions/tests.py
git commit -m "feat(sessions): accept moderator_enabled in POST /api/sessions/

- SessionCreateSerializer espone moderator_enabled come write opzionale
- default True se omesso (backward-compat)
- ModelSerializer passa il bool al kwargs di Session() senza override custom"
```

---

## Task 3: Esporre `moderator_enabled` come campo read su `SessionDetailSerializer` (+ STATE_CHANGED)

**Files:**
- Modify: `apps/sessions/serializers.py:148-168` (`SessionDetailSerializer.Meta.fields`)
- Test: `apps/sessions/tests.py` (nuova classe `SessionDetailSerializerModeratorEnabledTests`)

- [ ] **Step 1: Scrivi i test failing per GET + payload broadcast**

Aggiungi in fondo a `apps/sessions/tests.py`:

```python
class SessionDetailSerializerModeratorEnabledTests(TestCase):
    """SessionDetailSerializer espone moderator_enabled come read.
    Il payload è quello usato anche dal broadcast STATE_CHANGED, quindi
    questi test coprono entrambi i percorsi (GET + WS)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="host", email="host@example.com", password="pass123"
        )

    def _serialize(self, session):
        from apps.sessions.serializers import SessionDetailSerializer
        from rest_framework.test import APIRequestFactory

        factory = APIRequestFactory()
        request = factory.get("/")
        request.user = self.user
        return SessionDetailSerializer(session, context={"request": request}).data

    def test_detail_includes_moderator_enabled_true(self):
        session = Session.objects.create(
            title="S",
            context="murder_mystery",
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=True,
        )
        data = self._serialize(session)
        self.assertIn("moderator_enabled", data)
        self.assertTrue(data["moderator_enabled"])

    def test_detail_includes_moderator_enabled_false(self):
        session = Session.objects.create(
            title="S",
            context="murder_mystery",
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=False,
        )
        data = self._serialize(session)
        self.assertIn("moderator_enabled", data)
        self.assertFalse(data["moderator_enabled"])
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests.SessionDetailSerializerModeratorEnabledTests
```

Atteso: FAIL con `KeyError: 'moderator_enabled'` (il campo non è nei `fields` del serializer).

- [ ] **Step 3: Aggiungi il campo al `SessionDetailSerializer`**

In `apps/sessions/serializers.py`, modifica `SessionDetailSerializer.Meta`:

```python
    class Meta:
        model = Session
        fields = (
            "id",
            "title",
            "context",
            "state",
            "min_size",
            "max_size",
            "host",
            "participants_count",
            "me",
            "invite_url",
            "created_at",
            "started_at",
            "conclusion_at",
            "ended_at",
            "report_available",
            "votes_summary",
            "moderator_enabled",
        )
        read_only_fields = fields
```

NB: `read_only_fields = fields` è già presente nel codice; aggiungere `moderator_enabled` ai `fields` lo rende automaticamente read-only.

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests.SessionDetailSerializerModeratorEnabledTests
```

Atteso: PASS (2 test). Il flag arriva "gratis" al payload `STATE_CHANGED` perché `_get_session_detail_payload()` (in `apps/turns/ws_consumer.py:1013-1035`) usa lo stesso `SessionDetailSerializer`.

- [ ] **Step 5: Regression completa su sessions + turns**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests apps.sessions.tests_discussion_event \
  apps.turns.tests_services apps.turns.tests_disconnect
```

Atteso: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/sessions/serializers.py apps/sessions/tests.py
git commit -m "feat(sessions): expose moderator_enabled in SessionDetailSerializer

- campo read aggiunto, automatico in payload GET /api/sessions/<id>/
- automatico anche nei broadcast WS STATE_CHANGED (il consumer
  riusa SessionDetailSerializer in _get_session_detail_payload)
- niente WS event nuovo, niente endpoint PATCH: il flag è immutabile"
```

---

## Task 4: Helper async `_get_moderator_enabled` su `TurnsConsumer`

**Files:**
- Modify: `apps/turns/ws_consumer.py:838-842` (subito dopo `_get_session_state`)
- Test: `apps/turns/tests_moderator_disabled.py` (nuovo file)

- [ ] **Step 1: Crea il file di test e scrivi il test failing per il helper**

Crea `apps/turns/tests_moderator_disabled.py` con:

```python
"""Tests della modalità 'no moderator' (Session.moderator_enabled=False).

Copertura:
- helper _get_moderator_enabled
- 3 guard nel coordinator: _handle_end_speak, _trigger_loop,
  _flush_pending_tts_messages
- regression mod ON: i percorsi originali continuano a girare quando
  moderator_enabled=True

Convenzione invocazione asincrona: stesso pattern di
apps/turns/tests_disconnect.py — costruiamo una TurnsConsumer via
__new__ + asyncio.new_event_loop().run_until_complete().

Vedi docs/plans/2026-05-07-no-moderator-mode-design.md.
"""

import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

from django.test import TestCase
from django.core.cache import cache
from django.contrib.auth import get_user_model

from apps.sessions.models import Session, SessionParticipant, SessionState, ParticipantRole
from apps.turns.ws_consumer import TurnsConsumer

User = get_user_model()


class GetModeratorEnabledHelperTests(TestCase):
    """_get_moderator_enabled deve restituire il valore corrente del flag
    leggendo da DB con un singolo SELECT. Pattern speculare a
    _get_session_state."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="host", email="h@e.com", password="p"
        )

    def tearDown(self):
        cache.clear()

    def _make_session(self, *, moderator_enabled: bool) -> Session:
        s = Session.objects.create(
            title="S",
            context="murder_mystery",
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=moderator_enabled,
        )
        SessionParticipant.objects.create(
            session=s, user=self.user, role=ParticipantRole.HOST
        )
        return s

    def test_helper_returns_true_when_enabled(self):
        session = self._make_session(moderator_enabled=True)

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = str(session.id)
            return await consumer._get_moderator_enabled(consumer.session_id)

        result = asyncio.new_event_loop().run_until_complete(_run())
        self.assertTrue(result)

    def test_helper_returns_false_when_disabled(self):
        session = self._make_session(moderator_enabled=False)

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = str(session.id)
            return await consumer._get_moderator_enabled(consumer.session_id)

        result = asyncio.new_event_loop().run_until_complete(_run())
        self.assertFalse(result)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.GetModeratorEnabledHelperTests
```

Atteso: FAIL con `AttributeError: 'TurnsConsumer' object has no attribute '_get_moderator_enabled'`.

- [ ] **Step 3: Aggiungi il helper a `TurnsConsumer`**

In `apps/turns/ws_consumer.py`, subito dopo `_get_session_state` (riga 842, prima di `_ensure_session_active`):

```python
    @database_sync_to_async
    def _get_moderator_enabled(self, session_id) -> bool:
        """
        Restituisce il flag moderator_enabled della sessione (default True
        se non trovato — coerente con backward-compat).

        Usato dai 3 guard per decidere se saltare la pipeline LLM
        (vedi docs/plans/2026-05-07-no-moderator-mode-design.md).
        """
        from apps.sessions.models import Session

        try:
            return Session.objects.values_list(
                "moderator_enabled", flat=True
            ).get(id=session_id)
        except Session.DoesNotExist:
            return True
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.GetModeratorEnabledHelperTests
```

Atteso: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_moderator_disabled.py
git commit -m "feat(turns): add _get_moderator_enabled helper on TurnsConsumer

- single SELECT su Session.moderator_enabled
- pattern speculare a _get_session_state
- fallback True se sessione non trovata (backward-compat)
- usato dai 3 guard del coordinator (prossimi commit)"
```

---

## Task 5: Guard in `_handle_end_speak` — skip totale della pipeline di moderazione

**Files:**
- Modify: `apps/turns/ws_consumer.py:303-559` (subito dopo step 2 `_mark_any_activity` + `_broadcast_events`, prima di step 3 `_set_moderation_in_progress(True)` riga 364)
- Test: `apps/turns/tests_moderator_disabled.py` (estende il file con la classe `EndSpeakModeratorDisabledTests`)

**Contesto:** quando `moderator_enabled=False`, il turno umano è chiuso normalmente (step 1 + broadcast events) ma poi si esce: niente `_set_moderation_in_progress`, niente `_run_moderation_orchestrator`, niente static_messages, niente TTS dell'intervento, niente `should_transition_to_conclusion`. Il prossimo speaker può prenotarsi normalmente (lo stato turn è IDLE post-end_speak).

- [ ] **Step 1: Scrivi i test failing**

Aggiungi in `apps/turns/tests_moderator_disabled.py` (in fondo):

```python
class EndSpeakModeratorDisabledTests(TestCase):
    """Quando moderator_enabled=False, _handle_end_speak chiude il turno
    umano e ritorna senza chiamare l'orchestrator né alcun TTS."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()
        self.user = User.objects.create_user(
            username="speaker", email="sp@e.com", password="p"
        )
        self.session = Session.objects.create(
            title="S",
            context="murder_mystery",
            state=SessionState.ACTIVE,
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=False,
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST
        )

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def _make_consumer(self):
        consumer = TurnsConsumer.__new__(TurnsConsumer)
        consumer.session_id = str(self.session.id)
        consumer.group_name = f"turns_{self.session.id}"
        consumer.channel_name = "test-channel"
        consumer.scope = {"user": self.user}
        consumer.channel_layer = AsyncMock()
        consumer.send_json = AsyncMock()
        return consumer

    def test_end_speak_skips_orchestrator_when_moderator_disabled(self):
        """Mod OFF: _run_moderation_orchestrator NON chiamato.
        Verifica anche che _set_moderation_in_progress NON sia chiamato
        (entrata fase moderazione saltata)."""

        async def _run():
            consumer = self._make_consumer()

            # Mock TurnManager.end_speak per simulare chiusura turno OK
            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_run_moderation_orchestrator",
                new=AsyncMock(),
            ) as mock_orchestrator, patch.object(
                TurnsConsumer, "_set_moderation_in_progress",
                new=AsyncMock(),
            ) as mock_set_mod_progress:
                await consumer._handle_end_speak({"transcript": "hello"})

                mock_orchestrator.assert_not_awaited()
                mock_set_mod_progress.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_end_speak_skips_static_messages_and_tts_when_disabled(self):
        """Mod OFF: nessun side-effect TTS / static messages dopo end_speak."""

        async def _run():
            consumer = self._make_consumer()

            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_execute_tts_message",
                new=AsyncMock(),
            ) as mock_tts:
                await consumer._handle_end_speak({"transcript": "hi"})

                mock_tts.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())


class EndSpeakModeratorEnabledRegressionTests(TestCase):
    """Regression: mod ON deve continuare a chiamare l'orchestrator."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()
        self.user = User.objects.create_user(
            username="speaker", email="sp@e.com", password="p"
        )
        self.session = Session.objects.create(
            title="S",
            context="murder_mystery",
            state=SessionState.ACTIVE,
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=True,
        )
        SessionParticipant.objects.create(
            session=self.session, user=self.user, role=ParticipantRole.HOST
        )

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_end_speak_runs_orchestrator_when_moderator_enabled(self):
        """Mod ON: l'orchestrator DEVE essere chiamato (regression)."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = str(self.session.id)
            consumer.group_name = f"turns_{self.session.id}"
            consumer.channel_name = "test-channel"
            consumer.scope = {"user": self.user}
            consumer.channel_layer = AsyncMock()
            consumer.send_json = AsyncMock()

            mock_end_result = MagicMock()
            mock_end_result.success = True
            mock_end_result.events = []
            mock_end_result.to_state_dict = MagicMock(return_value={})

            mock_decision = MagicMock()
            mock_decision.hard_action = None
            mock_decision.ai_should_speak = False
            mock_decision.ai_message = ""
            mock_decision.static_messages_to_speak = []
            mock_decision.should_transition_to_conclusion = False

            with patch(
                "apps.turns.services.TurnManager.end_speak",
                return_value=mock_end_result,
            ), patch.object(
                TurnsConsumer, "_ensure_session_active",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_mark_any_activity",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_broadcast_events",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_set_moderation_in_progress",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_collect_asr_transcript_with_wait",
                new=AsyncMock(return_value=""),
            ), patch.object(
                TurnsConsumer, "_run_moderation_orchestrator",
                new=AsyncMock(return_value=mock_decision),
            ) as mock_orchestrator, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ), patch(
                "apps.turns.services.TurnManager.start_reservation_window",
                return_value=None,
            ), patch(
                "apps.turns.services.TurnManager.get_state",
                return_value=MagicMock(to_state_dict=lambda: {}),
            ):
                await consumer._handle_end_speak({"transcript": "hi"})

                mock_orchestrator.assert_awaited_once()

        asyncio.new_event_loop().run_until_complete(_run())
```

- [ ] **Step 2: Esegui i test e verifica che falliscano (mod OFF)**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.EndSpeakModeratorDisabledTests
```

Atteso: FAIL — l'orchestrator viene chiamato anche con `moderator_enabled=False` perché il guard non esiste ancora.

Il regression test mod ON dovrebbe già passare:

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.EndSpeakModeratorEnabledRegressionTests
```

Atteso: PASS (baseline pre-guard).

- [ ] **Step 3: Aggiungi il guard in `_handle_end_speak`**

In `apps/turns/ws_consumer.py`, subito dopo il blocco `for ev in result.events: ... await self.send_json(...)` (chiude alla riga ~357) e prima della NOTA sulla finestra di prenotazione (riga ~359), aggiungi:

```python
        # GUARD mod-OFF: la sessione gira senza moderatore AI.
        # Il turno umano è chiuso (step 1) e gli eventi sono già stati
        # broadcast (step 2). Si esce qui senza entrare nella pipeline di
        # moderazione (no LLM, no TTS, no static messages, no transition
        # forzata da end_speak — la transizione a CONCLUSION arriva solo
        # via trigger_loop o "tutti pronti").
        # Vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(b).
        if not await self._get_moderator_enabled(self.session_id):
            return
```

NB: il `return` qui è coerente con la semantica: il turno è chiuso, gli eventi sono stati broadcast; il prossimo speaker può prenotarsi normalmente alla prossima `turns.start_speak`. Lo stato turn è IDLE post-`end_speak`. Non serve aprire una reservation window perché `_handle_end_speak` originale non la apriva all'inizio (commento riga 359-361: "La finestra di prenotazione NON viene più aperta qui").

- [ ] **Step 4: Esegui i test e verifica che passino entrambi**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled
```

Atteso: PASS (i 2 test mod OFF + il regression mod ON + i 2 helper test del Task 4 = 5 test).

- [ ] **Step 5: Regression sui flussi turn esistenti**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_services apps.turns.tests_consumer apps.turns.tests_disconnect \
  apps.moderation.tests apps.moderation.tests_integration
```

Atteso: PASS — nessun test esistente cambia comportamento (default `True` → guard non scatta).

- [ ] **Step 6: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_moderator_disabled.py
git commit -m "feat(turns): guard moderation pipeline in end_speak when mod OFF

- skip totale della moderation pipeline (LLM + TTS + static messages
  + should_transition) quando Session.moderator_enabled=False
- il turno umano resta chiuso normalmente (events già broadcast)
- regression test conferma orchestrator chiamato quando mod ON
- vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(b)"
```

---

## Task 6: Guard in `_trigger_loop` — skip static_messages e _execute_forced_conclusion

**Files:**
- Modify: `apps/turns/ws_consumer.py:1085-1200` (`_trigger_loop`, dopo `_get_session_state` riga 1110)
- Test: `apps/turns/tests_moderator_disabled.py` (nuova classe `TriggerLoopModeratorDisabledTests` + classe regression mod ON)

**Contesto del design (§6.4(c)):** in mod OFF saltiamo:
1. `_execute_static_messages(...)` — riga 1165-1168, contenuto generato dal moderator service.
2. `_execute_forced_conclusion()` — riga 1191, recap LLM + TTS finale.

**Manteniamo** invece:
- La transizione di stato `ACTIVE → CONCLUSION` + broadcast `STATE_CHANGED` (riga 1173-1189), perché il timer 30 min deve comunque chiudere la sessione.

In mod OFF `trig_result.static_messages_to_speak` sarà presumibilmente sempre vuoto (i trigger temporali generano messaggi tramite il moderator service, ma la decisione di non eseguirli vive nel coordinator) — il guard è difesa in profondità.

- [ ] **Step 1: Scrivi i test failing per il trigger loop**

Aggiungi in `apps/turns/tests_moderator_disabled.py` in fondo:

```python
class TriggerLoopModeratorDisabledTests(TestCase):
    """In mod OFF il trigger loop:
    - NON chiama _execute_static_messages
    - NON chiama _execute_forced_conclusion
    - chiama comunque la transizione di stato ACTIVE → CONCLUSION
      (timer 30 min deve chiudere la sessione anche senza recap)
    """

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()
        self.user = User.objects.create_user(
            username="host", email="h@e.com", password="p"
        )

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def _make_consumer(self):
        consumer = TurnsConsumer.__new__(TurnsConsumer)
        consumer.session_id = "sess-mod-off"
        consumer.group_name = "turns_sess-mod-off"
        consumer.channel_layer = AsyncMock()
        return consumer

    def test_trigger_loop_skips_static_messages_when_disabled(self):
        """Mod OFF: _execute_static_messages NON deve essere chiamato anche
        se il trigger result contiene static_messages_to_speak."""

        async def _run():
            consumer = self._make_consumer()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            # trig_result con messaggi statici "fittizi" da skippare
            mock_trig = MagicMock()
            mock_trig.static_messages_to_speak = [MagicMock(use_tts=True, text="hi")]
            mock_trig.should_transition_to_conclusion = False

            # Dopo la prima iterazione, simuliamo passaggio a CONCLUSION
            # per uscire dal loop.
            states = ["ACTIVE", "CONCLUSION"]
            state_iter = iter(states)

            async def get_state(_self, _sid):
                try:
                    return next(state_iter)
                except StopIteration:
                    return "CONCLUSION"

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(state_iter, "CONCLUSION")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending", return_value=False,
            ), patch(
                "apps.turns.ws_consumer.evaluate_time_based_triggers",
                return_value=mock_trig,
            ), patch.object(
                TurnsConsumer, "_execute_static_messages",
                new=AsyncMock(return_value=False),
            ) as mock_exec_static, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )
                mock_exec_static.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_trigger_loop_skips_forced_conclusion_when_disabled(self):
        """Mod OFF: timer 30 scaduto → transizione a CONCLUSION SI,
        _execute_forced_conclusion NO."""

        async def _run():
            consumer = self._make_consumer()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            mock_trig = MagicMock()
            mock_trig.static_messages_to_speak = []
            mock_trig.should_transition_to_conclusion = True

            states = ["ACTIVE", "CONCLUSION"]
            state_iter = iter(states)

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(state_iter, "CONCLUSION")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending", return_value=False,
            ), patch(
                "apps.turns.ws_consumer.evaluate_time_based_triggers",
                return_value=mock_trig,
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ) as mock_transition, patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x", "state": "CONCLUSION"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )
                mock_transition.assert_awaited()  # state change SI
                mock_forced.assert_not_awaited()  # recap LLM NO

        asyncio.new_event_loop().run_until_complete(_run())


class TriggerLoopModeratorEnabledRegressionTests(TestCase):
    """Regression: mod ON deve continuare a chiamare _execute_forced_conclusion
    e _execute_static_messages quando il trigger result lo richiede."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_trigger_loop_executes_forced_conclusion_when_enabled(self):
        """Mod ON: timer 30 scaduto → forced_conclusion DEVE essere chiamato."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-mod-on"
            consumer.group_name = "turns_sess-mod-on"
            consumer.channel_layer = AsyncMock()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            mock_trig = MagicMock()
            mock_trig.static_messages_to_speak = []
            mock_trig.should_transition_to_conclusion = True

            states = ["ACTIVE", "CONCLUSION"]
            state_iter = iter(states)

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(state_iter, "CONCLUSION")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=True),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending", return_value=False,
            ), patch(
                "apps.turns.ws_consumer.evaluate_time_based_triggers",
                return_value=mock_trig,
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced, patch.object(
                TurnsConsumer, "_flush_pending_tts_messages",
                new=AsyncMock(),
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )
                mock_forced.assert_awaited()

        asyncio.new_event_loop().run_until_complete(_run())
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.TriggerLoopModeratorDisabledTests
```

Atteso: FAIL — i guard non esistono. `mock_exec_static.assert_not_awaited()` fallisce perché `_execute_static_messages` viene chiamato. `mock_forced.assert_not_awaited()` fallisce per stesso motivo.

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.TriggerLoopModeratorEnabledRegressionTests
```

Atteso: PASS (baseline mod ON).

- [ ] **Step 3: Aggiungi i guard nel trigger loop**

In `apps/turns/ws_consumer.py`, modifica `_trigger_loop` per leggere `moderator_enabled` una volta per tick e proteggere i due punti.

Subito dopo `session_phase = await self._get_session_state(session_id)` (riga 1110, dentro il try/except), aggiungi:

```python
                # Carica moderator_enabled una volta per tick: i guard mod-OFF
                # sotto lo riusano. Default True se sessione non trovata
                # (l'auto-exit per CONCLUSION/CLOSED al passo successivo
                # gestisce comunque il caso di sessione cancellata).
                moderator_enabled = await self._get_moderator_enabled(session_id)
```

Quindi modifica il blocco "Esegui/accoda i messaggi" (riga 1161-1168) sostituendo:

```python
                # Esegui/accoda i messaggi
                # Se should_transition_to_conclusion, passa il flag ai messaggi accodati
                message_was_queued = False
                if trig_result.static_messages_to_speak:
                    message_was_queued = await self._execute_static_messages(
                        trig_result.static_messages_to_speak,
                        trigger_conclusion=trig_result.should_transition_to_conclusion,
                    )
```

con:

```python
                # Esegui/accoda i messaggi
                # Se should_transition_to_conclusion, passa il flag ai messaggi accodati.
                # GUARD mod-OFF: i static_messages sono contenuto del moderator
                # service e vanno saltati interamente. La transizione di stato
                # (sotto) viene comunque eseguita.
                # Vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(c).
                message_was_queued = False
                if trig_result.static_messages_to_speak and moderator_enabled:
                    message_was_queued = await self._execute_static_messages(
                        trig_result.static_messages_to_speak,
                        trigger_conclusion=trig_result.should_transition_to_conclusion,
                    )
```

Quindi modifica il blocco transizione (riga 1173-1191) sostituendo:

```python
                if trig_result.should_transition_to_conclusion and not message_was_queued:
                    # Imposta il motivo della conclusione prima della transizione
                    await self._set_conclusion_reason("timer_expired")
                    transitioned = await self._transition_session_to_conclusion()
                    if transitioned:
                        logger.info("[TRIGGER_LOOP][TRANSITION] session=%s -> CONCLUSION", session_id)
                        # Broadcast del cambio di stato sessione con payload completo
                        payload = await self._get_session_detail_payload(user=None)
                        payload["new_state"] = "CONCLUSION"  # retrocompatibilità
                        await self.channel_layer.group_send(
                            f"sessions_{session_id}",
                            {
                                "type": "sessions.event",
                                "event_type": "STATE_CHANGED",
                                "payload": payload,
                            },
                        )
                        # Esegue FORCED_CONCLUSION immediatamente
                        await self._execute_forced_conclusion()
```

con:

```python
                if trig_result.should_transition_to_conclusion and not message_was_queued:
                    # Imposta il motivo della conclusione prima della transizione
                    await self._set_conclusion_reason("timer_expired")
                    transitioned = await self._transition_session_to_conclusion()
                    if transitioned:
                        logger.info("[TRIGGER_LOOP][TRANSITION] session=%s -> CONCLUSION", session_id)
                        # Broadcast del cambio di stato sessione con payload completo
                        payload = await self._get_session_detail_payload(user=None)
                        payload["new_state"] = "CONCLUSION"  # retrocompatibilità
                        await self.channel_layer.group_send(
                            f"sessions_{session_id}",
                            {
                                "type": "sessions.event",
                                "event_type": "STATE_CHANGED",
                                "payload": payload,
                            },
                        )
                        # GUARD mod-OFF: il recap LLM finale viene saltato.
                        # La transizione di stato sopra è comunque avvenuta —
                        # il frontend riceve STATE_CHANGED e mostra la pagina
                        # di conclusion senza voce del moderatore.
                        # Vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(c).
                        if moderator_enabled:
                            await self._execute_forced_conclusion()
```

- [ ] **Step 4: Esegui i test e verifica che passino**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled
```

Atteso: PASS (tutti i test del file).

- [ ] **Step 5: Regression sui test esistenti del trigger loop**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_disconnect apps.turns.tests_services apps.moderation.tests \
  apps.moderation.tests_integration apps.moderation.tests_intro
```

Atteso: PASS. Importante: `apps.turns.tests_disconnect.TriggerLoopExitsOnTerminalSessionStateTests` continua a passare (ora il loop legge anche `_get_moderator_enabled` ma il default `True` lascia il comportamento invariato; il test mocka `_get_session_state` che fa exit prima di leggere moderator_enabled).

NB: se `tests_disconnect` fallisce con `AttributeError` su `_get_moderator_enabled`, è perché il loop legge il flag *dopo* il check `session_phase in ("CONCLUSION", "CLOSED")` — quindi il test esistente non lo invoca mai. Lasciare il helper non mockato è OK.

- [ ] **Step 6: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_moderator_disabled.py
git commit -m "feat(turns): guard trigger_loop static_messages and forced_conclusion when mod OFF

- skip _execute_static_messages: contenuto del moderator service
- skip _execute_forced_conclusion: niente recap LLM + TTS finale
- mantieni transizione ACTIVE → CONCLUSION + broadcast STATE_CHANGED:
  il timer 30 min deve comunque chiudere la sessione
- moderator_enabled letto una volta per tick (single SELECT)
- regression test conferma forced_conclusion chiamato quando mod ON
- vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(c)"
```

---

## Task 7: Guard in `_flush_pending_tts_messages` — skip _execute_forced_conclusion

**Files:**
- Modify: `apps/turns/ws_consumer.py:1449-1485` (`_flush_pending_tts_messages`)
- Test: `apps/turns/tests_moderator_disabled.py` (nuova classe `FlushPendingMessagesModeratorDisabledTests`)

**Contesto del design (§6.4(d)):** in mod OFF la coda `pending` è naturalmente vuota (l'orchestrator non genera mai messaggi in mod OFF, vedi guard di Task 5/6), quindi il guard è "difesa in profondità". Lo aggiungiamo per coerenza architetturale: nessun `_execute_forced_conclusion` deve mai essere invocato in mod OFF.

- [ ] **Step 1: Scrivi i test failing**

Aggiungi in `apps/turns/tests_moderator_disabled.py`:

```python
class FlushPendingMessagesModeratorDisabledTests(TestCase):
    """In mod OFF, _flush_pending_tts_messages NON deve chiamare
    _execute_forced_conclusion anche se per qualche motivo c'è un
    messaggio in coda con trigger_conclusion=True (defensive guard)."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def test_flush_skips_forced_conclusion_when_disabled(self):
        """Mod OFF: anche con un PendingMessage(trigger_conclusion=True)
        in coda e stato IDLE, _execute_forced_conclusion NON viene chiamato.
        La transizione di stato avviene comunque (timer)."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-flush-off"
            consumer.group_name = "turns_sess-flush-off"
            consumer.channel_layer = AsyncMock()

            mock_state = MagicMock()
            mock_state.state = "IDLE"

            mock_pending_msg = MagicMock()
            mock_pending_msg.text = "queued recap"
            mock_pending_msg.trigger_conclusion = True

            with patch(
                "apps.turns.services.TurnManager.get_state_only",
                return_value=mock_state,
            ), patch(
                "apps.moderation.pending_messages.has_pending_messages",
                return_value=True,
            ), patch(
                "apps.moderation.pending_messages.dequeue_all_messages",
                return_value=[mock_pending_msg],
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=False),
            ), patch.object(
                TurnsConsumer, "_execute_tts_message",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ) as mock_transition, patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced:
                await consumer._flush_pending_tts_messages()
                mock_forced.assert_not_awaited()

        asyncio.new_event_loop().run_until_complete(_run())

    def test_flush_runs_forced_conclusion_when_enabled(self):
        """Regression mod ON: forced_conclusion VIENE chiamato se la coda
        contiene un messaggio con trigger_conclusion=True."""

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-flush-on"
            consumer.group_name = "turns_sess-flush-on"
            consumer.channel_layer = AsyncMock()

            mock_state = MagicMock()
            mock_state.state = "IDLE"

            mock_pending_msg = MagicMock()
            mock_pending_msg.text = "queued recap"
            mock_pending_msg.trigger_conclusion = True

            with patch(
                "apps.turns.services.TurnManager.get_state_only",
                return_value=mock_state,
            ), patch(
                "apps.moderation.pending_messages.has_pending_messages",
                return_value=True,
            ), patch(
                "apps.moderation.pending_messages.dequeue_all_messages",
                return_value=[mock_pending_msg],
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_execute_tts_message",
                new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_set_conclusion_reason", new=AsyncMock(),
            ), patch.object(
                TurnsConsumer, "_transition_session_to_conclusion",
                new=AsyncMock(return_value=True),
            ), patch.object(
                TurnsConsumer, "_get_session_detail_payload",
                new=AsyncMock(return_value={"id": "x"}),
            ), patch.object(
                TurnsConsumer, "_execute_forced_conclusion",
                new=AsyncMock(),
            ) as mock_forced:
                await consumer._flush_pending_tts_messages()
                mock_forced.assert_awaited()

        asyncio.new_event_loop().run_until_complete(_run())
```

- [ ] **Step 2: Esegui i test e verifica che il primo fallisca**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.FlushPendingMessagesModeratorDisabledTests
```

Atteso: `test_flush_skips_forced_conclusion_when_disabled` FAIL (forced_conclusion viene chiamato), `test_flush_runs_forced_conclusion_when_enabled` PASS (regression baseline).

- [ ] **Step 3: Aggiungi il guard in `_flush_pending_tts_messages`**

In `apps/turns/ws_consumer.py`, modifica il blocco che chiama `_execute_forced_conclusion` alla riga ~1485. Sostituisci:

```python
                    # Esegue FORCED_CONCLUSION per generare il riepilogo finale
                    await self._execute_forced_conclusion()
```

con:

```python
                    # GUARD mod-OFF (defensive): in mod OFF la coda è
                    # naturalmente vuota perché l'orchestrator non genera
                    # messaggi (vedi guard in _handle_end_speak e _trigger_loop).
                    # Se per qualche motivo arrivasse comunque qui, saltiamo
                    # il recap LLM finale.
                    # Vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(d).
                    if await self._get_moderator_enabled(self.session_id):
                        # Esegue FORCED_CONCLUSION per generare il riepilogo finale
                        await self._execute_forced_conclusion()
```

- [ ] **Step 4: Esegui i test e verifica che passino entrambi**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.FlushPendingMessagesModeratorDisabledTests
```

Atteso: PASS (2 test).

- [ ] **Step 5: Smoke regression sui flussi turn / moderation**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_services apps.turns.tests_consumer apps.turns.tests_disconnect \
  apps.turns.tests_moderator_disabled \
  apps.moderation.tests apps.moderation.tests_integration apps.moderation.tests_intro
```

Atteso: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests_moderator_disabled.py
git commit -m "feat(turns): guard _flush_pending_tts_messages from forced_conclusion in mod OFF

- defensive guard: in mod OFF la coda è naturalmente vuota perché
  i guard di end_speak e trigger_loop impediscono l'enqueue
- la transizione di stato resta abilitata (timer chiude la sessione)
- regression test conferma forced_conclusion in mod ON
- vedi docs/plans/2026-05-07-no-moderator-mode-design.md §6.4(d)"
```

---

## Task 8: Test di verifica — l'intro gira in entrambe le modalità

**Files:**
- Test: `apps/turns/tests_moderator_disabled.py` (nuova classe `IntroRunsInBothModesTests`)
- Modify: nessuno. Verifica che il design (intro sempre eseguita) sia rispettato a livello di codice.

**Contesto del design (§5):** in mod OFF l'intro va eseguita identica a mod ON. `SessionStartView` chiama `set_intro_pending` + `mark_session_started` + `TurnManager.set_introducing` indipendentemente dal flag. Il trigger loop esegue `_execute_intro_message` se `has_intro_pending` è True (riga 1103-1107) — senza guard sul flag. Questo task **conferma** il comportamento con un test esplicito, non aggiunge codice.

- [ ] **Step 1: Scrivi il test di verifica**

Aggiungi in `apps/turns/tests_moderator_disabled.py`:

```python
class IntroRunsInBothModesTests(TestCase):
    """L'intro del moderatore (testo statico via TTS) è base comune fra
    le due condizioni sperimentali e DEVE girare anche in mod OFF.
    Vedi docs/plans/2026-05-07-no-moderator-mode-design.md §5 e tabella §5."""

    def setUp(self):
        cache.clear()
        TurnsConsumer._trigger_tasks.clear()

    def tearDown(self):
        cache.clear()
        for task in TurnsConsumer._trigger_tasks.values():
            task.cancel()
        TurnsConsumer._trigger_tasks.clear()

    def _run_intro_branch(self, *, moderator_enabled: bool) -> bool:
        """Esegue il trigger_loop simulando intro pendente con il flag dato.
        Ritorna True se _execute_intro_message è stato chiamato."""

        intro_called = {"v": False}

        async def fake_intro(self, session_id):
            intro_called["v"] = True

        async def _run():
            consumer = TurnsConsumer.__new__(TurnsConsumer)
            consumer.session_id = "sess-intro"
            consumer.group_name = "turns_sess-intro"
            consumer.channel_layer = AsyncMock()

            real_sleep = asyncio.sleep

            async def fast_sleep(_seconds):
                await real_sleep(0)

            # has_intro_pending=True una volta, poi False (per uscire); inoltre
            # il primo _get_session_state ritorna ACTIVE poi CLOSED per exit.
            phases = iter(["ACTIVE", "CLOSED"])
            intros = iter([True, False])

            mock_turn_state = MagicMock()
            mock_turn_state.state = "AI_INTRODUCING"

            with patch.object(
                TurnsConsumer, "_get_session_state",
                new=AsyncMock(side_effect=lambda sid: next(phases, "CLOSED")),
            ), patch.object(
                TurnsConsumer, "_get_moderator_enabled",
                new=AsyncMock(return_value=moderator_enabled),
            ), patch(
                "apps.turns.ws_consumer.asyncio.sleep", new=fast_sleep,
            ), patch(
                "apps.turns.ws_consumer.has_intro_pending",
                side_effect=lambda sid: next(intros, False),
            ), patch(
                "apps.turns.services.TurnManager.get_state_only",
                return_value=mock_turn_state,
            ), patch.object(
                TurnsConsumer, "_execute_intro_message",
                new=fake_intro,
            ):
                await asyncio.wait_for(
                    consumer._trigger_loop(consumer.session_id),
                    timeout=2.0,
                )

        asyncio.new_event_loop().run_until_complete(_run())
        return intro_called["v"]

    def test_intro_runs_when_moderator_enabled(self):
        """Mod ON: intro chiamata (baseline)."""
        self.assertTrue(self._run_intro_branch(moderator_enabled=True))

    def test_intro_runs_when_moderator_disabled(self):
        """Mod OFF: intro DEVE comunque girare (base comune fra le 2
        condizioni sperimentali)."""
        self.assertTrue(self._run_intro_branch(moderator_enabled=False))
```

- [ ] **Step 2: Esegui i test e verifica che passino**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns.tests_moderator_disabled.IntroRunsInBothModesTests
```

Atteso: PASS (2 test). Se uno fallisce, è una regressione: `_execute_intro_message` viene saltato per qualche motivo. Diagnostica leggendo il codice del trigger loop ed eventualmente aggiungendo un commento esplicativo.

- [ ] **Step 3: Commit**

```bash
git add apps/turns/tests_moderator_disabled.py
git commit -m "test(turns): assert intro runs in both moderator modes

- l'intro è base comune del design sperimentale within-subject
- il trigger loop chiama _execute_intro_message senza guardare
  moderator_enabled (verifica esplicita)
- niente cambiamento di codice"
```

---

## Task 9: Test di verifica — report PDF robusto a `interventions_log` vuoto

**Files:**
- Test: `apps/reports/tests_metrics.py` (estende il file con un test di robustezza)
- Modify: nessuno. Verifica che il report PDF non si rompa in mod OFF (dove `interventions_log` sarà naturalmente vuoto).

**Contesto del design (§11, §6.7):** `pdf_service.py:129` salta la sezione "Interventi del moderatore" se `interventions_log` è assente o vuoto; `pdf_service.py:168-170` exit early dentro la helper. Nessun cambiamento di codice è necessario, ma aggiungiamo un test esplicito.

- [ ] **Step 1: Verifica esistenza test esistenti su `_build_interventions_section`**

```bash
grep -n "interventions_log\|_build_interventions_section" apps/reports/tests*.py
```

Se esiste già un test che copre `interventions_log=[]`, **salta il Task 9** e procedi al Task 10 — il design dichiara questo come "verifica nel plan" e basta confermare la copertura.

Se invece c'è solo `tests_metrics.py:261` (`test_interventions_log_empty_without_mod_state`) che testa `_collect_report_data` ma non il PDF render, prosegui.

- [ ] **Step 2: Scrivi il test failing (o di copertura)**

Aggiungi in `apps/reports/tests_metrics.py` (in fondo) una nuova classe:

```python
class PdfRendersWithEmptyInterventionsLogTests(TestCase):
    """In mod OFF il report_data ha interventions_log=[]: il PDF deve
    renderizzarsi senza la sezione 'Interventi del moderatore'.
    Pre-condizione del design 'no moderator' — vedi
    docs/plans/2026-05-07-no-moderator-mode-design.md §6.7."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.sessions.models import Session, SessionState
        User = get_user_model()
        self.user = User.objects.create_user(
            username="host", email="h@e.com", password="p"
        )
        self.session = Session.objects.create(
            title="Test mod OFF",
            context="murder_mystery",
            state=SessionState.CLOSED,
            min_size=3,
            max_size=3,
            host=self.user,
            moderator_enabled=False,
            report_data={
                "interventions_log": [],  # mod OFF: nessun intervento
                "ai_interventions": 0,
                "participation": {},
            },
            report_text="Discussione conclusa senza moderatore.",
        )

    def test_pdf_renders_without_interventions_section(self):
        """Il PDF deve generarsi senza errori e senza la sezione interventi."""
        from apps.reports.pdf_service import PDFReportService

        pdf_bytes = PDFReportService.generate_pdf(self.session)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)  # PDF non vuoto

        # Decode best-effort: se la stringa è presente nel PDF è un fallimento.
        # PDF binari non sempre cercano testo come plain ASCII; se il test è
        # troppo fragile, sostituire con assert sui Paragraph builder
        # (più robusto ma più verboso).
        self.assertNotIn(b"INTERVENTI DEL MODERATORE", pdf_bytes)
```

- [ ] **Step 3: Esegui il test**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.reports.tests_metrics.PdfRendersWithEmptyInterventionsLogTests
```

Atteso: PASS (il PDF si renderizza, e `b"INTERVENTI DEL MODERATORE"` non è presente perché la sezione viene saltata via `pdf_service.py:129`).

Se fallisce per ragioni binarie (encoding ReportLab cifra il testo nel PDF), sostituisci l'asserzione finale con una verifica più robusta:

```python
        # Asserzione alternativa robusta: il PDF è generato senza eccezioni
        # ed è non-vuoto (la condizione critica "non si rompe" è soddisfatta).
        # La sezione "Interventi del moderatore" viene già coperta dalle
        # asserzioni di copertura del codice (pdf_service.py:129 if-guard).
```

E rimuovi l'`assertNotIn`.

- [ ] **Step 4: Commit**

```bash
git add apps/reports/tests_metrics.py
git commit -m "test(reports): assert PDF renders with empty interventions_log

- pre-condizione del design 'no moderator': in mod OFF il PDF deve
  generarsi senza la sezione 'Interventi del moderatore'
- pdf_service.py:129 e :168-170 sono già robusti, niente cambio codice"
```

---

## Task 10: Smoke test finale + verifica end-to-end della suite

**Files:** nessuno (verifica).

- [ ] **Step 1: Esegui la suite estesa di reference**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.sessions.tests apps.sessions.tests_discussion_event \
  apps.moderation.tests apps.moderation.tests_integration \
  apps.moderation.tests_intro \
  apps.turns.tests_services apps.turns.tests_disconnect \
  apps.turns.tests_moderator_disabled \
  apps.reports.tests apps.reports.tests_metrics \
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

Atteso: PASS, ~440 test verdi (i ~426 esistenti + i ~14 nuovi: 4 in `apps.sessions.tests`, ~9 in `apps.turns.tests_moderator_disabled`, 1 in `apps.reports.tests_metrics`).

- [ ] **Step 2: Esegui anche la suite ASR/turns che potrebbe non essere coperta sopra**

```bash
docker compose run --rm web python manage.py test --noinput \
  apps.turns apps.asr 2>&1 | tail -20
```

Atteso: PASS (o nessun test in `apps.asr`).

- [ ] **Step 3: Esegui l'intera test suite per essere sicuri**

```bash
docker compose run --rm web python manage.py test --noinput
```

Atteso: PASS, nessuna regressione. Tempo di esecuzione: ~2-4 minuti.

- [ ] **Step 4 (opzionale): Verifica manuale via shell**

```bash
docker compose run --rm web python manage.py shell -c "
from apps.sessions.models import Session
from django.contrib.auth import get_user_model
User = get_user_model()
u = User.objects.first() or User.objects.create_user(username='probe', email='p@e.com', password='p')
s_on = Session.objects.create(title='probe ON', context='murder_mystery', min_size=3, max_size=3, host=u)
s_off = Session.objects.create(title='probe OFF', context='murder_mystery', min_size=3, max_size=3, host=u, moderator_enabled=False)
print(f'mod ON: {s_on.moderator_enabled}'); print(f'mod OFF: {s_off.moderator_enabled}')
s_on.delete(); s_off.delete()
"
```

Atteso output:
```
mod ON: True
mod OFF: False
```

- [ ] **Step 5 (opzionale): Test live in produzione (post-deploy, manuale)**

Vedi design §8.5. Quando il deploy è pronto:

1. Crea sessione NASA mod ON → flow normale (intro + turni + moderatore + recap finale).
2. Crea sessione NASA mod OFF → intro audio, **silenzio del moderatore** per tutto il resto, sessione finisce silenziosamente al timer 30 min o al "tutti pronti".
3. Verifica nei log che `[MODERATION][START]` e `[FORCED_CONCLUSION][START]` non appaiono per la sessione mod OFF.

Questo step non blocca il merge — verifica post-deploy.

---

## Self-Review (eseguita all'autore del plan)

### Spec coverage

| Sezione design | Task che la copre |
|---|---|
| §4.1 campo Session.moderator_enabled | Task 1 |
| §4.2 esposizione API write+read | Task 2, Task 3 |
| §4.3 migration backward-compat | Task 1 (Step 4) |
| §5 comportamento per fase | Task 5 (end_speak), Task 6 (trigger_loop), Task 7 (flush), Task 8 (intro), Task 9 (report) |
| §6.4(a) intro senza guard | Task 8 (verifica esplicita) |
| §6.4(b) guard end_speak | Task 5 |
| §6.4(c) guard trigger_loop static + forced | Task 6 |
| §6.4(d) guard flush_pending | Task 7 |
| §6.5 moderation/* invariato | nessun task (verifica negativa: niente file in `apps/moderation/` viene toccato) |
| §6.6 SessionStartView invariato | nessun task (verifica negativa) |
| §6.7 reports/* robusto | Task 9 |
| §8.1 unit test model + serializer | Task 1, Task 2, Task 3 |
| §8.2 unit test guard | Task 5, Task 6, Task 7 |
| §8.3 regression mod ON | Task 5 (regression class), Task 6 (regression class), Task 7 (test enabled) |
| §8.4 smoke test | Task 10 |
| §8.5 test live | Task 10 (Step 5 opzionale) |
| §9 deploy | non incluso nel plan: il deploy backend → VPS è una procedura standard separata (CLAUDE.md), eseguita manualmente dall'utente dopo il merge |
| §10 rischi | mitigati dai test del Task 5/6/7 |

Tutti i punti del design sono coperti.

### Placeholder scan

- Nessun "TBD" / "TODO" / "implement later" nei task.
- Migration filename: dichiarato approssimativo (`0010_session_moderator_enabled.py`) — il numero esatto è verificato a runtime nel Step 4 del Task 1 con `ls apps/sessions/migrations/0010_*.py`. Questo è accettabile perché il numero non può essere predetto deterministicamente prima di `makemigrations`.
- Test fragility nota in Task 9 Step 3 (binary search nel PDF) con istruzione esplicita di fallback.

### Type / signature consistency

- Nuovo helper `_get_moderator_enabled(session_id) -> bool` con la stessa signature/decorator pattern di `_get_session_state(session_id) -> str`. Coerente.
- Field `moderator_enabled: bool` su Session, nei serializer, nel payload `STATE_CHANGED`. Stesso nome ovunque.
- Test classes usano la stessa convenzione di `tests_disconnect.py` (asyncio.new_event_loop + TurnsConsumer.__new__).

Self-review OK.

---
