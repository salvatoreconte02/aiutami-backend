# TTS Moderatore Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implementare la sintesi vocale (TTS) per il moderatore AI, permettendogli di parlare agli utenti via audio WebRTC.

**Architecture:** Azure Speech SDK per TTS streaming, con peer virtuale "AI_MODERATOR" nell'AudioHub. L'audio viene iniettato nel ForwardingAudioTrack esistente e forwardato a tutti i client WebRTC. Fallback a testo se TTS fallisce.

**Tech Stack:** Azure Speech SDK (azure-cognitiveservices-speech), Django Channels, aiortc, Redis

---

## Task 1: Creare modulo TTS base

**Files:**
- Create: `apps/tts/__init__.py`
- Create: `apps/tts/service.py`
- Create: `apps/tts/tests/__init__.py`
- Create: `apps/tts/tests/test_service.py`
- Modify: `aiutami/settings.py:133-137`

**Step 1: Creare directory e init**

```bash
mkdir -p apps/tts/tests
```

**Step 2: Creare `apps/tts/__init__.py`**

```python
# TTS module for AI Moderator voice synthesis
```

**Step 3: Creare `apps/tts/tests/__init__.py`**

```python
# TTS tests
```

**Step 4: Aggiungere setting TTS in `aiutami/settings.py`**

Dopo linea 137 (dopo `AZURE_SPEECH_LANGUAGE`), aggiungere:

```python
AZURE_TTS_VOICE = os.getenv("AZURE_TTS_VOICE", "it-IT-DiegoNeural")
```

**Step 5: Commit struttura base**

```bash
git add apps/tts/__init__.py apps/tts/tests/__init__.py aiutami/settings.py
git commit -m "$(cat <<'EOF'
feat(tts): add TTS module structure and settings

- Create apps/tts module directory
- Add AZURE_TTS_VOICE setting with default it-IT-DiegoNeural

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Implementare TTSService con test

**Files:**
- Create: `apps/tts/service.py`
- Create: `apps/tts/tests/test_service.py`

**Step 1: Scrivere il test per TTSResult**

File: `apps/tts/tests/test_service.py`

```python
"""Tests for TTS service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from apps.tts.service import TTSResult, TTSService


class TestTTSResult:
    """Test TTSResult dataclass."""

    def test_success_result(self):
        result = TTSResult(success=True, duration_ms=1500, error=None)
        assert result.success is True
        assert result.duration_ms == 1500
        assert result.error is None

    def test_failure_result(self):
        result = TTSResult(success=False, duration_ms=None, error="timeout")
        assert result.success is False
        assert result.duration_ms is None
        assert result.error == "timeout"
```

**Step 2: Eseguire test per verificare fallimento**

```bash
docker compose run --rm web python manage.py test apps.tts.tests.test_service.TestTTSResult -v 2
```

Expected: FAIL con "No module named 'apps.tts.service'" o "cannot import name 'TTSResult'"

**Step 3: Implementare TTSResult in `apps/tts/service.py`**

```python
"""
TTS Service - Azure Speech Synthesis per il moderatore AI.

