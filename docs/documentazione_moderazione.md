# Documentazione Tecnica — Logica di Moderazione delle Sessioni Vocali

*Versione aggiornata: 2026-02-05 (aggiunto AI playout drain)*

## 1. Obiettivo della moderazione

Il sistema di moderazione ha tre responsabilità principali:

- Garantire il corretto flusso dei turni vocali, evitando sovrapposizioni non consentite.
- Analizzare la conversazione e intervenire in forma:
  - **meccanica** (messaggi fissi basati su logica e tempo),
  - **soft** (proposte facoltative dal modello),
  - **hard** (interventi obbligatori sintetici tramite modello).
- Mantenere uno stato persistente (**summary + contatori**) che consente al moderatore di comprendere l'evoluzione della discussione.

La moderazione è interamente orchestrata dal backend, che ha sempre l'ultima decisione sulla possibilità o meno di far parlare il moderatore.

---

## 2. Architettura generale

L'architettura è composta da cinque pilastri.

### 2.1 TurnManager (gestione turni vocali)

Responsabile di:

- apertura e chiusura di un turno umano;
- gestione turni AI;
- gestione prenotazioni;
- controllo stato del microfono;
- broadcast WebSocket degli eventi generati.

Il TurnManager non conosce la moderazione. Si limita a mantenere lo stato vocale in Redis e a generare eventi atomici (`HUMAN_STARTED`, `HUMAN_ENDED`, `AI_STARTED`, …).

### 2.2 ModerationState (stato logico della moderazione)

Conservato in Redis, contiene:

- summary della discussione aggiornato progressivamente;
- numero di turni umani dall'ultimo riassunto;
- numero di interventi AI già effettuati;
- timestamp dell'ultimo intervento AI;
- `conclusion_reason`: motivo della conclusione (`"timer_expired"` o `"all_participants_ready"`);
- `forced_conclusion_done`: flag per evitare ripetizioni del messaggio di chiusura;
- `turns_per_participant`: dizionario con conteggio turni per ogni partecipante (`{"Mario": 5, "Lucia": 2}`).

È aggiornato a ogni turno umano, sempre dopo l'eventuale analisi del modello.

### 2.3 ModerationTimersState (stato dei timer temporali)

Conservato in Redis, contiene:

