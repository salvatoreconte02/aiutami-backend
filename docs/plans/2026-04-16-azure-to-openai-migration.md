# Migrazione Azure → OpenAI (LLM + STT + TTS)

**Data:** 2026-04-16
**Autore:** Salvatore + Claude
**Contesto:** crediti Azure esauriti (sia Polimi che GitHub Education). Il
laboratorio ha fornito una chiave OpenAI con accesso completo a LLM, STT
(Whisper e gpt-4o-*-transcribe), TTS (tts-1, gpt-4o-mini-tts) e Realtime API.
Migriamo tutto il progetto da Azure a OpenAI mantenendo l'architettura
esistente (pipeline STT → LLM → TTS), senza cambiare l'UX percepita.

---

## 1. Scope e non-scope

### Scope
- Sostituire **Azure OpenAI** (LLM per moderation + reports) con **OpenAI chat completions**.
- Sostituire **Azure Speech STT** (streaming) con **OpenAI Realtime API transcription-only** (WebSocket).
- Sostituire **Azure Speech TTS** con **OpenAI TTS** (HTTP).
- Aggiornare env vars, Docker, requirements, `.env.example`, `CLAUDE.md`.
- Mantenere verdi i 229 test esistenti.

### Non-scope
- Cambio di architettura (no speech-to-speech `gpt-realtime`).
- Cambio del flusso di moderazione (prompt, trigger, gating, cooldown).
- Refactor del task-plugin system.
- Migrazione del database o dei modelli.

---

## 2. Mappa "da Azure a OpenAI"

### 2.1 LLM (Azure OpenAI → OpenAI)

| Aspetto | Azure OpenAI (attuale) | OpenAI (target) |
|---|---|---|
| Client | `openai.AzureOpenAI(azure_endpoint=..., api_key=..., api_version=...)` | `openai.OpenAI(api_key=...)` |
| Modello | `os.environ["AZURE_OPENAI_MODEL"]` (deployment) | `"gpt-4o-mini"` (fisso, via settings) |
| Env vars | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_MODEL` | `OPENAI_API_KEY`, `OPENAI_LLM_MODEL` (default `gpt-4o-mini`) |
| Body `chat.completions.create(...)` | uguale | uguale |

**File impattati:**
- `apps/moderation/service.py` — metodi `_build_azure_client`, `_call_llm`, `call_llm_for_conclusion`, `call_llm_for_summary`
- `apps/reports/llm_service.py` — `_build_azure_client`, `generate_report_text`

**Difficoltà:** bassa, drop-in. Il contratto dei messaggi, parsing JSON, fallback restano identici.

### 2.2 STT (Azure Speech SDK streaming → OpenAI Realtime transcription)

| Aspetto | Azure Speech SDK (attuale) | OpenAI Realtime (target) |
|---|---|---|
| SDK | `azure.cognitiveservices.speech` (binding C++) | `openai` SDK + WebSocket |
| Paradigma | `PushAudioInputStream` + `start_continuous_recognition_async()` + event callbacks (`recognizing` / `recognized`) | WebSocket verso `wss://api.openai.com/v1/realtime?intent=transcription`, eventi `input_audio_buffer.*` + `conversation.item.input_audio_transcription.*` |
| Formato audio input | PCM 16-bit mono 16kHz (già implementato) | PCM16 mono 24kHz (preferito) OR `g711_*` — oppure si rimane a 16kHz se supportato; dettaglio da verificare in Step 3 |
| Modello | `it-IT` di Azure | `gpt-4o-mini-transcribe` |
| Trigger "final" | `recognized` event | `conversation.item.input_audio_transcription.completed` |
| Trigger "partial" | `recognizing` event | `conversation.item.input_audio_transcription.delta` |
| Invio audio in chunk | `push_stream.write(pcm_bytes)` | `input_audio_buffer.append` (base64) |

**File impattati:**
- `apps/asr/azure_client.py` → sostituito da `apps/asr/openai_client.py`
- `apps/asr/worker.py` — l'integrazione (import, `_init_azure_client`) cambia nome e client sottostante; **la logica di resampling, warmup, diagnostica, cache transcript rimane identica**
- `aiutami/settings.py` — rimozione `AZURE_SPEECH_*`

**Difficoltà:** media. Il writer thread che legge dalla queue e chiama `push_stream.write()` diventa un task asyncio che fa `websocket.send(json.dumps(...))`. Bisogna gestire:
- Handshake WebSocket con header `Authorization: Bearer <key>` + `OpenAI-Beta: realtime=v1`
- Messaggio iniziale `transcription_session.update` con model, VAD config, language
- Ricezione eventi e propagazione a `on_partial` / `on_final` (stesse callback che il worker già usa)
- Teardown pulito (drain queue, close WebSocket)