Fornisce sintesi vocale streaming per permettere al moderatore AI
di parlare agli utenti via WebRTC.
"""
from dataclasses import dataclass
from typing import Callable, Awaitable, Optional
import asyncio
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class TTSResult:
    """Risultato della sintesi TTS."""
    success: bool
    duration_ms: Optional[int]
    error: Optional[str]
```

**Step 4: Eseguire test per verificare pass**

```bash
docker compose run --rm web python manage.py test apps.tts.tests.test_service.TestTTSResult -v 2
```

Expected: PASS (2 tests)

**Step 5: Commit TTSResult**

```bash
git add apps/tts/service.py apps/tts/tests/test_service.py
git commit -m "$(cat <<'EOF'
feat(tts): add TTSResult dataclass

- TTSResult holds success, duration_ms, error for TTS operations

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Implementare TTSService.synthesize_stream()

**Files:**
- Modify: `apps/tts/service.py`
- Modify: `apps/tts/tests/test_service.py`

**Step 1: Aggiungere test per TTSService con mock Azure SDK**

Aggiungere a `apps/tts/tests/test_service.py`:

```python
class TestTTSService:
    """Test TTSService."""

    @pytest.fixture
    def mock_speech_config(self):
        with patch("apps.tts.service.speechsdk") as mock_sdk:
            yield mock_sdk

    @pytest.mark.asyncio
    async def test_synthesize_stream_success(self, mock_speech_config):
        """Test successful TTS synthesis."""
        mock_sdk = mock_speech_config

        # Setup mock synthesizer
        mock_synthesizer = MagicMock()
        mock_sdk.SpeechSynthesizer.return_value = mock_synthesizer

        # Mock audio data result
        mock_result = MagicMock()
        mock_result.reason = mock_sdk.ResultReason.SynthesizingAudioCompleted
        mock_result.audio_data = b"\x00" * 9600  # 100ms at 48kHz mono 16-bit
        mock_result.audio_duration.total_seconds.return_value = 0.1
        mock_synthesizer.speak_text_async.return_value.get.return_value = mock_result

        # Mock audio config
        mock_sdk.audio.AudioOutputConfig.return_value = MagicMock()

        service = TTSService()
        chunks_received = []

        async def on_chunk(pcm: bytes, samples: int, sample_rate: int):
            chunks_received.append((pcm, samples, sample_rate))

        result = await service.synthesize_stream("Ciao mondo", on_chunk)

        assert result.success is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_synthesize_stream_failure(self, mock_speech_config):
        """Test TTS synthesis failure."""
        mock_sdk = mock_speech_config

        # Setup mock synthesizer
        mock_synthesizer = MagicMock()
        mock_sdk.SpeechSynthesizer.return_value = mock_synthesizer

        # Mock canceled result
        mock_result = MagicMock()
        mock_result.reason = mock_sdk.ResultReason.Canceled
        mock_cancellation = MagicMock()
        mock_cancellation.reason = mock_sdk.CancellationReason.Error
        mock_cancellation.error_details = "Connection failed"
        mock_sdk.CancellationDetails.from_result.return_value = mock_cancellation
        mock_synthesizer.speak_text_async.return_value.get.return_value = mock_result

        service = TTSService()

        async def on_chunk(pcm: bytes, samples: int, sample_rate: int):
            pass

        result = await service.synthesize_stream("Test", on_chunk)

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_synthesize_stream_empty_text(self, mock_speech_config):
        """Test TTS with empty text returns error."""
        service = TTSService()

        async def on_chunk(pcm: bytes, samples: int, sample_rate: int):
            pass

        result = await service.synthesize_stream("", on_chunk)

        assert result.success is False
        assert result.error == "empty_text"
```

**Step 2: Eseguire test per verificare fallimento**

```bash
docker compose run --rm web python manage.py test apps.tts.tests.test_service.TestTTSService -v 2
```

Expected: FAIL con "TTSService has no attribute 'synthesize_stream'"

**Step 3: Implementare TTSService**

Aggiungere a `apps/tts/service.py` dopo TTSResult:

```python
try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None


# Output format: 48kHz mono 16-bit PCM (matches audio hub)
OUTPUT_SAMPLE_RATE = 48000
BYTES_PER_SAMPLE = 2
CHANNELS = 1


class TTSService:
    """
    Azure Speech TTS con streaming audio.

    Sintetizza testo in audio PCM, compatibile con AudioHub.
    """

    def __init__(self):
        self._speech_key = settings.AZURE_SPEECH_KEY
        self._speech_region = settings.AZURE_SPEECH_REGION
        self._voice = getattr(settings, "AZURE_TTS_VOICE", "it-IT-DiegoNeural")

    async def synthesize_stream(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes, int, int], Awaitable[None]]
    ) -> TTSResult:
        """
        Sintetizza testo in audio, streaming chunk per chunk.

        Args:
            text: Testo da sintetizzare
            on_audio_chunk: Callback(pcm_data, samples, sample_rate) per ogni chunk

        Returns:
            TTSResult con success, duration_ms, error
        """
        if not text or not text.strip():
            return TTSResult(success=False, duration_ms=None, error="empty_text")

        if speechsdk is None:
            logger.error("Azure Speech SDK not installed")
            return TTSResult(success=False, duration_ms=None, error="sdk_not_installed")

        try:
            return await self._do_synthesis(text, on_audio_chunk)
        except Exception as e:
            logger.exception(f"TTS synthesis error: {e}")
            return TTSResult(success=False, duration_ms=None, error=f"exception: {e}")

    async def _do_synthesis(
        self,
        text: str,
        on_audio_chunk: Callable[[bytes, int, int], Awaitable[None]]
    ) -> TTSResult:
        """Esegue la sintesi con Azure SDK."""
        # Configurazione speech
        speech_config = speechsdk.SpeechConfig(
            subscription=self._speech_key,
            region=self._speech_region
        )
        speech_config.speech_synthesis_voice_name = self._voice

        # Output format: 48kHz mono 16-bit PCM raw
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Raw48Khz16BitMonoPcm
        )

        # Usa output in memoria (non file)
        audio_config = speechsdk.audio.AudioOutputConfig(use_default_speaker=False)

        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=None  # Gestione manuale dell'audio
        )

        # Esegui sintesi (blocking in thread pool)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: synthesizer.speak_text_async(text).get()
        )

        # Verifica risultato
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio_data = result.audio_data
            duration_ms = int(result.audio_duration.total_seconds() * 1000)

            # Invia audio in chunk
            if audio_data:
                chunk_size = OUTPUT_SAMPLE_RATE * BYTES_PER_SAMPLE * CHANNELS // 10  # 100ms chunks
                for i in range(0, len(audio_data), chunk_size):
                    chunk = audio_data[i:i + chunk_size]
                    samples = len(chunk) // BYTES_PER_SAMPLE
                    await on_audio_chunk(chunk, samples, OUTPUT_SAMPLE_RATE)

            return TTSResult(success=True, duration_ms=duration_ms, error=None)

        elif result.reason == speechsdk.ResultReason.Canceled:
            cancellation = speechsdk.CancellationDetails.from_result(result)
            if cancellation.reason == speechsdk.CancellationReason.Error:
                error_msg = f"azure_error: {cancellation.error_details}"
                logger.error(f"TTS canceled: {error_msg}")
                return TTSResult(success=False, duration_ms=None, error=error_msg)
            else:
                return TTSResult(success=False, duration_ms=None, error="canceled")

        else:
            return TTSResult(success=False, duration_ms=None, error=f"unknown_reason: {result.reason}")
```

**Step 4: Eseguire test per verificare pass**

```bash
docker compose run --rm web python manage.py test apps.tts.tests.test_service.TestTTSService -v 2
```

Expected: PASS (3 tests)

**Step 5: Commit TTSService**

```bash
git add apps/tts/service.py apps/tts/tests/test_service.py
git commit -m "$(cat <<'EOF'
feat(tts): implement TTSService with Azure Speech SDK

- synthesize_stream() converts text to PCM audio chunks
- Outputs 48kHz mono 16-bit PCM (compatible with AudioHub)
- Handles errors with appropriate TTSResult values
- Empty text returns error instead of calling Azure

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Modificare AudioHub per peer virtuale AI

**Files:**
- Modify: `apps/webrtc/audio_hub.py:19-88`
- Create: `apps/webrtc/tests/test_audio_hub.py`

**Step 1: Scrivere test per AI track injection**

Creare `apps/webrtc/tests/test_audio_hub.py`:

```python
"""Tests for AudioHub AI integration."""
import pytest
from unittest.mock import MagicMock, patch
from apps.webrtc.audio_hub import (
    SessionAudioHub,
    AI_MODERATOR_ID,
    get_hub,
)


class TestAudioHubAI:
    """Test AI moderator integration in AudioHub."""

    def test_ai_moderator_id_constant(self):
        """AI_MODERATOR_ID should be a reserved identifier."""
        assert AI_MODERATOR_ID == "__AI_MODERATOR__"

    def test_init_ai_track_creates_track(self):
        """init_ai_track should create a ForwardingAudioTrack."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            track = hub.init_ai_track()

            assert track == mock_track
            MockTrack.assert_called_once()

    def test_init_ai_track_idempotent(self):
        """init_ai_track should return same track on subsequent calls."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            track1 = hub.init_ai_track()
            track2 = hub.init_ai_track()

            assert track1 is track2
            MockTrack.assert_called_once()  # Only one creation

    def test_set_speaker_accepts_ai_moderator(self):
        """set_speaker should accept AI_MODERATOR_ID."""
        hub = SessionAudioHub("test-session")

        hub.set_speaker(AI_MODERATOR_ID)

        assert hub.current_speaker_user_id == AI_MODERATOR_ID

    def test_inject_ai_audio_when_ai_speaking(self):
        """inject_ai_audio should enqueue when AI is speaker."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            hub.init_ai_track()
            hub.set_speaker(AI_MODERATOR_ID)

            pcm_chunk = b"\x00" * 1920
            hub.inject_ai_audio(pcm_chunk, 960, 48000)

            mock_track.enqueue.assert_called_once_with(pcm_chunk, 960, 48000)

    def test_inject_ai_audio_ignored_when_not_speaking(self):
        """inject_ai_audio should be ignored when AI is not speaker."""
        hub = SessionAudioHub("test-session")

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_track = MagicMock()
            MockTrack.return_value = mock_track

            hub.init_ai_track()
            hub.set_speaker(123)  # Human speaker

            pcm_chunk = b"\x00" * 1920
            hub.inject_ai_audio(pcm_chunk, 960, 48000)

            mock_track.enqueue.assert_not_called()

    def test_inject_ai_audio_ignored_without_track(self):
        """inject_ai_audio should be ignored if track not initialized."""
        hub = SessionAudioHub("test-session")
        hub.set_speaker(AI_MODERATOR_ID)

        # Should not raise
        hub.inject_ai_audio(b"\x00" * 1920, 960, 48000)
