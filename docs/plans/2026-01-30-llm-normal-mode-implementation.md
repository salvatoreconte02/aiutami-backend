# LLM Normal Mode Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the LLM call in "normal" mode with richer input data (turns per participant, scenario info) and a detailed system prompt with clear intervention criteria.

**Architecture:** Add `turns_per_participant` tracking to `ModerationState`, pass structured input to the LLM with participant turn counts, and create a dedicated system prompt builder that provides specific intervention criteria (monopolization, exclusion, off-topic, conflict, direct request).

**Tech Stack:** Python, Django, Redis (via Django cache), Azure OpenAI

**Design Document:** `docs/plans/2026-01-30-llm-normal-mode-redesign.md`

---

## Task 1: Add `turns_per_participant` to ModerationState

**Files:**
- Modify: `apps/moderation/state.py:16-38` (ModerationState dataclass)
- Modify: `apps/moderation/state.py:45-67` (load_moderation_state)
- Modify: `apps/moderation/state.py:70-86` (save_moderation_state)
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py` (after `ModerationStateTests` class, around line 55):

```python
class ModerationStateTurnsPerParticipantTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_initial_state_has_empty_turns_per_participant(self):
        """Initial ModerationState should have empty turns_per_participant dict."""
        state = ModerationState.initial()
        self.assertEqual(state.turns_per_participant, {})

    def test_turns_per_participant_persists_after_save_and_load(self):
        """turns_per_participant should be saved to and loaded from Redis."""
        session_id = "test-session-tpp-1"

        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3, "Lucia": 1}
        save_moderation_state(session_id, state)

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant, {"Mario": 3, "Lucia": 1})
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ModerationStateTurnsPerParticipantTests -v 2`

Expected: FAIL with "ModerationState.__init__() got an unexpected keyword argument 'turns_per_participant'" or "AttributeError: 'ModerationState' object has no attribute 'turns_per_participant'"

**Step 3: Write minimal implementation**

Modify `apps/moderation/state.py`:

In the `ModerationState` dataclass (after line 27), add the field:

```python
    turns_per_participant: dict[str, int]  # {"speaker_name": count}
```

In `initial()` method (after line 37), add:

```python
            turns_per_participant={},
```

In `load_moderation_state()` (after line 66), add:

```python
        turns_per_participant=data.get("turns_per_participant", {}),
```

In `save_moderation_state()` (after line 83), add to the dict:

```python
            "turns_per_participant": state.turns_per_participant,
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ModerationStateTurnsPerParticipantTests -v 2`

Expected: PASS

**Step 5: Run full moderation test suite to check for regressions**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests -v 2`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add apps/moderation/state.py apps/moderation/tests.py
git commit -m "feat(moderation): add turns_per_participant tracking to ModerationState"
```

---

## Task 2: Increment turns_per_participant in handle_human_turn_ended

**Files:**
- Modify: `apps/moderation/service.py:54-127` (handle_human_turn_ended method)
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class TurnsPerParticipantIncrementTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_turns_per_participant_incremented_on_turn_end(self, mock_llm):
        """handle_human_turn_ended should increment turns_per_participant for speaker."""
        session_id = "test-tpp-increment-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        # Initial state with no turns
        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        # First turn from Mario
        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant.get("Mario"), 1)

    @patch.object(ModerationService, '_call_llm')
    def test_turns_per_participant_accumulates(self, mock_llm):
        """Multiple turns from same speaker should accumulate."""
        session_id = "test-tpp-increment-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 2}
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant.get("Mario"), 3)

    @patch.object(ModerationService, '_call_llm')
    def test_turns_per_participant_not_incremented_without_speaker_name(self, mock_llm):
        """If speaker_name is None, turns_per_participant should not change."""
        session_id = "test-tpp-no-name"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name=None,  # No speaker name
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.turns_per_participant, {})
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TurnsPerParticipantIncrementTests -v 2`

Expected: FAIL - turns_per_participant will be empty because we don't increment it yet

**Step 3: Write minimal implementation**

Modify `apps/moderation/service.py`, in `handle_human_turn_ended` method.

After loading state (line 75) and before calling `_call_llm` (line 81), add:

```python
        # Increment turn counter for the speaker
        if speaker_name:
            state.turns_per_participant[speaker_name] = (
                state.turns_per_participant.get(speaker_name, 0) + 1
            )
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TurnsPerParticipantIncrementTests -v 2`

Expected: PASS