**Strategia:** il worker NON deve cambiare interfaccia. L'`AzureStreamingClient` espone `start/push_audio/stop` + callback: riproduciamo la stessa interfaccia con `OpenAIRealtimeTranscriptionClient`. Il worker riceve solo un nuovo nome di classe da istanziare.

### 2.3 TTS (Azure Speech SDK → OpenAI TTS HTTP)

| Aspetto | Azure Speech SDK (attuale) | OpenAI TTS (target) |
|---|---|---|
| SDK | `azure.cognitiveservices.speech` | `openai` SDK (`client.audio.speech.create`) |
| Paradigma | Sintesi in background + `result.audio_data` (bytes PCM) | Risposta HTTP con body binario (MP3/PCM/Opus) |
| Formato output | `Raw48Khz16BitMonoPcm` (PCM raw 48kHz) | `pcm` (24kHz 16-bit mono) con `response_format="pcm"` — poi resample a 48kHz per audio hub |
| Modello | `it-IT-DiegoNeural` | `gpt-4o-mini-tts`, voce `onyx` (maschile, prima scelta) |
| Streaming | No (batch, poi chunkato lato nostro a 20ms) | Supporta streaming chunked, o batch + chunkato come ora |

**File impattati:**
- `apps/tts/service.py` — `_do_synthesis` riscritto per OpenAI
- `aiutami/settings.py` — rimozione `AZURE_TTS_VOICE`, aggiunta `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE`
- `apps/tts/tests/test_service.py` — aggiornare mock

**Difficoltà:** bassa/media. La chunking logic a 20ms resta. Cambia la chiamata di sintesi e la gestione del resample 24kHz → 48kHz (o si richiede direttamente 48kHz se supportato).

---

## 3. Decisioni architetturali

### 3.1 Un unico client OpenAI condiviso?

**No.** Ogni servizio (moderation, reports, tts) istanzia il proprio client. Motivi:
1. I 3 servizi vivono in processi diversi (moderation: sync in Django view; TTS: async in WebRTC consumer; reports: sync worker).
2. Il client `openai.OpenAI` è thread-safe e leggero — nessun vantaggio a farne singleton.
3. Il client Realtime STT è un oggetto più pesante (connessione WebSocket persistente) e vive una per sessione/utente — quindi già isolato.

### 3.2 Variabili d'ambiente

**Nuove:**
- `OPENAI_API_KEY` — chiave del lab (nel `.env` attualmente è `OPENAI_KEY_LAB_POLIMI`; rinomino a `OPENAI_API_KEY` per convenzione standard)
- `OPENAI_LLM_MODEL` — default `gpt-4o-mini`
- `OPENAI_STT_MODEL` — default `gpt-4o-mini-transcribe`
- `OPENAI_STT_LANGUAGE` — default `it`
- `OPENAI_TTS_MODEL` — default `gpt-4o-mini-tts`
- `OPENAI_TTS_VOICE` — default `onyx`

**Rimosse:**
- `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `AZURE_SPEECH_LANGUAGE`, `AZURE_TTS_VOICE`
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_API_VERSION`, `AZURE_OPENAI_MODEL`

### 3.3 Rimozione della dipendenza Azure Speech SDK

A fine migrazione si può rimuovere da `requirements.txt`:
```
azure-cognitiveservices-speech==1.38.0
```

Questo riduce l'immagine Docker di ~150 MB.

### 3.4 Scelta voce TTS

Procediamo con `onyx` (voce maschile, adatta a sostituire `it-IT-DiegoNeural`). Se in test interattivi sembra poco naturale, proveremo `nova`, `echo`, `alloy`. Questa è una decisione **cambiabile senza rilascio di codice**: basta modificare `OPENAI_TTS_VOICE` in `.env`.

---

## 4. Piano step-by-step

Ogni step è un commit separato su `main`, con test verdi.

### Step 0 — Preparazione env e settings (no-op funzionale)

- Rinomina in `.env`: `OPENAI_KEY_LAB_POLIMI` → `OPENAI_API_KEY`.
- Aggiungi in `.env.example`:
  ```
  OPENAI_API_KEY=sk-...
  OPENAI_LLM_MODEL=gpt-4o-mini
  OPENAI_STT_MODEL=gpt-4o-mini-transcribe
  OPENAI_STT_LANGUAGE=it
  OPENAI_TTS_MODEL=gpt-4o-mini-tts
  OPENAI_TTS_VOICE=onyx
  ```