```

**Step 2: Eseguire test per verificare fallimento**

```bash
docker compose run --rm web python manage.py test apps.webrtc.tests.test_audio_hub -v 2
```

Expected: FAIL con "cannot import name 'AI_MODERATOR_ID'"

**Step 3: Modificare `apps/webrtc/audio_hub.py`**

Aggiungere dopo gli import (circa linea 10):

```python
from apps.webrtc.audio_tracks import ForwardingAudioTrack

# Reserved ID for AI Moderator virtual peer
AI_MODERATOR_ID = "__AI_MODERATOR__"
```

Modificare la classe `SessionAudioHub.__init__` per aggiungere `_ai_track`:

```python
def __init__(self, session_id: str):
    self.session_id = session_id
    self.peers: Dict[int, PeerAudioState] = {}
    self.current_speaker_user_id: Optional[int | str] = None  # int for humans, str for AI
    self._ai_track: Optional[ForwardingAudioTrack] = None
```

Aggiungere i nuovi metodi alla classe `SessionAudioHub`:

```python
def init_ai_track(self) -> ForwardingAudioTrack:
    """Crea il track virtuale per il moderatore AI."""
    if self._ai_track is None:
        self._ai_track = ForwardingAudioTrack(
            user_id=0,  # Virtual user
            session_id=self.session_id
        )
        logger.info(f"[{self.session_id}] AI track initialized")
    return self._ai_track

