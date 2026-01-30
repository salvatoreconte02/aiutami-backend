# Design: Redesign chiamata LLM modalità "normal"

**Data**: 2026-01-30
**Stato**: Da approvare

## Obiettivo

Rivedere la chiamata LLM che avviene alla fine di ogni turno umano in modalità "normal" (non forced_summary, non forced_conclusion). Attualmente il prompt è generico ("decidi tu se intervenire") e non dà criteri chiari.

## Contesto attuale

Il file `apps/moderation/service.py` contiene:
- `_call_llm()` - chiamata generica per tutte le modalità
- System prompt minimal alle righe 216-236
- Input povero: solo `summary_in`, `last_turn`, `session_phase`, `speaker_name`

## Design proposto

### 1. Dati in input all'LLM

Struttura arricchita con informazioni necessarie per decisioni di moderazione:

```python
llm_input = {
    "mode": "normal",
    "scenario": {
        "type": "murder_mystery",
        "objective": "Discutere gli indizi e scoprire chi è l'assassino",
    },
    "discussion": {
        "summary": "...",           # riassunto cumulativo
        "last_turn": "...",         # trascrizione ultimo turno
        "last_speaker": "Mario",    # chi ha appena parlato
    },
    "participants": {
        "count": 4,
        "turns": {                  # turni per partecipante
            "Mario": 5,
            "Lucia": 2,
            "Paolo": 1,
            "Anna": 0
        }
    },
    "session": {
        "phase": "ACTIVE",
        "total_turns": 8,           # turni umani totali finora
    }
}
```

### 2. System prompt per modalità normal

```
Sei il moderatore AI di una discussione di gruppo su AIutami.

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
}
```

### 3. Modifiche al backend

#### 3.1 ModerationState (state.py)

Aggiungere campo per tracking turni per partecipante:

```python
@dataclass
class ModerationState:
    summary: str
    human_turns_since_last_summary: int
    ai_interventions_count: int
    last_ai_intervention_at: Optional[datetime]
    conclusion_reason: Optional[str]
    forced_conclusion_done: bool
    turns_per_participant: Dict[str, int]  # NUOVO: {"speaker_name": count}

    @classmethod
    def initial(cls) -> "ModerationState":
        return cls(
            summary=DEFAULT_SUMMARY,
            human_turns_since_last_summary=0,
            ai_interventions_count=0,
            last_ai_intervention_at=None,
            conclusion_reason=None,
            forced_conclusion_done=False,
            turns_per_participant={},  # NUOVO
        )
```

Aggiornare `load_moderation_state` e `save_moderation_state` per gestire il nuovo campo.

#### 3.2 ModerationService (service.py)

In `handle_human_turn_ended`, incrementare il contatore:

```python
# Incrementare il contatore per lo speaker
if speaker_name:
    state.turns_per_participant[speaker_name] = (
        state.turns_per_participant.get(speaker_name, 0) + 1
    )
```

In `_call_llm`, costruire il nuovo input strutturato:

```python
# Calcola totale turni
total_turns = sum(state.turns_per_participant.values())

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
        "count": len(state.turns_per_participant) or participants_count,
        "turns": state.turns_per_participant,
    },
    "session": {
        "phase": session_phase,
        "total_turns": total_turns,
    },
}
```

#### 3.3 System prompt

Creare funzione dedicata per costruire il prompt in base alla modalità:

```python
@classmethod
def _build_system_prompt(cls, mode: str) -> str:
    if mode == "normal":
        return cls._build_normal_mode_prompt()
    elif mode == "forced_summary":
        return cls._build_forced_summary_prompt()
    elif mode == "forced_conclusion":
        return cls._build_forced_conclusion_system_prompt()
    return cls._build_normal_mode_prompt()  # fallback
```

### 4. Criteri di intervento (riassunto)

| Scenario | Trigger | Intervento immediato? |
|----------|---------|----------------------|
| Monopolizzazione | Un partecipante ha parlato >> degli altri | No, solo se persiste |
| Esclusione | Un partecipante ha 0 o quasi 0 turni | No, solo se evidente |
| Off-topic evidente | Parlano di cose completamente scollegate | Sì |
| Off-topic parziale | Divagano ma c'è un filo logico | No, aspetta |
| Conflitto/insulti | Toni aggressivi, attacchi personali | Sì |
| Richiesta diretta | "Moderatore, puoi aiutarci?" | Sì |

### 5. Filtri backend

Dopo la decisione dell'LLM, il backend applica filtri **solo per modalità normal**:

| Filtro | Valore | Si applica a |
|--------|--------|--------------|
| Soglia score | `>= 0.7` | Solo normal |
| Max interventi | 10 per sessione | Solo normal |
| Cooldown | 30 secondi | Solo normal |
| Fase sessione | Solo ACTIVE | Solo normal |

**Importante**: Gli interventi meccanici (forced_summary, forced_conclusion) **non** incrementano i contatori e **non** resettano il cooldown. Questo perché:
- Sono prevedibili e necessari (riassunto periodico, conclusione obbligatoria)
- Non devono "rubare" budget agli interventi soft dove il moderatore reagisce a problemi reali

#### Modifica al codice

Attualmente `handle_human_turn_ended` incrementa sempre i contatori:
```python
if ai_should_speak:
    state.ai_interventions_count += 1
    state.last_ai_intervention_at = datetime.utcnow()
```

Deve diventare:
```python
if ai_should_speak and mode == "normal":
    state.ai_interventions_count += 1
    state.last_ai_intervention_at = datetime.utcnow()
```

### 6. Output atteso

Struttura invariata ma con `reason` codificato:

```json
{
  "updated_summary": "Mario ha proposto che il colpevole sia il maggiordomo...",
  "should_ai_speak": true,
  "message_to_say": "Lucia, tu cosa ne pensi dell'ipotesi di Mario?",
  "reason": "exclusion",
  "intervention_score": 0.75
}
```

## File da modificare

1. `apps/moderation/state.py` - Aggiungere `turns_per_participant`
2. `apps/moderation/service.py` - Nuovo input strutturato + nuovo system prompt
3. `apps/moderation/tests.py` - Aggiornare test per nuovo campo

## Note implementative

- Il campo `turns_per_participant` usa `speaker_name` come chiave (non `user_id`) per rendere l'input più leggibile all'LLM
- Il `speaker_name` è già disponibile nel flusso (viene passato da `ws_consumer.py`)
- Lo scenario è hardcoded a "murder_mystery" per ora; in futuro si può parametrizzare
- Il `participants_count` potrebbe essere derivato da `len(turns_per_participant)` ma serve un fallback per la prima chiamata

## Checklist implementazione

- [ ] Aggiungere `turns_per_participant` a `ModerationState`
- [ ] Aggiornare `load_moderation_state` e `save_moderation_state`
- [ ] Aggiornare `handle_human_turn_ended` per incrementare contatore turni
- [ ] Modificare incremento `ai_interventions_count` per solo mode "normal"
- [ ] Creare `_build_normal_mode_prompt()` con nuovo system prompt
- [ ] Aggiornare `_call_llm` con nuovo input strutturato
- [ ] Passare `state` a `_call_llm` per accesso a `turns_per_participant`
- [ ] Aggiornare test esistenti
- [ ] Test manuale con sessione reale