**Step 5: Run full test suite**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests -v 2`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): increment turns_per_participant on human turn end"
```

---

## Task 3: Only increment ai_interventions_count for normal mode

**Files:**
- Modify: `apps/moderation/service.py:111-114`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class AIInterventionCountModeTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_normal_mode_increments_ai_intervention_count(self, mock_llm):
        """Normal mode AI intervention should increment ai_interventions_count."""
        session_id = "test-ai-count-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Test intervention",
            "reason": "monopolization",
            "intervention_score": 0.8,
        }

        state = ModerationState.initial()
        state.ai_interventions_count = 0
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,  # normal mode
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.ai_interventions_count, 1)

    @patch.object(ModerationService, '_call_llm')
    def test_forced_summary_does_not_increment_ai_intervention_count(self, mock_llm):
        """Forced summary should NOT increment ai_interventions_count."""
        session_id = "test-ai-count-2"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Summary message",
            "reason": "forced_summary",
            "intervention_score": 1.0,
        }

        state = ModerationState.initial()
        state.ai_interventions_count = 2
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.FORCED_SUMMARY,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        # Should still be 2, not 3
        self.assertEqual(loaded.ai_interventions_count, 2)

    @patch.object(ModerationService, '_call_llm')
    def test_forced_conclusion_does_not_increment_ai_intervention_count(self, mock_llm):
        """Forced conclusion should NOT increment ai_interventions_count."""
        session_id = "test-ai-count-3"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": True,
            "message_to_say": "Conclusion message",
            "reason": "forced_conclusion",
            "intervention_score": 1.0,
        }

        state = ModerationState.initial()
        state.ai_interventions_count = 3
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="CONCLUSION",
            hard_action=HardModerationAction.FORCED_CONCLUSION,
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        # Should still be 3, not 4
        self.assertEqual(loaded.ai_interventions_count, 3)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.AIInterventionCountModeTests -v 2`

Expected: FAIL - forced_summary and forced_conclusion tests will fail because currently all modes increment the counter

**Step 3: Write minimal implementation**

Modify `apps/moderation/service.py`, change lines 111-114 from:

```python
        # 5) Se l'AI parlerà, aggiornare contatori
        if ai_should_speak:
            state.ai_interventions_count += 1
            state.last_ai_intervention_at = datetime.utcnow()
```

To:

```python
        # 5) Se l'AI parlerà in normal mode, aggiornare contatori
        # (forced_summary e forced_conclusion non consumano il budget interventi)
        if ai_should_speak and mode == "normal":
            state.ai_interventions_count += 1
            state.last_ai_intervention_at = datetime.utcnow()
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.AIInterventionCountModeTests -v 2`

Expected: PASS

**Step 5: Run full test suite**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests -v 2`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "fix(moderation): only increment ai_interventions_count for normal mode"
```

---

## Task 4: Create _build_normal_mode_prompt() method

**Files:**
- Modify: `apps/moderation/service.py` (add new method after line 527)
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class BuildNormalModePromptTests(TestCase):
    def test_build_normal_mode_prompt_exists(self):
        """_build_normal_mode_prompt should exist and return a string."""
        prompt = ModerationService._build_normal_mode_prompt()
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 100)

    def test_build_normal_mode_prompt_contains_intervention_criteria(self):
        """Prompt should contain specific intervention criteria."""
        prompt = ModerationService._build_normal_mode_prompt()

        # Check for intervention criteria
        self.assertIn("monopol", prompt.lower())  # monopolization
        self.assertIn("esclus", prompt.lower())   # exclusion
        self.assertIn("off-topic", prompt.lower())
        self.assertIn("conflitt", prompt.lower()) # conflict

    def test_build_normal_mode_prompt_contains_json_output_spec(self):
        """Prompt should specify JSON output format."""
        prompt = ModerationService._build_normal_mode_prompt()

        self.assertIn("updated_summary", prompt)
        self.assertIn("should_ai_speak", prompt)
        self.assertIn("message_to_say", prompt)
        self.assertIn("intervention_score", prompt)

    def test_build_normal_mode_prompt_contains_score_thresholds(self):
        """Prompt should explain intervention_score thresholds."""
        prompt = ModerationService._build_normal_mode_prompt()

        self.assertIn("0.7", prompt)  # threshold for intervention
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.BuildNormalModePromptTests -v 2`

Expected: FAIL with "AttributeError: type object 'ModerationService' has no attribute '_build_normal_mode_prompt'"