def inject_ai_audio(self, pcm_chunk: bytes, samples: int, sample_rate: int):
    """Inietta audio TTS nel track AI per forwarding."""
    if self._ai_track is not None and self.current_speaker_user_id == AI_MODERATOR_ID:
        self._ai_track.enqueue(pcm_chunk, samples, sample_rate)
```

Modificare `set_speaker` per accettare anche stringhe (type hint già OK se usa `Optional[int | str]`).

**Step 4: Eseguire test per verificare pass**

```bash
docker compose run --rm web python manage.py test apps.webrtc.tests.test_audio_hub -v 2
```

Expected: PASS (7 tests)

**Step 5: Commit AudioHub AI integration**

```bash
git add apps/webrtc/audio_hub.py apps/webrtc/tests/test_audio_hub.py
git commit -m "$(cat <<'EOF'
feat(webrtc): add AI moderator virtual peer to AudioHub

- Add AI_MODERATOR_ID constant for virtual peer identification
- Add init_ai_track() to create ForwardingAudioTrack for AI
- Add inject_ai_audio() to enqueue TTS chunks when AI is speaking
- set_speaker() now accepts AI_MODERATOR_ID

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Modificare forward_pcm per supportare AI track

**Files:**
- Modify: `apps/webrtc/audio_hub.py:54-65`
- Modify: `apps/webrtc/tests/test_audio_hub.py`