- `session_started_at`: timestamp inizio sessione (immutabile dopo l'avvio)
- `last_any_activity_at`: ultimo evento di attività (reset per NO PUSH)
- `last_user_speak_at`: dizionario con ultimo turno per ogni utente
- Flag di notifica: `no_push_notified`, `timer_25_notified`, `timer_30_notified`
- `inactive_notified_user_ids`: utenti già notificati per inattività
- Contatori solleciti vocali per utente (max 2 per sessione)

### 2.4 Trigger Engine (determinazione dei trigger)

Responsabile della valutazione di due famiglie di eventi:

**Trigger post-turno** — Eseguiti alla chiusura di ogni turno umano:
- Prenotazione intervento
- Pronti alla conclusione
- FORCED_SUMMARY

**Trigger alla transizione** — Eseguiti immediatamente quando la sessione passa a CONCLUSION:
- FORCED_CONCLUSION (non più post-turno, scatta alla transizione)

**Trigger temporali** — Valutati ogni 5 secondi:
- NO PUSH (silenzio prolungato)
- UTENTE INATTIVO (avviso testuale + sollecito vocale)
- TIMER 25 minuti
- TIMER 30 minuti

I trigger temporali non interrompono mai uno speaker attivo.

**Nota tecnica sui trigger temporali:**
- Meccanismo principale: ping dal frontend (`turns.ping`) ogni 5 secondi
- Fallback: background task server-side (`_trigger_loop`)
- Il ping è attualmente necessario perché il background task parte solo se il client si connette quando la sessione è già ACTIVE

### 2.5 ModerationService (gestione chiamata modello e regole backend)

Dato un `hard_action` o una richiesta soft, il servizio:

- determina la modalità di chiamata LLM (`normal`, `forced_summary`, `forced_conclusion`);
- chiama il modello;
- aggiorna sempre il summary;
- applica il filtro backend (limite interventi, cooldown, fase sessione, score minimo).

### 2.6 ModerationOrchestrator (flusso completo post-turno)

Unico entry-point della moderazione. Riceve session_id, user_id, testo ultimo turno, fase sessione. Esegue: caricamento stato → valutazione trigger → chiamata ModerationService → costruzione FullModerationDecision.

---

## 3. Trigger Meccanici (senza LLM)

### 3.1 Trigger 1: Prenotazione Intervento

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Fine turno umano, se esiste una prenotazione attiva |
| **Messaggio** | `"Ora la parola va a {nome}, che aveva prenotato."` |
| **Modalità** | Solo testo (NO TTS) |
| **Destinatari** | Tutti i partecipanti |

### 3.2 Trigger 2: Pronti alla Conclusione

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Quando un utente clicca "pronto a concludere" |
| **Se qualcuno parla** | Messaggio in coda, pronunciato a fine turno |
| **Se nessuno parla** | Messaggio pronunciato subito |
| **Modalità** | TTS |
| **Destinatari** | Tutti i partecipanti |

**Varianti messaggio (caso normale - primi utenti pronti):**
1. `"{nome} è pronto a concludere. Se hai capito con certezza di chi si tratta, premi anche tu 'pronto alla conclusione' per terminare la sessione."`
2. `"{nome} ha indicato di essere pronto alla conclusione. Quando anche tu avrai raggiunto una certezza, premi il pulsante per concludere."`
3. `"{nome} si è dichiarato pronto a concludere. Se hai già individuato il colpevole, puoi premere 'pronto alla conclusione'."`
4. `"{nome} è pronto. Ricorda: quando sei sicuro di chi si tratta, premi 'pronto alla conclusione' per avviare la fase finale."`

**Varianti messaggio (caso "manca solo uno"):**
1. `"{nome} è pronto a concludere. Ora manca solo un partecipante per avviare la fase finale."`
2. `"{nome} si è dichiarato pronto. Manca solo una persona: se hai raggiunto una certezza, premi 'pronto alla conclusione'."`
3. `"{nome} è pronto. Quasi tutti hanno deciso: manca solo un voto per concludere la sessione."`

**Varianti messaggio (caso "tutti pronti" - 3/3):**
1. `"Tutti i partecipanti sono pronti. Possiamo avviarci alla fase di conclusione."`
2. `"Tutti hanno deciso. Possiamo avviarci alla fase di conclusione."`
3. `"Siete tutti pronti. Possiamo avviarci alla fase di conclusione."`

**Comportamento transizione 3/3:**
- Quando tutti sono pronti, il messaggio TTS viene pronunciato **prima** della transizione
- La transizione ACTIVE → CONCLUSION avviene **dopo** la fine del TTS
- Se qualcuno sta parlando, il messaggio viene accodato con flag `trigger_conclusion=True`

**Comportamento pulsante:**
- Una volta premuto, non può essere deselezionato
- Dialog di conferma prima di premere (frontend)

### 3.3 Trigger 3: NO PUSH (Silenzio Prolungato)

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | 20 secondi di silenzio (nessuna attività) |
| **Condizione** | Nessuno sta parlando (umano o AI) |
| **Modalità** | TTS |
| **Ripetizione** | Reset dopo che qualcuno parla (può riscattare) |
| **Valutazione** | Background task server ogni 5 secondi |

**Varianti messaggio:**
1. `"Se qualcuno vuole intervenire, può parlare ora o condividere una breve considerazione."`
2. `"C'è un momento di silenzio. Se qualcuno ha un pensiero da condividere, questo è un buon momento."`
3. `"Se qualcuno desidera aggiungere qualcosa alla discussione, può prendere la parola."`
4. `"La discussione è in pausa. Chi vuole intervenire può farlo ora."`

**Note implementative:**
- Il flag `no_push_notified` deve essere resettato in `mark_any_activity()` quando qualcuno parla
- Il timer parte dalla fine dell'ultimo intervento (umano o AI)

### 3.4 Trigger 4: UTENTE INATTIVO

Sistema a due livelli con reset dopo sollecito vocale.

#### Livello 1: Avviso Testuale (5 minuti)

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Utente non parla da 5 minuti |
| **Modalità** | Solo testo |
| **Destinatario** | Solo l'utente interessato (messaggio privato) |
| **Ripetizione** | Ogni 5 minuti dal reset |

**Messaggio:**
`"Non intervieni da un po'. Se vuoi condividere qualcosa, questo è un buon momento."`

#### Livello 2: Sollecito Vocale (10 minuti)

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Utente non parla da 10 minuti |
| **Modalità** | TTS |
| **Destinatario** | Tutti (pubblico) |
| **Reset timer** | Dopo ogni sollecito vocale |
| **Limite** | Max 2 solleciti vocali per utente per sessione |

**Varianti messaggio:**
1. `"{nome}, se vuoi condividere un'idea, questo è un buon momento per intervenire."`
2. `"{nome}, non ti abbiamo ancora sentito. Se hai qualcosa da aggiungere, puoi parlare ora."`
3. `"{nome}, c'è qualcosa che vorresti condividere con il gruppo?"`
4. `"{nome}, se hai un pensiero sulla discussione, sentiti libero di intervenire."`

**Logica temporale (esempio utente mai parla in 30 min):**
- 5 min: avviso testuale
- 10 min: sollecito vocale → reset timer
- 15 min: avviso testuale
- 20 min: sollecito vocale → reset timer (raggiunto limite 2)
- 25 min: avviso testuale
- 30 min: fine sessione

**Payload WebSocket (STATIC_MESSAGE):**
```json
// Livello 1 (testo privato)
{
  "type": "turns.event",
  "event_type": "STATIC_MESSAGE",
  "payload": {
    "text": "Non intervieni da un po'...",
    "use_tts": false,
    "trigger_type": "INACTIVE_USER_TEXT",
    "target_user_id": 123,
    "target_user_name": "Mario"
  }
}

// Livello 2 (voce pubblica)
{
  "type": "turns.event",
  "event_type": "STATIC_MESSAGE",
  "payload": {
    "text": "Mario, se vuoi condividere...",
    "use_tts": true,
    "trigger_type": "INACTIVE_USER_VOICE",
    "target_user_id": 123,
    "target_user_name": "Mario"
  }
}
```

**Gestione frontend:**
- Livello 1: Mostra messaggio solo se `current_user.id == target_user_id`
- Livello 2: Mostra a tutti (è pubblico), `target_user_id` indica chi è il target

### 3.5 Trigger 5: TIMER 25 Minuti

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Sessione raggiunge 25 minuti |
| **Riferimento tempo** | `session_started_at` (immutabile) |
| **Messaggio** | `"Mancano circa cinque minuti alla fine della discussione."` |
| **Modalità** | Solo testo |
| **Ripetizione** | Una sola volta |

**Comportamento frontend:**
- Prima del trigger: nessun timer visivo
- Quando scatta: mostra messaggio + avvia timer visivo di 5 minuti

### 3.6 Trigger 6: TIMER 30 Minuti

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Sessione raggiunge 30 minuti |
| **Se qualcuno parla** | Messaggio accodato, pronunciato a fine turno |
| **Messaggio** | `"Il tempo della discussione è terminato. Potete avviarvi verso la conclusione."` |
| **Modalità** | TTS |
| **Effetto** | Transizione sessione ACTIVE → CONCLUSION |
| **Ripetizione** | Una sola volta |

**Comportamento transizione:**
- Il messaggio TTS viene pronunciato **prima** della transizione
- La transizione ACTIVE → CONCLUSION avviene **dopo** la fine del TTS
- Se qualcuno sta parlando, il messaggio viene accodato con flag `trigger_conclusion=True`
- Comportamento uniforme con il trigger "tutti pronti" (3/3)

---

## 4. Trigger con LLM (da definire)

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

### 4.2 Trigger 8: FORCED_CONCLUSION

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Immediatamente alla transizione ACTIVE → CONCLUSION |
| **Cause transizione** | Timer 30 min scaduto OPPURE tutti pronti (3/3) |
| **Modalità** | TTS (chiamata LLM dedicata) |
| **Ripetizione** | Una sola volta (flag `forced_conclusion_done`) |

**Comportamento:**
- Scatta **immediatamente** quando la sessione transiziona a CONCLUSION
- I turni umani sono bloccati in fase CONCLUSION (errore `SESSION_IN_CONCLUSION`)
- Usa una chiamata LLM dedicata (`call_llm_for_conclusion`) separata dalla moderazione normale

**Chiamata LLM:**

| Parametro | Valore |
|-----------|--------|
| Model | `gpt-4o-mini` (o env `AZURE_OPENAI_MODEL`) |
| Temperature | `0.5` |
| Max tokens | `512` |

**System Prompt:**
```
Sei il moderatore AI di AIutami, una piattaforma per discussioni di gruppo moderate.

La sessione sta per concludersi e devi generare il messaggio finale di chiusura.

## Il tuo compito

Genera un messaggio che:
1. **Riassuma la discussione** - Parti dal summary fornito e adattalo per un contesto di chiusura.
2. **Dia istruzioni per il voto** - Spiega cosa devono fare i partecipanti.
3. **Ringrazi i partecipanti** - Concludi con un ringraziamento.

## Tono e stile
- Caldo e coinvolgente, non robotico
- Lunghezza: 100-150 parole (30-60 secondi di parlato)

## Adatta il tono al motivo della conclusione
- `timer_expired`: riconosci il lavoro svolto nonostante il limite di tempo
- `all_participants_ready`: valorizza la loro decisione di concludere

## Output
JSON con: updated_summary, message_to_say
```

**User Message (JSON):**
```json
{
    "mode": "forced_conclusion",
    "summary_in": "<summary corrente>",
    "conclusion_reason": "timer_expired" | "all_participants_ready",
    "session_duration_minutes": 30,
    "scenario": {
        "type": "murder_mystery",
        "vote_action": "selezionare il colpevole",
        "vote_outcome": "scoprirete se avete indovinato l'assassino"
    },
    "language": "it"
}
```

**Fallback (se LLM fallisce):**
- `timer_expired`: "Il tempo a disposizione è terminato. Ecco un breve riepilogo..."
- `all_participants_ready`: "Avete deciso di procedere alla votazione. Ecco un breve riepilogo..."

### 4.3 Trigger 9: Intervento Normal (Soft)

| Aspetto | Valore |
|---------|--------|
| **Quando scatta** | Ogni fine turno umano, durante fase ACTIVE |
| **Condizione** | `hard_action = NONE` (nessun trigger obbligatorio) |
| **Modalità** | TTS se `intervention_score >= 0.7` |
| **Budget** | Max 10 interventi per sessione |
| **Cooldown** | 30 secondi tra interventi |

**Input strutturato all'LLM:**

```json
{
  "mode": "normal",
  "scenario": {
    "type": "murder_mystery",
    "objective": "Discutere gli indizi e scoprire chi è l'assassino"
  },
  "discussion": {
    "summary": "Riassunto cumulativo della discussione",
    "last_turn": "Trascrizione dell'ultimo turno parlato",
    "last_speaker": "Nome dello speaker"
  },
  "participants": {
    "count": 4,
    "turns": {"Mario": 5, "Lucia": 2, "Paolo": 1, "Anna": 0}
  },
  "session": {
    "phase": "ACTIVE",
    "total_turns": 8
  },
  "language": "it"
}
```

**Criteri di intervento LLM:**

L'LLM interviene (imposta `should_ai_speak: true` e `intervention_score >= 0.7`) solo se rileva:

1. **Monopolizzazione** - Un partecipante ha parlato molti più turni degli altri e continua a dominare
2. **Esclusione** - Un partecipante non ha quasi mai parlato e nessuno lo coinvolge
3. **Off-topic evidente** - La discussione deraglia completamente (es. parlano di cose scollegate dal caso)
4. **Conflitto** - Toni aggressivi, insulti, attacchi personali
5. **Richiesta diretta** - Qualcuno chiede esplicitamente aiuto al moderatore

**NON interviene per:**
- Off-topic parziali (aspetta auto-correzione del gruppo)
- Silenzi brevi o pause naturali
- Disaccordi civili (parte sana della discussione)

**Scala `intervention_score`:**
| Range | Significato |
|-------|-------------|
| 0.0-0.3 | Tutto ok, nessun problema |
| 0.4-0.6 | Situazione da monitorare ma non critica |
| 0.7-0.8 | Problema evidente, intervento consigliato |
| 0.9-1.0 | Problema grave (insulti, off-topic totale), intervento necessario |

**Filtri backend (dopo decisione LLM):**

Il backend applica filtri aggiuntivi **solo** per mode=normal (i mode forced_summary e forced_conclusion bypassano questi filtri):

- Soglia score: `intervention_score >= 0.7` richiesto per parlare
- Max interventi: 10 per sessione (`ai_interventions_count`)
- Cooldown: 30 secondi tra interventi (`last_ai_intervention_at`)
- Fase: solo durante ACTIVE

**Nota importante:** Gli interventi `forced_summary` e `forced_conclusion` **NON** incrementano `ai_interventions_count` e **NON** sono soggetti a cooldown.

**Stile risposta:**
- Tono: gentile, indiretto, mai autoritario
- Lunghezza: 1-2 frasi (20-30 parole max)
- Esempi: `"Lucia, tu cosa ne pensi di questo indizio?"` / `"Interessante, ma tornando al caso..."`

**Output LLM (JSON):**
```json
{
  "updated_summary": "Riassunto aggiornato includendo l'ultimo turno",
  "should_ai_speak": true,
  "message_to_say": "Il messaggio da dire (null se should_ai_speak=false)",
  "reason": "monopolization | exclusion | off_topic | conflict | user_request | all_ok",
  "intervention_score": 0.75
}
```

---

## 5. Costanti di Configurazione

| Costante | Valore | Descrizione |
|----------|--------|-------------|
| `NO_PUSH_THRESHOLD` | 20 secondi | Soglia silenzio per NO PUSH |
| `INACTIVE_TEXT_THRESHOLD` | 5 minuti | Soglia per avviso testuale inattività |
| `INACTIVE_USER_THRESHOLD` | 10 minuti | Soglia per sollecito vocale inattività |
| `MAX_VOICE_SOLICITS_PER_USER` | 2 | Limite solleciti vocali per utente |
| `TIMER_25_THRESHOLD` | 25 minuti | Avviso tempo rimanente |
| `TIMER_30_THRESHOLD` | 30 minuti | Fine discussione |
| `TRIGGER_LOOP_INTERVAL` | 5 secondi | Frequenza background task |
| `FORCED_CONCLUSION_TEMPERATURE` | 0.5 | Temperature LLM per tono caldo |
| `FORCED_CONCLUSION_MAX_TOKENS` | 512 | Max tokens per messaggio chiusura |
| `MAX_AI_INTERVENTIONS_PER_SESSION` | 10 | Budget interventi normal mode |
| `AI_INTERVENTION_COOLDOWN` | 30 secondi | Cooldown tra interventi normal mode |
| `NORMAL_MODE_SCORE_THRESHOLD` | 0.7 | Soglia intervention_score per parlare |
| `NORMAL_MODE_TEMPERATURE` | 0.4 | Temperature LLM per normal mode |
| `SUMMARY_TURNS_INTERVAL` | 4 | Turni umani tra ogni FORCED_SUMMARY |
| `FORCED_SUMMARY_TEMPERATURE` | 0.4 | Temperature LLM per forced_summary |
| `FORCED_SUMMARY_MAX_TOKENS` | 512 | Max tokens per messaggio summary |

---

## 6. Sistema Pending Messages

I messaggi che non possono essere riprodotti immediatamente (perché qualcuno sta parlando) vengono accodati in Redis tramite `pending_messages.py`:

- `enqueue_message(session_id, text, trigger_type, trigger_conclusion=False)`: accoda messaggio
- `dequeue_all_messages(session_id)`: svuota coda e ritorna messaggi
- `has_pending_messages(session_id)`: verifica se ci sono messaggi in coda

**Struttura PendingMessage:**
```python
@dataclass
class PendingMessage:
    text: str
    trigger_type: str
    created_at: datetime
    trigger_conclusion: bool = False  # Se True, dopo il TTS transiziona a CONCLUSION
```

**Flag `trigger_conclusion`:**
- Usato per messaggi che devono causare transizione ACTIVE → CONCLUSION
- Applicabile a: trigger "tutti pronti" (3/3), timer 30 minuti
- La transizione avviene **dopo** la riproduzione del TTS

**Blocco accodamento:**
- Quando esiste un messaggio con `trigger_conclusion=True` in coda, tutti i nuovi messaggi vengono ignorati
- Questo garantisce che il messaggio di conclusione sia sempre l'ultimo riprodotto
- I messaggi già accodati prima del messaggio di conclusione vengono mantenuti

TTL: 1 ora. I messaggi vengono riprodotti appena il turno torna IDLE.

---

## 7. Diagramma Architetturale

```
┌──────────────────────────────────────────┐
│                 FRONTEND                 │
│   WebSocket → turns.* messages           │
│   Click → ready_to_conclude              │
└──────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│             WS CONSUMER (turns)          │
│  - riceve end_speak                      │
│  - chiude il turno                       │
│  - invoca ModerationOrchestrator         │
│  - gestisce i turni AI                   │
│  - background task trigger temporali     │
│  - FORCED_CONCLUSION alla transizione    │
└──────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│          MODERATION ORCHESTRATOR         │
│  - trigger post turno                    │
│  - chiamata ModerationService            │
│  - decisione finale                      │
└──────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│            MODERATION SERVICE            │
│  - chiama LLM (soft/hard)                │
│  - aggiorna summary                      │
│  - filtra interventi                     │
└──────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│             TRIGGER ENGINE               │
│  - prenotazioni / pronti                 │
│  - NO PUSH / inattivo                    │
│  - timer 25'/30'                         │
│  - riassunto (FORCED_SUMMARY)            │
└──────────────────────────────────────────┘
                 │
                 ▼
┌──────────────────────────────────────────┐
│             TURN MANAGER                 │
│  - HUMAN / AI SPEAKING                   │
│  - prenotazioni                          │
│  - priority window                       │
└──────────────────────────────────────────┘
```

---

## 8. Votazione e Report (CONCLUSION → CLOSED)

### 8.1 Flusso Votazione

1. **Entrata in CONCLUSION**: La sessione entra in CONCLUSION (via timer 30min o 3/3 pronti)
2. **TTS forced_conclusion**: Il moderatore pronuncia il messaggio di chiusura
3. **AI_ENDED**: Frontend riceve evento e abilita i bottoni di voto
4. **Voti**: I partecipanti votano uno alla volta
   - `POST /api/sessions/{id}/vote/` con `{"suspect": "Eddie|Mickey|Billy"}`
   - Ogni voto genera evento WebSocket `VOTE_CAST`
5. **ALL_VOTED**: Quando tutti votano, broadcast `ALL_VOTED` con risultati completi
6. **Countdown**: 15 secondi per visualizzare i risultati
7. **Chiusura**:
   - Host può anticipare con `POST /api/sessions/{id}/close/`
   - Altrimenti timeout automatico (non implementato MVP)
8. **Report**: LLM genera `report_text`, sessione passa a CLOSED

### 8.2 Endpoint Votazione

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| POST | `/api/sessions/{id}/vote/` | Registra voto |
| GET | `/api/sessions/{id}/vote-status/` | Stato voti |
| POST | `/api/sessions/{id}/close/` | Chiusura anticipata (host) |
| GET | `/api/sessions/{id}/report/` | Download PDF |

### 8.3 Costanti MVP

```python
MURDER_MYSTERY_SUSPECTS = ["Eddie", "Mickey", "Billy"]
MURDER_MYSTERY_GUILTY = "Eddie"
REVEAL_TIMEOUT_SECONDS = 15
```

### 8.4 WebSocket Events

- `VOTE_CAST`: `{"user_id": 123}` - qualcuno ha votato
- `ALL_VOTED`: risultati completi con `results`, `guilty`, `success_rate`, `closing_in_seconds`
- `SESSION_CLOSED`: sessione chiusa, redirect a storico

### 8.5 Report PDF

Il report PDF viene generato on-demand quando un partecipante chiama `GET /api/sessions/{id}/report/`.

**Contenuto:**
- Titolo sessione e data
- Risultato finale (colpevole, percentuale successo)
- Tabella voti con esito per partecipante
- Analisi generata da LLM (se disponibile)
- Riassunto discussione

**Requisiti:**
- Solo partecipanti possono scaricare
- Solo sessioni in stato CLOSED

---

## 9. Messaggio Introduttivo del Moderatore

Quando una sessione passa da LOBBY ad ACTIVE, il moderatore AI pronuncia automaticamente un messaggio di benvenuto che spiega come usare l'applicativo.

### 9.1 Stato AI_INTRODUCING

Durante l'introduzione, lo stato dei turni è `AI_INTRODUCING`:
- Blocca `request_speak` (ritorna errore `INTRO_IN_PROGRESS`)
- Blocca `request_reserve` (ritorna errore `INTRO_IN_PROGRESS`)
- Considerato "qualcuno sta parlando" per i trigger temporali
- Transiziona a `IDLE` solo quando il TTS finisce

### 9.2 Flusso

1. `SessionStartView.post()` imposta lo stato turni a `AI_INTRODUCING` e marca l'intro come pendente
2. Il trigger loop (ogni 5s) rileva l'intro pendente
3. Dopo un delay di ~2.5s, viene generato e pronunciato il messaggio intro via TTS
4. Al termine del TTS, lo stato transiziona a `IDLE` e i partecipanti possono interagire

### 9.3 Messaggio Template

Il messaggio include i nomi dei partecipanti e le istruzioni per:
- Usare il pulsante microfono per parlare
- Prenotarsi se qualcuno sta già parlando
- Usare "Pronto alla conclusione" quando pronti

### 9.4 Gestione Errori

- Se il TTS fallisce, il messaggio viene inviato come testo via WebSocket
- Il flag `intro_pending` ha un TTL di 300 secondi come sicurezza

### 9.5 Redis Keys

- `session:intro_pending:{session_id}` - Flag booleano che indica intro pendente (TTL 300s)

---

## 10. AI Playout Drain

### 10.1 Problema

Quando l'AI parla, la sintesi TTS (`synthesize_stream()`) produce chunk audio che vengono accodati nei buffer dei `ForwardingAudioTrack` di ciascun peer WebRTC. La sintesi termina prima che tutti i buffer siano stati riprodotti (tipicamente ~1s di ritardo). Senza drain, `AI_ENDED` veniva emesso al termine della sintesi, non al termine del playout reale.

### 10.2 Soluzione

Dopo il completamento della sintesi TTS, il backend attende che i buffer audio WebRTC si svuotino prima di emettere `AI_ENDED`:

```
synthesize_stream() ritorna
   ↓
hub.mark_ai_stream_end()     → segnala ai track: non arrivano più chunk
   ↓
await hub.wait_ai_playout()  → attende che i buffer si svuotino (max 10s)
   ↓
hub.set_speaker(None)        → ora è davvero finito
AI_ENDED emesso
```

### 10.3 Punti di applicazione

Il drain è applicato in tutti e tre i punti che emettono `AI_ENDED`:

1. **`_handle_end_speak()`** — Intervento LLM (normal mode e forced_summary)
2. **`_execute_tts_message()`** — Messaggi time-based (NO PUSH, inattività, timer, pronti alla conclusione)
3. **`_execute_intro_message()`** — Messaggio introduttivo

### 10.4 Gestione edge cases

- **Nessun peer connesso**: `wait_ai_playout()` ritorna subito
- **Peer disconnesso durante playout**: il track è chiuso, il timeout scatta e si procede
- **Timeout safety**: max 10 secondi di attesa, poi procede comunque