**Step 3: Write minimal implementation**

Add to `apps/moderation/service.py` after `_fallback_forced_conclusion` method (around line 545):

```python
    @classmethod
    def _build_normal_mode_prompt(cls) -> str:
        """System prompt per la modalità normal - criteri dettagliati di intervento."""
        return """Sei il moderatore AI di una discussione di gruppo su AIutami.

## Scenario
I partecipanti stanno giocando a un murder mystery. Il loro obiettivo è discutere gli indizi e scoprire chi è l'assassino.

## Il tuo ruolo
Sei un facilitatore neutro. Non partecipi alla discussione, non dai opinioni sul caso. Il tuo compito è assicurarti che la conversazione sia equilibrata e produttiva.

## Quando intervenire
Intervieni SOLO se:
1. **Monopolizzazione**: Un partecipante ha parlato molti più turni degli altri e continua a dominare
2. **Esclusione**: Un partecipante non ha quasi mai parlato e nessuno lo coinvolge
3. **Off-topic evidente**: La discussione deraglia completamente (es. parlano di cose scollegate dal caso)
4. **Conflitto**: Toni aggressivi, insulti, attacchi personali
5. **Richiesta diretta**: Qualcuno chiede esplicitamente aiuto al moderatore

NON intervenire per:
- Off-topic parziali (aspetta che il gruppo si auto-corregga)
- Silenzi brevi o pause naturali
- Disaccordi civili (sono parte sana della discussione)

## Stile
- Tono: gentile, indiretto, mai autoritario
- Lunghezza: 1-2 frasi (20-30 parole max)
- Esempi: "Lucia, tu cosa ne pensi di questo indizio?" / "Interessante, ma tornando al caso..."

## Come valutare

Analizza:
1. Il campo `participants.turns` - chi ha parlato quanto?
2. Il `last_turn` - c'è qualcosa che richiede intervento?
3. Il `summary` - la discussione sta procedendo verso l'obiettivo?

Assegna un `intervention_score` da 0 a 1:
- 0.0-0.3: Tutto ok, nessun problema
- 0.4-0.6: Situazione da monitorare ma non critica
- 0.7-0.8: Problema evidente, intervento consigliato
- 0.9-1.0: Problema grave (insulti, off-topic totale), intervento necessario

Imposta `should_ai_speak: true` SOLO se `intervention_score >= 0.7`

## Output

Rispondi SEMPRE con un JSON valido:

{
  "updated_summary": "Riassunto aggiornato includendo l'ultimo turno",
  "should_ai_speak": true/false,
  "message_to_say": "Il messaggio da dire (null se should_ai_speak=false)",
  "reason": "monopolization | exclusion | off_topic | conflict | user_request | all_ok",
  "intervention_score": 0.0-1.0
}"""
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.BuildNormalModePromptTests -v 2`

Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): add _build_normal_mode_prompt with detailed intervention criteria"
```

---

## Task 5: Create _build_system_prompt() dispatcher method

**Files:**
- Modify: `apps/moderation/service.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class BuildSystemPromptTests(TestCase):
    def test_build_system_prompt_normal_mode(self):
        """_build_system_prompt('normal') should return normal mode prompt."""
        prompt = ModerationService._build_system_prompt("normal")
        # Should contain intervention criteria specific to normal mode
        self.assertIn("monopol", prompt.lower())

    def test_build_system_prompt_forced_summary_mode(self):
        """_build_system_prompt('forced_summary') should return appropriate prompt."""
        prompt = ModerationService._build_system_prompt("forced_summary")
        self.assertIsInstance(prompt, str)
        # forced_summary uses the existing generic prompt (for now)
        self.assertIn("riassunto", prompt.lower())

    def test_build_system_prompt_forced_conclusion_mode(self):
        """_build_system_prompt('forced_conclusion') should return conclusion prompt."""
        prompt = ModerationService._build_system_prompt("forced_conclusion")
        # Should use existing _build_forced_conclusion_system_prompt
        self.assertIn("conclus", prompt.lower())

    def test_build_system_prompt_unknown_mode_defaults_to_normal(self):
        """Unknown mode should default to normal mode prompt."""
        prompt = ModerationService._build_system_prompt("unknown_mode")
        normal_prompt = ModerationService._build_normal_mode_prompt()
        self.assertEqual(prompt, normal_prompt)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.BuildSystemPromptTests -v 2`

Expected: FAIL with "AttributeError: type object 'ModerationService' has no attribute '_build_system_prompt'"

**Step 3: Write minimal implementation**

Add to `apps/moderation/service.py` after `_build_normal_mode_prompt`:

```python
    @classmethod
    def _build_system_prompt(cls, mode: str) -> str:
        """
        Costruisce il system prompt appropriato in base alla modalità.

        Args:
            mode: "normal", "forced_summary", o "forced_conclusion"

        Returns:
            System prompt string per il modello LLM
        """
        if mode == "normal":
            return cls._build_normal_mode_prompt()
        elif mode == "forced_conclusion":
            return cls._build_forced_conclusion_system_prompt()
        elif mode == "forced_summary":
            # Per forced_summary usa un prompt dedicato al riassunto
            return cls._build_forced_summary_prompt()
        # Fallback a normal mode per modalità sconosciute
        return cls._build_normal_mode_prompt()

    @classmethod
    def _build_forced_summary_prompt(cls) -> str:
        """System prompt per la modalità forced_summary."""
        return """Sei il moderatore AI di una discussione di gruppo su AIutami.

Il tuo compito è generare un breve riassunto della discussione finora.

## Istruzioni

1. Leggi il summary esistente e l'ultimo turno
2. Genera un riassunto aggiornato che includa i nuovi punti emersi
3. Il riassunto deve essere:
   - Neutro e oggettivo
   - Conciso (max 100 parole)
   - Focalizzato sui punti chiave della discussione

## Output

Rispondi SEMPRE con un JSON valido:

{
  "updated_summary": "Il riassunto aggiornato della discussione",
  "should_ai_speak": true,
  "message_to_say": "Breve ricapitolazione verbale dei punti principali (max 50 parole)",
  "reason": "forced_summary",
  "intervention_score": 1.0
}"""
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.BuildSystemPromptTests -v 2`

Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): add _build_system_prompt dispatcher with mode-specific prompts"
```