**Step 1: Aggiungere test per AI audio forwarding**

Aggiungere a `apps/webrtc/tests/test_audio_hub.py`:

```python
class TestAudioHubForwarding:
    """Test audio forwarding with AI moderator."""

    def test_get_ai_track_for_peer_when_ai_speaking(self):
        """When AI is speaking, peers should receive AI track."""
        hub = SessionAudioHub("test-session")

        # Register a human peer
        mock_human_track = MagicMock()
        hub.register_peer(123, mock_human_track)

        with patch("apps.webrtc.audio_hub.ForwardingAudioTrack") as MockTrack:
            mock_ai_track = MagicMock()
            MockTrack.return_value = mock_ai_track

            hub.init_ai_track()
            hub.set_speaker(AI_MODERATOR_ID)

            # Get outbound track for peer 123 should be AI track
            track = hub.get_outbound_track_for_peer(123)

            assert track == mock_ai_track

    def test_get_human_track_for_peer_when_human_speaking(self):
        """When human is speaking, other peers should receive human's track."""
        hub = SessionAudioHub("test-session")

        # Register two human peers
        mock_speaker_track = MagicMock()
        mock_listener_track = MagicMock()
        hub.register_peer(100, mock_speaker_track)
        hub.register_peer(200, mock_listener_track)

        hub.set_speaker(100)

        # Peer 200 should receive speaker 100's track
        track = hub.get_outbound_track_for_peer(200)

        # Track comes from speaker (100), not listener
        assert track == mock_speaker_track
```

**Step 2: Eseguire test per verificare fallimento**

```bash
docker compose run --rm web python manage.py test apps.webrtc.tests.test_audio_hub.TestAudioHubForwarding -v 2
```

Expected: FAIL con "has no attribute 'get_outbound_track_for_peer'"

**Step 3: Aggiungere metodo get_outbound_track_for_peer**

Aggiungere a `SessionAudioHub`:

```python
def get_outbound_track_for_peer(self, user_id: int) -> Optional[ForwardingAudioTrack]:
    """
    Ritorna il track da cui il peer user_id dovrebbe ricevere audio.

    - Se AI sta parlando: ritorna _ai_track
    - Se un umano sta parlando: ritorna il track di quell'umano (se diverso da user_id)
    - Altrimenti: None
    """
    if self.current_speaker_user_id == AI_MODERATOR_ID:
        return self._ai_track
    elif self.current_speaker_user_id is not None and self.current_speaker_user_id != user_id:
        speaker_state = self.peers.get(self.current_speaker_user_id)
        if speaker_state:
            return speaker_state.outbound_track
    return None
```

**Step 4: Eseguire test per verificare pass**

```bash
docker compose run --rm web python manage.py test apps.webrtc.tests.test_audio_hub.TestAudioHubForwarding -v 2
```

Expected: PASS (2 tests)

**Step 5: Commit forwarding logic**

```bash
git add apps/webrtc/audio_hub.py apps/webrtc/tests/test_audio_hub.py
git commit -m "$(cat <<'EOF'
feat(webrtc): add get_outbound_track_for_peer for AI forwarding

- Returns AI track when AI_MODERATOR is speaking
- Returns human speaker track when human is speaking
- Used by WebRTC peer connections for audio routing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Aggiungere campo final_summary al modello Session

**Files:**
- Modify: `apps/sessions/models.py:39-118`
- Create migration

**Step 1: Aggiungere campo final_summary**

In `apps/sessions/models.py`, aggiungere dopo `ended_at` (circa linea 73):

```python
    final_summary = models.TextField(
        blank=True,
        null=True,
        help_text="Summary finale della sessione dal moderatore AI"
    )
