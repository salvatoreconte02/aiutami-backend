# FORCED_SUMMARY Trigger Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor FORCED_SUMMARY trigger to use a dedicated LLM call with hybrid behavior (problem detection + summary recap), following the same architecture as FORCED_CONCLUSION.

**Architecture:** Create dedicated `call_llm_for_summary()` method in `ModerationService` with murder mystery-aware prompt. Modify `ModerationOrchestrator` to bifurcate: FORCED_SUMMARY triggers the new method directly, while normal mode continues as before. Both paths update the summary and manage counters correctly.

**Tech Stack:** Python, Django, Azure OpenAI, Redis (for state), unittest with mocks

---

## Task 1: Add call_llm_for_summary Method

**Files:**
- Modify: `apps/moderation/service.py:409-550` (add new methods after `call_llm_for_conclusion`)
- Test: `apps/moderation/tests.py` (add new test class)

**Step 1: Write the failing test for call_llm_for_summary**

Add to `apps/moderation/tests.py`:

```python
class CallLLMForSummaryTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch.object(ModerationService, '_build_azure_client')
    def test_call_llm_for_summary_returns_expected_structure(self, mock_client):
        """call_llm_for_summary should return dict with updated_summary, message_to_say, correction_reason."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps({
            "updated_summary": "Updated summary",
            "message_to_say": "Recap message",
            "correction_reason": None,
        })
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = ModerationService.call_llm_for_summary(
            summary_in="Previous summary",
            last_turn_text="Mario said something about Eddie",
            last_turn_speaker="Mario",
            participants_turns={"Mario": 5, "Lucia": 3, "Paolo": 2},
            total_turns=10,
        )

        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIn("correction_reason", result)
        self.assertIsNotNone(result["message_to_say"])
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.CallLLMForSummaryTests.test_call_llm_for_summary_returns_expected_structure -v 2`
Expected: FAIL with "AttributeError: type object 'ModerationService' has no attribute 'call_llm_for_summary'"

**Step 3: Write minimal implementation**

Add to `apps/moderation/service.py` after `_fallback_forced_conclusion` method (around line 551):

```python
    # -------------------------------------------------------------------------
    # FORCED_SUMMARY dedicated LLM call
    # -------------------------------------------------------------------------

    @classmethod
    def call_llm_for_summary(
        cls,
        *,
        summary_in: str,
        last_turn_text: str,
        last_turn_speaker: Optional[str],
        participants_turns: dict[str, int],
        total_turns: int,
    ) -> dict:
        """
        Chiamata LLM dedicata per FORCED_SUMMARY.

        A differenza di _call_llm(), usa un prompt specifico per murder mystery
        che combina:
        1. Valutazione problemi (monopolizzazione, esclusione, off-topic, conflitto)
        2. Ricapitolazione periodica degli indizi

        Returns dict with:
        - updated_summary
        - message_to_say
        - correction_reason (monopolization|exclusion|off_topic|conflict|null)
        """
        logger.info(
            "[MODERATION][LLM][SUMMARY_REQUEST] speaker=%s total_turns=%d",
            last_turn_speaker,
            total_turns,
        )

        llm_input = {
            "mode": "forced_summary",
            "summary_in": summary_in,
            "last_turn": {
                "speaker": last_turn_speaker,
                "text": last_turn_text,
            },
            "participants": {
                "count": len(participants_turns),
                "names": list(participants_turns.keys()),
                "turns": participants_turns,
            },
            "session": {
                "total_turns": total_turns,
            },
            "scenario": {
                "type": "murder_mystery",
                "objective": "Scoprire chi è l'assassino tra i sospettati",
            },
            "language": "it",
        }

        try:
            client = cls._build_azure_client()
            deployment = os.environ.get("AZURE_OPENAI_MODEL", "gpt-4o-mini")

            system_prompt = cls._build_forced_summary_system_prompt()

            response = client.chat.completions.create(
                model=deployment,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(llm_input, ensure_ascii=False)},
                ],
                temperature=0.4,
                max_tokens=512,
            )

            raw_output = response.choices[0].message.content
            if isinstance(raw_output, list):
                raw_output = "".join(part.get("text", "") for part in raw_output)

        except Exception as e:
            logger.warning("[MODERATION][LLM][SUMMARY_ERROR] error=%s", str(e))
            return cls._fallback_forced_summary(summary_in, last_turn_text)

        try:
            parsed = json.loads(raw_output)
        except Exception as e:
            logger.warning(
                "[MODERATION][LLM][SUMMARY_PARSE_ERROR] raw=%r error=%s",
                raw_output, str(e)
            )
            return cls._fallback_forced_summary(summary_in, last_turn_text)

        logger.info(
            "[MODERATION][LLM][SUMMARY_RESPONSE] correction=%s message=%r",
            parsed.get("correction_reason"),
            (parsed.get("message_to_say", "") or "")[:50],
        )

        return {
            "updated_summary": parsed.get("updated_summary", summary_in),
            "message_to_say": parsed.get("message_to_say"),
            "correction_reason": parsed.get("correction_reason"),
        }
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.CallLLMForSummaryTests.test_call_llm_for_summary_returns_expected_structure -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): add call_llm_for_summary method"
```