---

## Task 6: Update _call_llm to use structured input and new system prompt

**Files:**
- Modify: `apps/moderation/service.py:164-303` (_call_llm method)
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class CallLLMStructuredInputTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_azure_client')
    def test_call_llm_sends_structured_input_with_participants(self, mock_client):
        """_call_llm should send structured input including participants.turns."""
        # Setup mock
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        # Create state with turns_per_participant
        turns_per_participant = {"Mario": 5, "Lucia": 2}

        # Call _call_llm with state
        ModerationService._call_llm(
            summary_in="Test summary",
            last_turn="Test turn",
            mode="normal",
            session_phase="ACTIVE",
            speaker_name="Mario",
            turns_per_participant=turns_per_participant,
        )

        # Verify the call was made
        mock_client.return_value.chat.completions.create.assert_called_once()
        call_args = mock_client.return_value.chat.completions.create.call_args

        # Extract the user message content
        messages = call_args[1]['messages']
        user_message = messages[1]['content']
        user_data = json.loads(user_message)

        # Verify structured input
        self.assertIn("participants", user_data)
        self.assertIn("turns", user_data["participants"])
        self.assertEqual(user_data["participants"]["turns"], {"Mario": 5, "Lucia": 2})

    @patch.object(ModerationService, '_build_azure_client')
    def test_call_llm_uses_normal_mode_prompt(self, mock_client):
        """_call_llm in normal mode should use _build_normal_mode_prompt."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Test",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.1,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        ModerationService._call_llm(
            summary_in="Test",
            last_turn="Turn",
            mode="normal",
            session_phase="ACTIVE",
            speaker_name="Mario",
            turns_per_participant={},
        )

        call_args = mock_client.return_value.chat.completions.create.call_args
        messages = call_args[1]['messages']
        system_prompt = messages[0]['content']

        # Should contain intervention criteria from normal mode prompt
        self.assertIn("monopol", system_prompt.lower())
        self.assertIn("intervention_score", system_prompt)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.CallLLMStructuredInputTests -v 2`

Expected: FAIL - _call_llm doesn't accept turns_per_participant parameter yet

**Step 3: Write minimal implementation**

Modify `apps/moderation/service.py`, update `_call_llm` method signature and body.

Change the signature (around line 164):

```python
    @classmethod
    def _call_llm(
        cls,
        *,
        summary_in: str,
        last_turn: str,
        mode: str,
        session_phase: str,
        speaker_name: Optional[str] = None,
        turns_per_participant: Optional[dict[str, int]] = None,
    ) -> dict:
```

Replace the llm_input construction (around lines 187-200) with:

```python
        # 1) Preparazione input strutturato per il modello
        if turns_per_participant is None:
            turns_per_participant = {}

        total_turns = sum(turns_per_participant.values()) if turns_per_participant else 0

        llm_input = {
            "mode": mode,
            "scenario": {
                "type": "murder_mystery",
                "objective": "Discutere gli indizi e scoprire chi è l'assassino",
            },
            "discussion": {
                "summary": summary_in,
                "last_turn": last_turn,
                "last_speaker": speaker_name,
            },
            "participants": {
                "count": len(turns_per_participant) if turns_per_participant else 3,
                "turns": turns_per_participant,
            },
            "session": {
                "phase": session_phase,
                "total_turns": total_turns,
            },
            "language": "it",
        }
```

Replace the system_prompt construction (lines 216-236) with:

```python
            system_prompt = cls._build_system_prompt(mode)
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.CallLLMStructuredInputTests -v 2`

Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): update _call_llm with structured input and mode-specific prompts"
```

---

## Task 7: Update handle_human_turn_ended to pass state to _call_llm

**Files:**
- Modify: `apps/moderation/service.py:81-87` (handle_human_turn_ended)
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class HandleHumanTurnPassesStateTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_call_llm')
    def test_handle_human_turn_passes_turns_per_participant_to_llm(self, mock_llm):
        """handle_human_turn_ended should pass turns_per_participant to _call_llm."""
        session_id = "test-pass-state-1"

        mock_llm.return_value = {
            "updated_summary": "Test summary",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        # Setup state with existing turns
        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3, "Lucia": 1}
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Verify _call_llm was called with turns_per_participant
        mock_llm.assert_called_once()
        call_kwargs = mock_llm.call_args[1]

        # After increment, Mario should have 4 turns
        self.assertIn("turns_per_participant", call_kwargs)
        self.assertEqual(call_kwargs["turns_per_participant"]["Mario"], 4)
        self.assertEqual(call_kwargs["turns_per_participant"]["Lucia"], 1)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.HandleHumanTurnPassesStateTests -v 2`

Expected: FAIL - _call_llm is not being called with turns_per_participant argument

**Step 3: Write minimal implementation**

Modify `apps/moderation/service.py`, update the `_call_llm` call in `handle_human_turn_ended` (around lines 81-87):

```python
        # 2) Chiamare il LLM (ora collegato ad Azure)
        llm_output = cls._call_llm(
            summary_in=state.summary,
            last_turn=last_turn_text,
            mode=mode,
            session_phase=session_phase,
            speaker_name=speaker_name,
            turns_per_participant=state.turns_per_participant,
        )
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.HandleHumanTurnPassesStateTests -v 2`

Expected: PASS

**Step 5: Run full test suite to ensure no regressions**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests -v 2`

Expected: All tests PASS

**Step 6: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): pass turns_per_participant from state to _call_llm"
```

---

## Task 8: Final integration test

**Files:**
- Test: `apps/moderation/tests.py`

**Step 1: Write integration test**

Add to `apps/moderation/tests.py`:

```python
class LLMNormalModeIntegrationTests(TestCase):
    """Integration tests for the complete normal mode flow."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_azure_client')
    def test_full_normal_mode_flow_with_participant_tracking(self, mock_client):
        """Test complete flow: state tracking + structured LLM input + intervention decision."""
        session_id = "test-integration-1"

        # Mock LLM to return intervention when score >= 0.7
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Mario ha dominato la discussione, Lucia non ha parlato",
            "should_ai_speak": True,
            "message_to_say": "Lucia, tu cosa ne pensi?",
            "reason": "exclusion",
            "intervention_score": 0.75,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        # Setup: Mario has spoken 5 times, Lucia 0 times
        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 5, "Lucia": 0}
        save_moderation_state(session_id, state)

        # Mario speaks again (6th turn)
        result = ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Penso che sia stato il maggiordomo!",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.NONE,
            speaker_name="Mario",
        )

        # Verify AI decides to intervene
        self.assertTrue(result.ai_should_speak)
        self.assertEqual(result.ai_message, "Lucia, tu cosa ne pensi?")

        # Verify state was updated
        loaded_state = load_moderation_state(session_id)
        self.assertEqual(loaded_state.turns_per_participant["Mario"], 6)
        self.assertEqual(loaded_state.ai_interventions_count, 1)

        # Verify LLM received structured input
        call_args = mock_client.return_value.chat.completions.create.call_args
        messages = call_args[1]['messages']
        user_message = json.loads(messages[1]['content'])

        self.assertEqual(user_message["participants"]["turns"]["Mario"], 6)
        self.assertEqual(user_message["participants"]["turns"]["Lucia"], 0)
        self.assertEqual(user_message["scenario"]["type"], "murder_mystery")

    @patch.object(ModerationService, '_build_azure_client')
    def test_forced_summary_does_not_use_normal_prompt(self, mock_client):
        """Forced summary should use its own prompt, not the normal mode prompt."""
        session_id = "test-integration-2"

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Riassunto della discussione",
            "should_ai_speak": True,
            "message_to_say": "Ecco il riassunto...",
            "reason": "forced_summary",
            "intervention_score": 1.0,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationService.handle_human_turn_ended(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test",
            session_phase="ACTIVE",
            hard_action=HardModerationAction.FORCED_SUMMARY,
            speaker_name="Mario",
        )

        # Verify prompt was for forced_summary (should not contain "monopol")
        call_args = mock_client.return_value.chat.completions.create.call_args
        system_prompt = call_args[1]['messages'][0]['content']

        # forced_summary prompt should mention "riassunto" but not intervention criteria
        self.assertIn("riassunto", system_prompt.lower())
        # It should NOT contain detailed intervention criteria like monopolization
        self.assertNotIn("monopol", system_prompt.lower())