```

**Step 2: Creare migration**

```bash
docker compose run --rm web python manage.py makemigrations sessions --name add_final_summary
```

**Step 3: Applicare migration**

```bash
docker compose run --rm web python manage.py migrate sessions
```

**Step 4: Commit model change**

```bash
git add apps/sessions/models.py apps/sessions/migrations/
git commit -m "$(cat <<'EOF'
feat(sessions): add final_summary field to Session model

- Stores AI moderator's summary at session close
- TextField, nullable for sessions without AI summary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Aggiungere metodo _append_to_session_transcript

**Files:**
- Modify: `apps/turns/ws_consumer.py`
- Create: `apps/turns/tests/test_transcript.py`

**Step 1: Scrivere test per append transcript**

Creare `apps/turns/tests/test_transcript.py`:

```python
"""Tests for session transcript management."""
import pytest
import json
from unittest.mock import patch, MagicMock
from django.core.cache import cache


class TestSessionTranscript:
    """Test transcript append functionality."""

    @pytest.fixture(autouse=True)
    def clear_cache(self):
        """Clear cache before each test."""
        cache.clear()
        yield
        cache.clear()

    def test_append_human_entry(self):
        """Test appending human turn to transcript."""
        from apps.turns.ws_consumer import _append_to_session_transcript

        session_id = "test-session-123"
        entry = {
            "type": "human",
            "user_id": 456,
            "speaker_name": "Mario Rossi",
            "text": "Penso che dovremmo procedere",
            "timestamp": "2026-01-27T10:30:00Z"
        }

        _append_to_session_transcript(session_id, entry)

        key = f"session:{session_id}:transcript"
        items = cache.get(key)
        assert items is not None
        assert len(items) == 1
        assert json.loads(items[0])["type"] == "human"

    def test_append_ai_entry(self):
        """Test appending AI turn to transcript."""
        from apps.turns.ws_consumer import _append_to_session_transcript

        session_id = "test-session-123"
        entry = {
            "type": "ai",
            "text": "Grazie per il contributo",
            "trigger": "llm_decision",
            "timestamp": "2026-01-27T10:31:00Z"
        }

        _append_to_session_transcript(session_id, entry)

        key = f"session:{session_id}:transcript"
        items = cache.get(key)
        assert items is not None
        parsed = json.loads(items[0])
        assert parsed["type"] == "ai"
        assert parsed["trigger"] == "llm_decision"

    def test_append_multiple_entries(self):
        """Test appending multiple entries maintains order."""
        from apps.turns.ws_consumer import _append_to_session_transcript

        session_id = "test-session-123"

        _append_to_session_transcript(session_id, {"type": "human", "text": "First"})
        _append_to_session_transcript(session_id, {"type": "ai", "text": "Second"})
        _append_to_session_transcript(session_id, {"type": "human", "text": "Third"})

        key = f"session:{session_id}:transcript"
        items = cache.get(key)

        assert len(items) == 3
        assert json.loads(items[0])["text"] == "First"
        assert json.loads(items[1])["text"] == "Second"
        assert json.loads(items[2])["text"] == "Third"
```

**Step 2: Eseguire test per verificare fallimento**

```bash
docker compose run --rm web python manage.py test apps.turns.tests.test_transcript -v 2
```

Expected: FAIL con "cannot import name '_append_to_session_transcript'"

**Step 3: Implementare _append_to_session_transcript**

Aggiungere a `apps/turns/ws_consumer.py` (come funzione module-level, non metodo):

