# TTS Moderatore - Design Document

**Data:** 2026-01-27
**Stato:** Approvato
**Autore:** Claude + Salvatore

## Obiettivo

Implementare la sintesi vocale (TTS) per il moderatore AI, permettendogli di "parlare" agli utenti via audio WebRTC invece di inviare solo messaggi testuali.

## Decisioni di Design

| Aspetto | Decisione |
|---------|-----------|
| Dove avviene TTS | Backend (Azure Speech Synthesis) |
| Gestione turno AI | Sincrono con audio reale (turno dura quanto l'audio) |
| Integrazione audio hub | Peer virtuale "AI_MODERATOR" |
| Flusso generazione | Streaming in tempo reale |
| Voce | Neurale italiana, configurabile via env |
| Gestione errori TTS | Fallback a solo testo |
| Persistenza transcript | Redis durante sessione, cleanup alla chiusura |
| Summary finale | Usa summary esistente da ModerationState |

## Architettura

### Flusso Completo

```
Human turn ends
       ↓
ModerationOrchestrator → LLM decision
       ↓
decision.ai_should_speak = true
       ↓
TurnManager.ai_start() → stato AI_SPEAKING
       ↓
TTSService.synthesize_stream(text) → Azure Speech SDK
       ↓
Audio chunks (PCM) arrivano in streaming
       ↓
AudioHub.inject_ai_audio(chunk) → peer virtuale "AI_MODERATOR"
       ↓
ForwardingAudioTrack → forwarding a tutti i client via WebRTC
       ↓
Audio finito
       ↓
TurnManager.ai_end() → stato IDLE
```

### Componenti

| Componente | Azione | Responsabilità |
|------------|--------|----------------|
| `TTSService` | **Nuovo** | Wrapper Azure Speech SDK, streaming synthesis |
| `AudioHub` | **Modifica** | Peer virtuale AI, metodo `inject_ai_audio()` |
| `TurnsConsumer` | **Modifica** | Integrazione TTS nel flusso `_handle_end_speak()` |
| `ForwardingAudioTrack` | **Nessuna** | Già supporta chunk PCM, riusabile |

## Dettaglio Componenti

### 1. TTSService

**Nuovo file:** `apps/tts/service.py`

```python
class TTSResult:
    success: bool
    duration_ms: int | None
    error: str | None

class TTSService:
    """Azure Speech TTS con streaming audio."""

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
```

**Comportamento:**
- Crea `SpeechSynthesizer` con Azure SDK
- Usa `PullAudioOutputStream` per ricevere chunk in streaming
- Per ogni chunk ricevuto, chiama `on_audio_chunk(pcm_data, samples, sample_rate)`
- Chunk in formato PCM 16-bit mono 48kHz (compatibile con audio hub)
- Ritorna durata totale e stato success/error

**Gestione errori:**
- Timeout Azure → `TTSResult(success=False, error="timeout")`
- Quota esaurita → `TTSResult(success=False, error="quota")`
- Errore generico → `TTSResult(success=False, error="azure_error")`

**Configurazione:**
```python
VOICE = settings.AZURE_TTS_VOICE  # default: "it-IT-DiegoNeural"
SAMPLE_RATE = 48000  # match audio hub
FORMAT = AudioFormat.PCM_16BIT_MONO
```

### 2. Modifiche AudioHub

**File:** `apps/webrtc/audio_hub.py`

**Costante:**
```python
AI_MODERATOR_ID = "__AI_MODERATOR__"
```

**Nuovi attributi:**
```python
class AudioHub:
    def __init__(self, session_id: str):
        # ... esistenti ...
        self._ai_track: ForwardingAudioTrack | None = None  # NUOVO
```

**Nuovi metodi:**
```python
def init_ai_track(self) -> ForwardingAudioTrack:
    """Crea il track virtuale per il moderatore AI."""
    if not self._ai_track:
        self._ai_track = ForwardingAudioTrack()
    return self._ai_track

def inject_ai_audio(self, pcm_chunk: bytes, samples: int, sample_rate: int):
    """Inietta audio TTS nel track AI per forwarding."""
    if self._ai_track and self._current_speaker == AI_MODERATOR_ID:
        self._ai_track.enqueue(pcm_chunk, samples, sample_rate)
```

**Modifica a `set_speaker()`:**
```python
def set_speaker(self, user_id: str | None):
    """Accetta anche AI_MODERATOR_ID."""
    self._current_speaker = user_id
    # Se speaker è AI, il track AI viene forwardato a tutti i peer
```

**Logica forwarding:**
- `speaker == AI_MODERATOR_ID` → forward `_ai_track` a tutti i peer umani
- `speaker == user_id` → forward track di quel user a tutti gli altri (invariato)
- `speaker == None` → nessun forwarding (invariato)

### 3. Integrazione TurnsConsumer

**File:** `apps/turns/ws_consumer.py`

**Modifica a `_handle_end_speak()`:**

```python
async def _handle_end_speak(self, content: dict):
    # ... codice esistente fino a decision.ai_should_speak ...

    if decision.ai_should_speak:
        # 1. Start AI turn
        ai_start_res = TM.ai_start(self.session_id)
        await self._broadcast_events(ai_start_res.events)

        # 2. Imposta AI come speaker nell'audio hub
        hub = get_audio_hub(self.session_id)
        hub.set_speaker(AI_MODERATOR_ID)

        # 3. TTS streaming con injection nell'hub
        tts = TTSService()
        tts_result = await tts.synthesize_stream(
            text=decision.ai_message,
            on_audio_chunk=lambda chunk, samples, sr:
                hub.inject_ai_audio(chunk, samples, sr)
        )

        # 4. Fallback se TTS fallisce
        if not tts_result.success:
            logger.warning(f"TTS failed: {tts_result.error}, fallback to text")
            await self.send_json({
                "type": "turns.ai_message",
                "payload": {"text": decision.ai_message}
            })

        # 5. Append al transcript di sessione
        await self._append_to_session_transcript({
            "type": "ai",
            "text": decision.ai_message,
            "trigger": decision.trigger_type,
            "timestamp": datetime.utcnow().isoformat()
        })

        # 6. Fine AI turn (sincrono con fine audio)
        hub.set_speaker(None)
        ai_end_res = TM.ai_end(self.session_id)
        await self._broadcast_events(ai_end_res.events)
```

### 4. Gestione Transcript

**Chiave Redis:** `session:{session_id}:transcript`

**Struttura (lista JSON):**
```json
[
    {
        "type": "human",
        "user_id": "uuid",
        "speaker_name": "Mario Rossi",
        "text": "Penso che dovremmo...",
        "timestamp": "2026-01-27T10:30:00Z"
    },
    {
        "type": "ai",
        "text": "Grazie Mario. Vorrei aggiungere che...",
        "trigger": "llm_decision",
        "timestamp": "2026-01-27T10:30:45Z"
    }
]
```

**Nuovo metodo in TurnsConsumer:**
```python
async def _append_to_session_transcript(self, entry: dict):
    key = f"session:{self.session_id}:transcript"
    cache.rpush(key, json.dumps(entry))
```

**Quando salvare:**
- Turno umano → append dopo `_collect_asr_transcript_with_wait()`
- Turno AI → append dopo TTS completato (o fallback testo)

### 5. Cleanup alla Chiusura Sessione

**File:** `apps/sessions/services.py` (o dove gestisci CLOSED)

```python
async def close_session(session_id: str):
    # 1. Recupera summary esistente da ModerationState
    mod_state = ModerationState.load(session_id)
    final_summary = mod_state.summary

    # 2. Salva summary in DB
    session = Session.objects.get(id=session_id)
    session.final_summary = final_summary
    session.save()

    # 3. Cleanup Redis
    cache.delete(f"session:{session_id}:transcript")
    cache.delete(f"turns:{session_id}")
    cache.delete(f"moderation:{session_id}")
```

**Modifica Model Session:**
```python
class Session(models.Model):
    # ... campi esistenti ...
    final_summary = models.TextField(blank=True, null=True)  # NUOVO
```

## Configurazione

### Variabili Ambiente

```bash
# Esistenti (già usate per ASR)
AZURE_SPEECH_KEY=xxx
AZURE_SPEECH_REGION=westeurope

# Nuova
AZURE_TTS_VOICE=it-IT-DiegoNeural
```

**Voci italiane disponibili:**
- `it-IT-DiegoNeural` (maschile)
- `it-IT-ElsaNeural` (femminile)
- `it-IT-IsabellaNeural` (femminile)
- `it-IT-GiuseppeNeural` (maschile)

### Settings Django

**File:** `aiutami/settings.py`

```python
# TTS Configuration
AZURE_TTS_VOICE = env("AZURE_TTS_VOICE", default="it-IT-DiegoNeural")
```

## File da Creare/Modificare

### Nuovi File

| File | Descrizione |
|------|-------------|
| `apps/tts/__init__.py` | Init modulo TTS |
| `apps/tts/service.py` | TTSService |

### File da Modificare

| File | Modifica |
|------|----------|
| `apps/webrtc/audio_hub.py` | Peer virtuale AI, `inject_ai_audio()` |
| `apps/turns/ws_consumer.py` | Integrazione TTS, append transcript |
| `apps/sessions/services.py` | Cleanup Redis alla chiusura |
| `apps/sessions/models.py` | Campo `final_summary` |
| `aiutami/settings.py` | `AZURE_TTS_VOICE` |

## Considerazioni Tecniche

### Sample Rate
Azure TTS default è 24kHz. L'audio hub lavora a 48kHz. Il TTSService dovrà:
- Opzione A: Richiedere 48kHz ad Azure (supportato)
- Opzione B: Fare resampling 24kHz → 48kHz

**Raccomandazione:** Opzione A (richiedere 48kHz ad Azure)

### Latenza
- Stimata: 200-500ms dal testo al primo chunk audio
- Dipende dalla lunghezza del testo e dalla risposta Azure

### Concorrenza
- Il flag `moderation_in_progress` già esistente previene race condition
- Nessun umano può prendere il turno mentre AI sta parlando

### Costi Azure
- ~€15 per 1M caratteri (voci neurali)
- Stimato: €15 coprono ~100-200 sessioni complete

## Testing

### Unit Test
- Mock di Azure Speech SDK per `TTSService`
- Test `AudioHub.inject_ai_audio()` con chunk fittizi
- Test integrazione `TurnsConsumer` con mock TTS

### Integration Test
- Test end-to-end con Azure reale (opzionale, costoso)
- Verificare audio ricevuto dai client WebRTC

### Test Manuali (utente)
- Verificare qualità audio su diversi browser
- Verificare latenza percepita
- Verificare fallback a testo quando TTS fallisce