---

## Task 2: Add Dedicated System Prompt for FORCED_SUMMARY

**Files:**
- Modify: `apps/moderation/service.py` (replace existing `_build_forced_summary_prompt`)
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class ForcedSummarySystemPromptTests(TestCase):
    def test_forced_summary_system_prompt_contains_murder_mystery_context(self):
        """FORCED_SUMMARY prompt should contain murder mystery context."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        self.assertIn("murder mystery", prompt.lower())

    def test_forced_summary_system_prompt_contains_hybrid_instructions(self):
        """FORCED_SUMMARY prompt should mention both correction and recap."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        self.assertIn("correzione", prompt.lower())
        self.assertIn("ricapitolazione", prompt.lower())

    def test_forced_summary_system_prompt_contains_output_format(self):
        """FORCED_SUMMARY prompt should specify JSON output with correction_reason."""
        prompt = ModerationService._build_forced_summary_system_prompt()
        self.assertIn("correction_reason", prompt)
        self.assertIn("updated_summary", prompt)
        self.assertIn("message_to_say", prompt)
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedSummarySystemPromptTests -v 2`
Expected: FAIL (current prompt doesn't have murder mystery context or hybrid instructions)

**Step 3: Write implementation**

Replace `_build_forced_summary_prompt` method in `apps/moderation/service.py` (around line 631) with:

```python
    @classmethod
    def _build_forced_summary_system_prompt(cls) -> str:
        """System prompt dedicato per FORCED_SUMMARY con comportamento ibrido."""
        return """Sei il moderatore AI di AIutami, una piattaforma per discussioni di gruppo.

## Scenario
I partecipanti stanno giocando a un murder mystery. Devono discutere gli indizi e scoprire chi è l'assassino.

## Il tuo compito

Genera un messaggio di ricapitolazione periodica. Parla in modo naturale e coinvolgente, come un facilitatore esperto.

### Struttura del messaggio

1. **[Solo se necessario] Correzione gentile** - Se rilevi un problema (monopolizzazione, esclusione, off-topic, conflitto), inizia con un invito delicato a riequilibrare
2. **Ricapitolazione fluida** - Riassumi gli indizi emersi in modo discorsivo, menzionando chi ha sollevato cosa e su quale sospettato
3. **Apertura sul contenuto** - Concludi invitando ad approfondire un aspetto non ancora esplorato

## Criteri per la correzione

Includi una correzione solo se:
- **Monopolizzazione**: un partecipante ha parlato molto più degli altri (guarda il campo `participants.turns`)
- **Esclusione**: qualcuno non ha mai parlato o ha pochissimi turni
- **Off-topic**: discussione lontana dal caso del murder mystery
- **Conflitto**: toni aggressivi nel contenuto dell'ultimo turno

Se non rilevi problemi, vai diretto alla ricapitolazione senza correzione.

## Tono e stile
- Caldo e naturale, come un facilitatore esperto
- Fluido e discorsivo, non a elenco
- Lunghezza: 60-100 parole (30-45 secondi di parlato)

## Output

Rispondi SOLO con un JSON valido:

{
    "updated_summary": "Riassunto aggiornato includendo l'ultimo turno",
    "message_to_say": "Il messaggio vocale completo",
    "correction_reason": "monopolization | exclusion | off_topic | conflict | null"
}

IMPORTANTE: `correction_reason` indica il tipo di problema rilevato. Se non c'è problema, usa null."""
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedSummarySystemPromptTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): add murder mystery-aware FORCED_SUMMARY prompt"
```

---

## Task 3: Add Fallback for FORCED_SUMMARY

**Files:**
- Modify: `apps/moderation/service.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class ForcedSummaryFallbackTests(TestCase):
    def test_fallback_forced_summary_returns_expected_structure(self):
        """_fallback_forced_summary should return dict with required fields."""
        result = ModerationService._fallback_forced_summary(
            summary_in="Previous discussion",
            last_turn_text="Mario mentioned Eddie",
        )

        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIn("correction_reason", result)
        self.assertIsNone(result["correction_reason"])

    def test_fallback_forced_summary_combines_summary_and_turn(self):
        """Fallback should combine summary and last turn in updated_summary."""
        result = ModerationService._fallback_forced_summary(
            summary_in="Summary A",
            last_turn_text="Turn B",
        )

        self.assertIn("Summary A", result["updated_summary"])
        self.assertIn("Turn B", result["updated_summary"])

    def test_fallback_forced_summary_message_invites_discussion(self):
        """Fallback message should invite further discussion."""
        result = ModerationService._fallback_forced_summary(
            summary_in="Test",
            last_turn_text="Test turn",
        )

        self.assertIn("approfondire", result["message_to_say"].lower())
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedSummaryFallbackTests -v 2`
Expected: FAIL with "AttributeError: type object 'ModerationService' has no attribute '_fallback_forced_summary'"

**Step 3: Write implementation**

Add to `apps/moderation/service.py` after `call_llm_for_summary`:

```python
    @classmethod
    def _fallback_forced_summary(cls, summary_in: str, last_turn_text: str) -> dict:
        """
        Comportamento di riserva se la chiamata LLM per summary fallisce.
        """
        combined = f"{summary_in} {last_turn_text}".strip()

        return {
            "updated_summary": combined,
            "message_to_say": (
                "Facciamo il punto della situazione. "
                f"{combined} "
                "Ci sono aspetti che volete approfondire?"
            ),
            "correction_reason": None,
        }
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedSummaryFallbackTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/service.py apps/moderation/tests.py
git commit -m "feat(moderation): add _fallback_forced_summary method"
```

---

## Task 4: Test call_llm_for_summary Uses Fallback on Error

**Files:**
- Test: `apps/moderation/tests.py`

**Step 1: Write the test**

Add to `CallLLMForSummaryTests` class in `apps/moderation/tests.py`:

```python
    @patch.object(ModerationService, '_build_azure_client')
    def test_call_llm_for_summary_uses_fallback_on_api_error(self, mock_client):
        """call_llm_for_summary should use fallback when Azure API fails."""
        mock_client.return_value.chat.completions.create.side_effect = Exception("API Error")

        result = ModerationService.call_llm_for_summary(
            summary_in="Previous summary",
            last_turn_text="Last turn",
            last_turn_speaker="Mario",
            participants_turns={"Mario": 3},
            total_turns=3,
        )

        # Should return fallback structure
        self.assertIn("updated_summary", result)
        self.assertIn("message_to_say", result)
        self.assertIn("approfondire", result["message_to_say"].lower())
        self.assertIsNone(result["correction_reason"])

    @patch.object(ModerationService, '_build_azure_client')
    def test_call_llm_for_summary_uses_fallback_on_invalid_json(self, mock_client):
        """call_llm_for_summary should use fallback when LLM returns invalid JSON."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Not valid JSON"
        mock_client.return_value.chat.completions.create.return_value = mock_response

        result = ModerationService.call_llm_for_summary(
            summary_in="Previous summary",
            last_turn_text="Last turn",
            last_turn_speaker="Mario",
            participants_turns={"Mario": 3},
            total_turns=3,
        )

        self.assertIn("approfondire", result["message_to_say"].lower())
```

**Step 2: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.CallLLMForSummaryTests -v 2`
Expected: PASS (implementation already handles these cases)

**Step 3: Commit**

```bash
git add apps/moderation/tests.py
git commit -m "test(moderation): add fallback tests for call_llm_for_summary"
```

---

## Task 5: Modify Orchestrator to Bifurcate on FORCED_SUMMARY

**Files:**
- Modify: `apps/moderation/orchestrator.py`
- Test: `apps/moderation/tests.py`

**Step 1: Write the failing test**

Add to `apps/moderation/tests.py`:

```python
class OrchestratorForcedSummaryBifurcationTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    @patch.object(ModerationService, 'handle_human_turn_ended')
    def test_forced_summary_uses_dedicated_method(self, mock_handle, mock_summary, mock_triggers):
        """When FORCED_SUMMARY triggers, orchestrator should call call_llm_for_summary."""
        session_id = "test-orch-fs-1"

        # Setup trigger to return FORCED_SUMMARY
        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        # Setup summary LLM response
        mock_summary.return_value = {
            "updated_summary": "Updated summary",
            "message_to_say": "Recap message",
            "correction_reason": None,
        }

        # Setup initial state
        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3}
        save_moderation_state(session_id, state)

        decision = ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # call_llm_for_summary should be called
        mock_summary.assert_called_once()
        # handle_human_turn_ended should NOT be called (bifurcation)
        mock_handle.assert_not_called()
        # AI should speak
        self.assertTrue(decision.ai_should_speak)
        self.assertEqual(decision.ai_message, "Recap message")

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    @patch.object(ModerationService, 'handle_human_turn_ended')
    def test_normal_mode_uses_handle_human_turn_ended(self, mock_handle, mock_summary, mock_triggers):
        """When no hard action, orchestrator should call handle_human_turn_ended (normal path)."""
        session_id = "test-orch-normal-1"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.NONE,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        mock_handle.return_value = ModerationResult(
            ai_should_speak=False,
            ai_message=None,
            updated_state=ModerationState.initial(),
        )

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # handle_human_turn_ended should be called (normal path)
        mock_handle.assert_called_once()
        # call_llm_for_summary should NOT be called
        mock_summary.assert_not_called()
```

**Step 2: Run test to verify it fails**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.OrchestratorForcedSummaryBifurcationTests -v 2`
Expected: FAIL (current orchestrator always calls handle_human_turn_ended)

**Step 3: Write implementation**

Modify `apps/moderation/orchestrator.py` `handle_human_turn_end` method:

```python
# apps/moderation/orchestrator.py

from dataclasses import dataclass
from typing import List, Optional

from .state import load_moderation_state, save_moderation_state, ModerationState
from .service import (
    ModerationService,
    ModerationResult,
    HardModerationAction,
)
from .triggers import (
    evaluate_triggers_on_human_turn_end,
    TriggerEvaluationResult,
    StaticMessage,
)


@dataclass
class FullModerationDecision:
    """
    Risultato completo della moderazione alla fine di un turno umano.

    Contiene:
    - static_messages_to_speak: lista di StaticMessage (con flag use_tts)
    - ai_should_speak: se il moderatore AI deve parlare
    - ai_message: contenuto eventuale del messaggio AI
    - hard_action: NONE / FORCED_SUMMARY / FORCED_CONCLUSION
    - should_transition_to_conclusion: se la sessione deve passare a CONCLUSION
    """
    static_messages_to_speak: List[StaticMessage]
    ai_should_speak: bool
    ai_message: Optional[str]
    hard_action: HardModerationAction
    should_transition_to_conclusion: bool = False


class ModerationOrchestrator:
    """
    Punto di ingresso unico per la moderazione alla fine di un turno umano.

    Sequenza gestita:
      1. Carica lo stato corrente di moderazione
      2. Valuta i trigger post–turno (hard + statici)
      3. Biforcazione:
         - FORCED_SUMMARY: chiama call_llm_for_summary
         - Altrimenti: chiama ModerationService.handle_human_turn_ended
      4. Restituisce una FullModerationDecision
    """

    @classmethod
    def handle_human_turn_end(
        cls,
        *,
        session_id: int | str,
        user_id: int | str,
        last_turn_text: str,
        session_phase: str,          # es. "ACTIVE", "CONCLUSION"
        speaker_name: Optional[str] = None,
    ) -> FullModerationDecision:
        """
        Deve essere chiamato subito dopo che un turno umano è
        terminato, durante la finestra di moderazione (microfoni chiusi).
        """

        # 1) Carica stato moderazione
        moderation_state = load_moderation_state(session_id)

        # 2) Trigger post-turno (hard action + messaggi statici)
        trigger_result: TriggerEvaluationResult = evaluate_triggers_on_human_turn_end(
            session_id=session_id,
            user_id=user_id,
            session_phase=session_phase,
            moderation_state=moderation_state,
        )

        # 3) Biforcazione in base al hard_action
        if trigger_result.hard_action == HardModerationAction.FORCED_SUMMARY:
            # FORCED_SUMMARY: usa metodo dedicato
            return cls._handle_forced_summary(
                session_id=session_id,
                last_turn_text=last_turn_text,
                speaker_name=speaker_name,
                moderation_state=moderation_state,
                trigger_result=trigger_result,
            )
        else:
            # Normal path: chiama handle_human_turn_ended
            moderation_result: ModerationResult = ModerationService.handle_human_turn_ended(
                session_id=session_id,
                user_id=user_id,
                last_turn_text=last_turn_text,
                session_phase=session_phase,
                hard_action=trigger_result.hard_action,
                speaker_name=speaker_name,
            )

            return FullModerationDecision(
                static_messages_to_speak=trigger_result.static_messages_to_speak,
                ai_should_speak=moderation_result.ai_should_speak,
                ai_message=moderation_result.ai_message,
                hard_action=trigger_result.hard_action,
                should_transition_to_conclusion=trigger_result.should_transition_to_conclusion,
            )

    @classmethod
    def _handle_forced_summary(
        cls,
        *,
        session_id: int | str,
        last_turn_text: str,
        speaker_name: Optional[str],
        moderation_state: ModerationState,
        trigger_result: TriggerEvaluationResult,
    ) -> FullModerationDecision:
        """
        Gestisce il path FORCED_SUMMARY separatamente.

        1. Incrementa turns_per_participant per lo speaker
        2. Chiama call_llm_for_summary
        3. Aggiorna summary
        4. Reset human_turns_since_last_summary a 0
        5. Salva stato
        """
        # Increment turn counter for the speaker
        if speaker_name:
            moderation_state.turns_per_participant[speaker_name] = (
                moderation_state.turns_per_participant.get(speaker_name, 0) + 1
            )

        # Calculate total turns
        total_turns = sum(moderation_state.turns_per_participant.values())

        # Call dedicated LLM
        llm_result = ModerationService.call_llm_for_summary(
            summary_in=moderation_state.summary,
            last_turn_text=last_turn_text,
            last_turn_speaker=speaker_name,
            participants_turns=moderation_state.turns_per_participant,
            total_turns=total_turns,
        )

        # Update state
        moderation_state.summary = llm_result["updated_summary"]
        moderation_state.human_turns_since_last_summary = 0  # Reset counter

        # Save state
        save_moderation_state(session_id, moderation_state)

        return FullModerationDecision(
            static_messages_to_speak=trigger_result.static_messages_to_speak,
            ai_should_speak=True,  # FORCED_SUMMARY always speaks
            ai_message=llm_result["message_to_say"],
            hard_action=HardModerationAction.FORCED_SUMMARY,
            should_transition_to_conclusion=trigger_result.should_transition_to_conclusion,
        )
```

**Step 4: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.OrchestratorForcedSummaryBifurcationTests -v 2`
Expected: PASS

**Step 5: Commit**

```bash
git add apps/moderation/orchestrator.py apps/moderation/tests.py
git commit -m "feat(moderation): bifurcate orchestrator for FORCED_SUMMARY"
```

---

## Task 6: Test Summary Updates in Both Paths

**Files:**
- Test: `apps/moderation/tests.py`

**Step 1: Write the test**

Add to `apps/moderation/tests.py`:

```python
class SummaryUpdateBothPathsTests(TestCase):
    """Verify summary is always updated in both FORCED_SUMMARY and normal paths."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_updates_summary(self, mock_summary, mock_triggers):
        """FORCED_SUMMARY path should update moderation_state.summary."""
        session_id = "test-summary-fs-1"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        mock_summary.return_value = {
            "updated_summary": "NEW SUMMARY FROM LLM",
            "message_to_say": "Recap",
            "correction_reason": None,
        }

        state = ModerationState.initial()
        state.summary = "OLD SUMMARY"
        state.human_turns_since_last_summary = 3
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.summary, "NEW SUMMARY FROM LLM")
        # Counter should be reset
        self.assertEqual(loaded.human_turns_since_last_summary, 0)

    @patch.object(ModerationService, '_call_llm')
    def test_normal_path_updates_summary(self, mock_llm):
        """Normal path should also update moderation_state.summary."""
        session_id = "test-summary-normal-1"

        mock_llm.return_value = {
            "updated_summary": "UPDATED NORMAL SUMMARY",
            "should_ai_speak": False,
            "message_to_say": None,
            "reason": "all_ok",
            "intervention_score": 0.2,
        }

        state = ModerationState.initial()
        state.summary = "OLD SUMMARY"
        state.human_turns_since_last_summary = 1  # Not enough to trigger FORCED_SUMMARY
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.summary, "UPDATED NORMAL SUMMARY")
        # Counter should be incremented (not reset)
        self.assertEqual(loaded.human_turns_since_last_summary, 2)