```

**Step 2: Run integration test**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.LLMNormalModeIntegrationTests -v 2`

Expected: PASS

**Step 3: Run full test suite**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests -v 2`

Expected: All tests PASS

**Step 4: Commit**

```bash
git add apps/moderation/tests.py
git commit -m "test(moderation): add integration tests for LLM normal mode redesign"
```

---

## Task 9: Update moderation documentation

**Files:**
- Modify: `docs/documentazione_moderazione.md`

**Step 1: Update documentation**

Add section documenting the normal mode LLM behavior:

```markdown
## Modalità Normal - Criteri di Intervento

In modalità "normal" (ogni turno umano durante fase ACTIVE), l'LLM riceve dati strutturati:

### Input all'LLM

```json
{
  "mode": "normal",
  "scenario": {
    "type": "murder_mystery",
    "objective": "Discutere gli indizi e scoprire chi è l'assassino"
  },
  "discussion": {
    "summary": "Riassunto cumulativo",
    "last_turn": "Trascrizione ultimo turno",
    "last_speaker": "Nome speaker"
  },
  "participants": {
    "count": 4,
    "turns": {"Mario": 5, "Lucia": 2, "Paolo": 1, "Anna": 0}
  },
  "session": {
    "phase": "ACTIVE",
    "total_turns": 8
  }
}
```