- Aggiungi in `aiutami/settings.py` (mantenendo intatte le vecchie Azure per ora):
  ```python
  OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
  OPENAI_LLM_MODEL = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
  OPENAI_STT_MODEL = os.getenv("OPENAI_STT_MODEL", "gpt-4o-mini-transcribe")
  OPENAI_STT_LANGUAGE = os.getenv("OPENAI_STT_LANGUAGE", "it")
  OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
  OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "onyx")
  ```
- Nessun altro file modificato.

**Test:** tutti i 229 test devono passare invariati.

**Commit:** `chore(config): add OpenAI env vars in preparation for Azure migration`

### Step 1 — Migrazione LLM (moderation + reports)

- In `apps/moderation/service.py`:
  - Rimuovi `from openai import AzureOpenAI`, aggiungi `from openai import OpenAI`.
  - Sostituisci `_build_azure_client` → `_build_openai_client` che usa `OpenAI(api_key=settings.OPENAI_API_KEY)`.
  - Nei tre metodi che chiamano LLM, il parametro `model=` passa a `settings.OPENAI_LLM_MODEL`.
  - Aggiungi `response_format={"type": "json_object"}` per garantire parsing JSON affidabile (OpenAI supporta JSON mode nativo; Azure lo ha ma non era usato).
- Stessa cosa in `apps/reports/llm_service.py`.
- Aggiorna i test che mockano `AzureOpenAI` → mockano `OpenAI` (cambio path di import).

**Test:** lancia suite completa con l'API key reale. I test che mockano il client non cambiano comportamento. I test di integrazione (se presenti con rete) possono essere skippati in CI.

**Commit:** `refactor(llm): migrate moderation and reports from Azure OpenAI to OpenAI`

### Step 2 — Migrazione TTS

- Riscrivi `apps/tts/service.py`:
  - Rimuovi l'import `azure.cognitiveservices.speech`.
  - Usa `openai.OpenAI().audio.speech.create(model=settings.OPENAI_TTS_MODEL, voice=settings.OPENAI_TTS_VOICE, input=text, response_format="pcm")`.
  - La risposta è PCM 24kHz 16-bit mono. Resample a 48kHz (stesso algoritmo `np.interp` usato in ASR ma inverso) o richiedi `response_format="wav"` e lasci il wav-header parsing esistente.
  - La chunking logic a 20ms resta identica.
- Aggiorna `apps/tts/tests/test_service.py` per mockare `OpenAI` invece di `speechsdk`.
- Aggiorna `aiutami/settings.py` (rimozione `AZURE_SPEECH_*` per TTS, ma lascia quelle per ASR per ora).

**Test:** i test TTS esistenti verificano l'interfaccia (`synthesize_stream` + callback). Aggiorna i mock.

**Commit:** `refactor(tts): migrate from Azure Speech to OpenAI TTS (gpt-4o-mini-tts)`

### Step 3 — Migrazione STT (Realtime transcription)

La parte più delicata. Procedo in due sotto-commit.

#### 3a. Nuovo client Realtime

- Crea `apps/asr/openai_realtime_client.py` con classe `OpenAIRealtimeTranscriptionClient`:
  - Stessa interfaccia di `AzureStreamingClient` (`start()`, `push_audio(bytes)`, `stop()`, callback `on_partial`, `on_final`, `queue_size`).
  - Internamente: connessione WebSocket persistente verso `wss://api.openai.com/v1/realtime?intent=transcription`.
  - Invia `transcription_session.update` con modello, language, VAD server-side.
  - Writer thread legge dalla queue e invia eventi `input_audio_buffer.append` (audio base64).
  - Reader thread ascolta il WebSocket, gestisce eventi `conversation.item.input_audio_transcription.delta` (→ partial) e `.completed` (→ final).
  - Teardown: `input_audio_buffer.commit`, attesa eventi finali pendenti, chiusura WebSocket.
- Aggiungi dipendenza `websockets` in `requirements.txt` se non presente.

#### 3b. Switch del worker

- In `apps/asr/worker.py`:
  - Sostituisci `from .azure_client import AzureStreamingClient` con `from .openai_realtime_client import OpenAIRealtimeTranscriptionClient as ASRStreamingClient`.
  - Aggiorna `_init_azure_client` (rinominato `_init_asr_client`) per usare `settings.OPENAI_API_KEY`, `settings.OPENAI_STT_MODEL`, `settings.OPENAI_STT_LANGUAGE`.
  - Nessun altro cambio nel worker (resampling, warmup, cache transcript, diagnostica identici).
- Elimina `apps/asr/azure_client.py`.