```python
import json
from django.core.cache import cache

TRANSCRIPT_KEY_PREFIX = "session"
TRANSCRIPT_TTL = 60 * 60 * 24  # 24 hours


def _append_to_session_transcript(session_id: str, entry: dict) -> None:
    """
    Appende un'entry al transcript della sessione in Redis.

    Args:
        session_id: ID della sessione
        entry: Dict con type, text, e altri campi
    """
    key = f"{TRANSCRIPT_KEY_PREFIX}:{session_id}:transcript"
    serialized = json.dumps(entry)

    # Redis RPUSH via Django cache
    # Django cache non ha rpush nativo, usiamo get/set
    existing = cache.get(key) or []
    existing.append(serialized)
    cache.set(key, existing, timeout=TRANSCRIPT_TTL)
```

**Step 4: Eseguire test per verificare pass**

```bash
docker compose run --rm web python manage.py test apps.turns.tests.test_transcript -v 2
```

Expected: PASS (3 tests)

**Step 5: Commit transcript helper**

```bash
git add apps/turns/ws_consumer.py apps/turns/tests/test_transcript.py
git commit -m "$(cat <<'EOF'
feat(turns): add _append_to_session_transcript helper

- Stores transcript entries in Redis list
- Supports human and AI entry types
- 24-hour TTL, cleaned up at session close

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Integrare TTS in _handle_end_speak

**Files:**
- Modify: `apps/turns/ws_consumer.py:387-401`

**Step 1: Aggiornare imports**

Aggiungere all'inizio di `apps/turns/ws_consumer.py`:

```python
from apps.tts.service import TTSService
from apps.webrtc.audio_hub import get_hub, AI_MODERATOR_ID
from datetime import datetime
```

**Step 2: Modificare blocco AI speaking**

Sostituire il blocco lines 387-401 (o equivalente) con:

```python
        # LLM-generated AI message with TTS
        if decision.ai_should_speak and decision.ai_message:
            # 1. Start AI turn
            ai_start_res = TM.ai_start(self.session_id)
            await self._broadcast_events(ai_start_res.events)

            # 2. Set AI as speaker in audio hub
            hub = get_hub(self.session_id)
            hub.init_ai_track()
            hub.set_speaker(AI_MODERATOR_ID)

            # 3. TTS streaming with injection to hub
            tts = TTSService()
            tts_result = await tts.synthesize_stream(
                text=decision.ai_message,
                on_audio_chunk=lambda pcm, samples, sr: self._inject_ai_audio(hub, pcm, samples, sr)
            )

            # 4. Fallback if TTS fails
            if not tts_result.success:
                logger.warning(f"TTS failed: {tts_result.error}, fallback to text")
                await self.send_json({
                    "type": "turns.ai_message",
                    "payload": {"text": decision.ai_message}
                })

            # 5. Append to session transcript
            _append_to_session_transcript(self.session_id, {
                "type": "ai",
                "text": decision.ai_message,
                "trigger": "llm_decision",
                "timestamp": datetime.utcnow().isoformat()
            })

            # 6. End AI turn (synchronous with audio end)
            hub.set_speaker(None)
            ai_end_res = TM.ai_end(self.session_id)
            await self._broadcast_events(ai_end_res.events)
```

**Step 3: Aggiungere helper method**

Aggiungere alla classe `TurnsConsumer`:

```python
    async def _inject_ai_audio(self, hub, pcm: bytes, samples: int, sample_rate: int):
        """Wrapper async per inject_ai_audio."""
        hub.inject_ai_audio(pcm, samples, sample_rate)
```

**Step 4: Commit integrazione TTS**

```bash
git add apps/turns/ws_consumer.py
git commit -m "$(cat <<'EOF'
feat(turns): integrate TTS in AI speaking flow

- AI turn uses TTSService for voice synthesis
- Audio injected to AudioHub for WebRTC forwarding
- Fallback to text message if TTS fails
- Transcript updated with AI message

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Aggiungere append transcript per turni umani

**Files:**
- Modify: `apps/turns/ws_consumer.py`

**Step 1: Aggiungere append dopo raccolta transcript ASR**

Dopo la raccolta del transcript (circa linea 338, dopo `_collect_asr_transcript_with_wait`), aggiungere:

```python
            # Append human turn to session transcript
            if last_turn_text:
                _append_to_session_transcript(self.session_id, {
                    "type": "human",
                    "user_id": str(user_id),
                    "speaker_name": speaker_name,
                    "text": last_turn_text,
                    "timestamp": datetime.utcnow().isoformat()
                })
```