### Criteri di Intervento

L'LLM interviene solo se rileva:
1. **Monopolizzazione**: Un partecipante ha parlato molto più degli altri
2. **Esclusione**: Un partecipante non ha quasi mai parlato
3. **Off-topic evidente**: Discussione completamente scollegata dal caso
4. **Conflitto**: Toni aggressivi, insulti, attacchi personali
5. **Richiesta diretta**: Qualcuno chiede aiuto al moderatore

### Filtri Backend

Dopo la decisione LLM, il backend applica (solo per mode=normal):
- Soglia score: >= 0.7 per parlare
- Max interventi: 10 per sessione
- Cooldown: 30 secondi tra interventi
- Fase: solo ACTIVE

Gli interventi forced_summary e forced_conclusion NON incrementano i contatori.
```

**Step 2: Commit**

```bash
git add docs/documentazione_moderazione.md
git commit -m "docs(moderation): document normal mode LLM criteria and structured input"
```

---

## Checklist Implementazione

- [x] Task 1: Add `turns_per_participant` to ModerationState
- [x] Task 2: Increment turns_per_participant in handle_human_turn_ended
- [x] Task 3: Only increment ai_interventions_count for normal mode
- [x] Task 4: Create _build_normal_mode_prompt() method
- [x] Task 5: Create _build_system_prompt() dispatcher method
- [x] Task 6: Update _call_llm with structured input and new system prompt
- [x] Task 7: Update handle_human_turn_ended to pass state to _call_llm
- [x] Task 8: Final integration test
- [x] Task 9: Update moderation documentation