```

**Step 2: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.SummaryUpdateBothPathsTests -v 2`
Expected: PASS

**Step 3: Commit**

```bash
git add apps/moderation/tests.py
git commit -m "test(moderation): verify summary updates in both paths"
```

---

## Task 7: Test Turns Counter Increment Before LLM Call

**Files:**
- Test: `apps/moderation/tests.py`

**Step 1: Write the test**

Add to `apps/moderation/tests.py`:

```python
class TurnsCounterIncrementOrderTests(TestCase):
    """Verify turns counter is incremented BEFORE LLM call in both paths."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_increments_turns_before_llm(self, mock_summary, mock_triggers):
        """FORCED_SUMMARY should increment turns BEFORE calling LLM."""
        session_id = "test-turns-order-1"

        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=False,
        )

        captured_turns = {}

        def capture_turns(**kwargs):
            captured_turns.update(kwargs.get("participants_turns", {}))
            return {
                "updated_summary": "Summary",
                "message_to_say": "Message",
                "correction_reason": None,
            }

        mock_summary.side_effect = capture_turns

        state = ModerationState.initial()
        state.turns_per_participant = {"Mario": 3}
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test turn",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # LLM should have received Mario: 4 (incremented BEFORE call)
        self.assertEqual(captured_turns.get("Mario"), 4)
```