**Step 2: Commit human transcript append**

```bash
git add apps/turns/ws_consumer.py
git commit -m "$(cat <<'EOF'
feat(turns): append human turns to session transcript

- Records speaker_name, user_id, text and timestamp
- Stored in Redis for session duration

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Cleanup transcript alla chiusura sessione

**Files:**
- Modify: `apps/sessions/services.py` (o file che gestisce CLOSED)
- Modify: `apps/sessions/models.py` (se serve import)

**Step 1: Identificare dove avviene la chiusura sessione**

Cercare nel codebase dove `session.state = SessionState.CLOSED` viene settato.

**Step 2: Aggiungere cleanup logic**

Nel metodo che chiude la sessione, aggiungere:

```python
from django.core.cache import cache
from apps.moderation.state import load_moderation_state

def close_session(session_id: str):
    """Chiude la sessione e salva il summary."""
    session = Session.objects.get(id=session_id)

    # 1. Recupera summary da ModerationState
    mod_state = load_moderation_state(session_id)
    if mod_state and mod_state.summary:
        session.final_summary = mod_state.summary

    # 2. Aggiorna stato
    session.state = SessionState.CLOSED
    session.ended_at = timezone.now()
    session.save()

    # 3. Cleanup Redis
    cache.delete(f"session:{session_id}:transcript")
    cache.delete(f"turns:{session_id}")
    cache.delete(f"moderation:{session_id}")
```

**Step 3: Commit cleanup**

```bash
git add apps/sessions/services.py
git commit -m "$(cat <<'EOF'
feat(sessions): save final_summary and cleanup Redis on close

- Copies ModerationState.summary to Session.final_summary
- Deletes transcript, turns, and moderation Redis keys

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Aggiornare .env.example

**Files:**
- Modify: `.env.example` (se esiste) o documentare

**Step 1: Aggiungere variabile TTS**

```bash
# TTS Configuration
AZURE_TTS_VOICE=it-IT-DiegoNeural
```

**Step 2: Commit env update**

```bash
git add .env.example
git commit -m "$(cat <<'EOF'
docs: add AZURE_TTS_VOICE to .env.example

- Default voice: it-IT-DiegoNeural (Italian male neural)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Test integrazione manuale (utente)

**Checklist per test manuale:**

1. [ ] Avviare l'ambiente Docker: `make up`
2. [ ] Creare una sessione con almeno 2 partecipanti
3. [ ] Un partecipante parla e termina il turno
4. [ ] Verificare che il moderatore AI risponda con audio (non solo testo)
5. [ ] Verificare che l'audio sia udibile da tutti i partecipanti
6. [ ] Verificare la qualità audio (no distorsioni, latenza accettabile)
7. [ ] Testare fallback: disabilitare Azure TTS temporaneamente, verificare messaggio testo
8. [ ] Verificare transcript in Redis: `redis-cli LRANGE session:<id>:transcript 0 -1`
9. [ ] Chiudere sessione e verificare `final_summary` in DB

---

## Summary

| Task | Descrizione | Files principali |
|------|-------------|------------------|
| 1 | Struttura modulo TTS | `apps/tts/__init__.py`, settings |
| 2 | TTSResult dataclass | `apps/tts/service.py` |
| 3 | TTSService.synthesize_stream | `apps/tts/service.py` |
| 4 | AudioHub peer virtuale AI | `apps/webrtc/audio_hub.py` |
| 5 | Forwarding AI audio | `apps/webrtc/audio_hub.py` |
| 6 | Campo final_summary | `apps/sessions/models.py` |
| 7 | _append_to_session_transcript | `apps/turns/ws_consumer.py` |
| 8 | Integrazione TTS in end_speak | `apps/turns/ws_consumer.py` |
| 9 | Append turni umani | `apps/turns/ws_consumer.py` |
| 10 | Cleanup alla chiusura | `apps/sessions/services.py` |
| 11 | Documentazione .env | `.env.example` |
| 12 | Test manuale | - |