**Test:** sessione di test manuale end-to-end (parla in WebRTC, verifica partial/final in log, verifica che TurnsConsumer riceva i segmenti). Gli unit test esistenti su `ASRStreamWorker` mockano il client, quindi passano se i mock vengono aggiornati.

**Commit 3a:** `feat(asr): add OpenAI Realtime transcription client (unused)`
**Commit 3b:** `refactor(asr): switch worker from Azure to OpenAI Realtime transcription`

### Step 4 — Cleanup finale

- Rimuovi da `requirements.txt`:
  ```
  azure-cognitiveservices-speech==1.38.0
  ```
- Rimuovi da `aiutami/settings.py`:
  ```
  AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, AZURE_SPEECH_LANGUAGE, AZURE_TTS_VOICE
  ```
- Rimuovi da `.env.example` le variabili Azure.
- Aggiorna `CLAUDE.md`:
  - Sezione "Environment Variables" → rimpiazza Azure con OpenAI.
  - Sezione app/`asr`, `tts`, `moderation` → aggiorna provider.
- Rebuild immagine Docker per verificare che senza `azure-cognitiveservices-speech` tutto giri.

**Test:** suite completa + sessione E2E manuale.

**Commit:** `chore(deps): remove Azure Speech SDK, cleanup env and docs`

---

## 5. Strategia di test

### 5.1 Test automatizzati esistenti

I 229 test esistenti coprono:
- Logica di moderation (prompt, trigger, state) → mockano il client LLM, basta cambiare il path di mock.
- Logica di turn-taking → non toccano STT direttamente.
- Flusso report → mocka LLM.
- Tasks (registry, murder_mystery, generic, nasa_moon) → indipendenti.

**Azione:** aggiornare i mock dove necessario (Step 1, 2, 3b), niente nuovi test unit.

### 5.2 Test manuali end-to-end

Dopo Step 1: avvia backend con nuova chiave, crea sessione, invia un "turno" text-only via shell Django (`ModerationService.handle_human_turn_ended(...)`) e verifica output LLM.

Dopo Step 2: dalla shell chiama `TTSService().synthesize_stream("Ciao, sono il moderatore.", ...)` e verifica che arrivi audio a 48kHz.

Dopo Step 3: sessione WebRTC completa con 1-2 partecipanti, verifica trascrizioni partial/final nei log, verifica che il flusso turn-ended trigger-i l'intervento AI.

### 5.3 Rollback

Ogni step è un commit separato. Se uno step introduce regressioni, `git revert <sha>` del singolo commit. Il codice Azure rimosso si recupera con `git show HEAD~N:<path>`.

---

## 6. Rischi e mitigazioni

| Rischio | Probabilità | Mitigazione |
|---|---|---|
| Qualità voce `onyx` inferiore a `DiegoNeural` in italiano | Media | Proviamo `nova` come alternativa; scelta modificabile via env var. |
| Realtime API ha rate limit / concurrency più basso di Azure | Bassa | Test con 3 streams simultanei prima di concludere. In caso, fallback a `gpt-4o-mini-transcribe` batch su chunks di 1-2s con VAD lato server. |
| Latenza partial transcription maggiore di Azure | Bassa | Test empirico. In caso di degrado accettiamo ~200-400ms in più visto che il trigger del turno scatta comunque sul "final". |
| JSON mode di OpenAI non accetta il nostro prompt | Molto bassa | Modalità opt-in; se serve lo disattiviamo e restiamo col parsing try/except esistente. |
| Formato PCM TTS non matcha audio hub | Media | Richiediamo `response_format="wav"` (header incluso) o resample 24kHz→48kHz con `np.interp`. |

---

## 7. Stima e ordine

Ordine di commit sul branch `main`:
1. Step 0 — env + settings
2. Step 1 — LLM moderation + reports
3. Step 2 — TTS
4. Step 3a — nuovo client Realtime (dormiente)
5. Step 3b — switch worker ASR
6. Step 4 — cleanup

LLM e TTS sono drop-in quasi puri (~30 min ciascuno con test).
STT è il grosso del lavoro (~2-3h per protocollo + test E2E).
Cleanup ~15 min.

---

## 8. Checklist finale

- [ ] Step 0 committato
- [ ] Step 1 committato, test verdi
- [ ] Step 2 committato, test verdi, TTS manuale OK
- [ ] Step 3a committato (client solo, non usato)
- [ ] Step 3b committato, test verdi, E2E WebRTC OK
- [ ] Step 4 committato, `azure-cognitiveservices-speech` rimosso, docker build OK
- [ ] `CLAUDE.md` aggiornato
- [ ] `MEMORY.md` aggiornato con "migrazione OpenAI completata"