**Step 2: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.TurnsCounterIncrementOrderTests -v 2`
Expected: PASS

**Step 3: Commit**

```bash
git add apps/moderation/tests.py
git commit -m "test(moderation): verify turns increment order in FORCED_SUMMARY"
```

---

## Task 8: Test Compatibility with FORCED_CONCLUSION Transition

**Files:**
- Test: `apps/moderation/tests.py`

**Step 1: Write the test**

Add to `apps/moderation/tests.py`:

```python
class ForcedSummaryCompatibilityWithConclusionTests(TestCase):
    """Verify FORCED_SUMMARY doesn't break FORCED_CONCLUSION flow."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('apps.moderation.orchestrator.evaluate_triggers_on_human_turn_end')
    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_preserves_transition_flag(self, mock_summary, mock_triggers):
        """FORCED_SUMMARY path should preserve should_transition_to_conclusion from triggers."""
        session_id = "test-compat-1"

        # Trigger returns FORCED_SUMMARY AND should_transition_to_conclusion=True
        # (edge case: timer expired on same turn as summary)
        mock_triggers.return_value = TriggerEvaluationResult(
            hard_action=HardModerationAction.FORCED_SUMMARY,
            static_messages_to_speak=[],
            should_transition_to_conclusion=True,
        )

        mock_summary.return_value = {
            "updated_summary": "Summary",
            "message_to_say": "Message",
            "correction_reason": None,
        }

        state = ModerationState.initial()
        save_moderation_state(session_id, state)

        decision = ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Test",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # Transition flag should be preserved
        self.assertTrue(decision.should_transition_to_conclusion)

    @patch.object(ModerationService, 'call_llm_for_summary')
    def test_forced_summary_leaves_summary_for_conclusion(self, mock_summary):
        """After FORCED_SUMMARY, summary should be available for FORCED_CONCLUSION."""
        session_id = "test-compat-2"

        mock_summary.return_value = {
            "updated_summary": "Complete discussion summary with all clues",
            "message_to_say": "Recap message",
            "correction_reason": None,
        }

        state = ModerationState.initial()
        state.human_turns_since_last_summary = 3  # Will trigger FORCED_SUMMARY
        save_moderation_state(session_id, state)

        ModerationOrchestrator.handle_human_turn_end(
            session_id=session_id,
            user_id=1,
            last_turn_text="Final clue about Eddie",
            session_phase="ACTIVE",
            speaker_name="Mario",
        )

        # Now FORCED_CONCLUSION can use this summary
        loaded = load_moderation_state(session_id)
        self.assertEqual(loaded.summary, "Complete discussion summary with all clues")

        # call_llm_for_conclusion would receive this summary
        conclusion_result = ModerationService.call_llm_for_conclusion(
            summary_in=loaded.summary,
            conclusion_reason="timer_expired",
        )
        # (This is a smoke test - actual LLM call would be mocked in real test)
```

**Step 2: Run test to verify it passes**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests.ForcedSummaryCompatibilityWithConclusionTests -v 2`
Expected: PASS

**Step 3: Commit**

```bash
git add apps/moderation/tests.py
git commit -m "test(moderation): verify FORCED_SUMMARY compatibility with CONCLUSION"
```

---

## Task 9: Update Documentation

**Files:**
- Modify: `docs/documentazione_moderazione.md`

**Step 1: Update section 4.1**

Replace the `### 4.1 Trigger 7: FORCED_SUMMARY` section in `docs/documentazione_moderazione.md` with:

```markdown
### 4.1 Trigger 7: FORCED_SUMMARY

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Ogni N turni umani (attualmente 4) |
| **Contatore** | `human_turns_since_last_summary` |
| **Modalità** | TTS (chiamata LLM dedicata) |
| **Reset contatore** | Dopo ogni FORCED_SUMMARY |

**Comportamento ibrido:**

FORCED_SUMMARY combina due responsabilità in una sola chiamata LLM:

1. **Valutazione problemi** - Come normal mode, rileva monopolizzazione, esclusione, off-topic, conflitto
2. **Ricapitolazione periodica** - Riassume gli indizi emersi per sospettato nel contesto murder mystery

**Struttura del messaggio generato:**

1. **[Solo se necessario] Correzione gentile** - Se rileva un problema (monopolizzazione, esclusione, off-topic, conflitto)
2. **Ricapitolazione fluida** - Indizi per sospettato, chi ha detto cosa
3. **Apertura sul contenuto** - Invita ad approfondire un aspetto non discusso

**Chiamata LLM:**

| Parametro | Valore |
|-----------|--------|
| Model | `gpt-4o-mini` (o env `AZURE_OPENAI_MODEL`) |
| Temperature | `0.4` |
| Max tokens | `512` |

**Input LLM (JSON):**
```json
{
    "mode": "forced_summary",
    "summary_in": "Riassunto cumulativo (senza ultimo turno)",
    "last_turn": {
        "speaker": "Mario",
        "text": "Secondo me Eddie aveva un movente economico..."
    },
    "participants": {
        "count": 3,
        "names": ["Mario", "Lucia", "Paolo"],
        "turns": {"Mario": 5, "Lucia": 3, "Paolo": 2}
    },
    "session": {
        "total_turns": 10
    },
    "scenario": {
        "type": "murder_mystery",
        "objective": "Scoprire chi è l'assassino tra i sospettati"
    },
    "language": "it"
}
```

**Output LLM (JSON):**
```json
{
    "updated_summary": "Riassunto aggiornato includendo l'ultimo turno",
    "message_to_say": "Il messaggio vocale completo",
    "correction_reason": "monopolization | exclusion | off_topic | conflict | null"
}
```

- `correction_reason` è per logging/analytics, non per filtraggio (trigger mandatory)

**Fallback (se LLM fallisce):**

```python
{
    "updated_summary": f"{summary_in} {last_turn_text}",
    "message_to_say": "Facciamo il punto della situazione. [summary]. Ci sono aspetti che volete approfondire?",
    "correction_reason": None,
}
```

**Gestione stato:**

| Aspetto | Responsabile |
|---------|--------------|
| Incremento `turns_per_participant` | Prima della biforcazione (sempre) |
| Incremento `human_turns_since_last_summary` | Solo se NOT forced_summary |
| Reset `human_turns_since_last_summary` a 0 | Solo se forced_summary |
| Update `summary` | Entrambi i path |
| Salvataggio stato Redis | Entrambi i path |

**Architettura:**

```
ModerationOrchestrator.handle_human_turn_end()
    ↓
evaluate_triggers_on_human_turn_end() → hard_action, should_transition
    ↓
┌─────────────────────────────────────────────────────┐
│ IF hard_action == FORCED_SUMMARY:                   │
│     _handle_forced_summary()                        │
│         → call_llm_for_summary()                    │
│         → reset human_turns_since_last_summary = 0  │
│         → TTS (sempre, mandatory)                   │
├─────────────────────────────────────────────────────┤
│ ELSE:                                               │
│     ModerationService.handle_human_turn_ended()     │
│         → _call_llm() (normal mode)                 │
│         → TTS se score >= 0.7                       │
└─────────────────────────────────────────────────────┘
```
```

**Step 2: Verify documentation renders correctly**

Read the updated documentation to verify markdown is correct.

**Step 3: Commit**

```bash
git add docs/documentazione_moderazione.md
git commit -m "docs(moderation): update FORCED_SUMMARY specification"
```

---

## Task 10: Run Full Test Suite

**Files:**
- None (verification only)

**Step 1: Run all moderation tests**

Run: `docker compose run --rm web python manage.py test apps.moderation -v 2`
Expected: All tests PASS

**Step 2: Run integration tests if available**

Run: `docker compose run --rm web python manage.py test apps.moderation.tests_integration -v 2`
Expected: All tests PASS

**Step 3: Final commit (if any test adjustments needed)**

```bash
git add -A
git commit -m "test(moderation): ensure all tests pass after FORCED_SUMMARY refactor"
```

---

## Checklist finale

- [x] Task 1: Add `call_llm_for_summary()` in service.py
- [x] Task 2: Add `_build_forced_summary_system_prompt()` with murder mystery context
- [x] Task 3: Add `_fallback_forced_summary()` in service.py
- [x] Task 4: Test fallback behavior on errors
- [ ] Task 5: Modify orchestrator.py for bifurcation
- [ ] Task 6: Test summary updates in both paths
- [ ] Task 7: Test turns counter increment order
- [ ] Task 8: Test compatibility with FORCED_CONCLUSION transition
- [ ] Task 9: Update `docs/documentazione_moderazione.md`
- [ ] Task 10: Run full test suite

---

## Costanti di riferimento

```python
SUMMARY_TURNS_INTERVAL = 4  # Poi 6
FORCED_SUMMARY_TEMPERATURE = 0.4
FORCED_SUMMARY_MAX_TOKENS = 512
```
