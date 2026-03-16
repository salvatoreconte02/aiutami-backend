# A Multi-party Conversational Social Robot Using LLMs

- **Autori**: Addlesee, Cherakara, Nelson, Hernandez-Garcia, Gunson, Sieinska, Romeo, Dondrup, Lemon
- **Anno**: 2024
- **Fonte**: HRI '24 Companion (ACM/IEEE International Conference on Human-Robot Interaction)
- **DOI**: 10.1145/3610978.3641112
- **Citazioni**: 23
- **Codice**: https://github.com/AddleseeHQ/mp-llm-demo-prompts

## Problema affrontato

I sistemi conversazionali commerciali (Siri, Alexa) e la maggior parte della ricerca sono dyadic (1 utente + 1 sistema). Questo e un limite critico quando si deployano robot sociali in spazi pubblici (ospedali, musei, aeroporti) dove piu persone interagiscono contemporaneamente. Le sfide specifiche delle MPC: (1) riconoscere chi ha parlato, (2) riconoscere a chi e indirizzata l'utterance, (3) generare risposte appropriate nel contesto multiparty.

## Setting

Robot sociale ARI deployato come receptionist in sala d'attesa di una memory clinic ospedaliera (progetto EU H2020 SPRING). Pazienti anziani con possibili deficit cognitivi + accompagnatori. Il sistema deve essere utile e intrattenente.

## Architettura (Pipeline STT-TTT-TTS)

Il sistema segue un flusso a componenti modulari (Figure 2 del paper):

1. **ASR** -- Speech-to-Text (input audio dal robot)
2. **Gaze Detection** -- Rilevamento dello sguardo dell'utente per capire a chi si rivolge
3. **Addressee Detection (LLM prompt)** -- "Is ARI the addressee?" Usa contenuto della frase + segnale di gaze. Se no -> Do Nothing (il robot ascolta senza interrompere)
4. **Full Utterance Check (LLM prompt)** -- "Is it a full utterance?" Se si -> genera risposta. Se no -> genera Clarification Request (iCR)
5. **LLM (Vicuna-13b-v1.5)** -- Genera risposta grounded alle informazioni dell'ospedale (in-prompt knowledge) oppure gestisce out-of-domain (barzellette, quiz, chit-chat)
6. **TTS** -- Text-to-Speech per output vocale
7. **Movement** -- Gesti del robot (braccia, testa, occhi)

### Dettaglio dei componenti chiave

**Addressee Detection**
- Prompt all'LLM che chiede se l'utente sta parlando al robot o all'altra persona
- Input: contenuto testuale + segnale di gaze
- Se il robot non e il destinatario: "Do Nothing" -- passa il turno e continua ad ascoltare
- Questo e fondamentale per non interrompere conversazioni umano-umano

**Clarification Requests (iCR)**
- Il problema: in una memory clinic, le pause sono frequenti (deficit cognitivi). L'ASR puo interpretare una pausa come fine turno
- Soluzione: se l'utterance non e completa, il robot genera una clarification request naturale invece di rispondere con nonsense
- Esempi dal corpus umano di iCR usati come few-shot examples
- Codice: https://github.com/AddleseeHQ/interruption-recovery

**Response Generation**
- LLM con in-prompt knowledge (info ospedale, orari, indicazioni)
- Guardrails: "you are not qualified to give medical advice", "you do not have access to patient records"
- Problema hallucination: il mondo statico dell'LLM puo causare errori (es. citare un ristorante inesistente, dire "devi digiunare dopo le 10am" quando il paziente dice di avere fame)
- Out-of-domain: l'LLM gestisce naturalmente barzellette, quiz, chit-chat grazie al pre-training

**Turn-Taking**
- Il sistema decide quando prendere il turno basandosi su:
  - Addressee detection (e indirizzato al robot?)
  - Full utterance detection (l'utente ha finito di parlare?)
- NON c'e un sistema esplicito di richiesta turno -- il robot decide autonomamente

## Risultati

- Sistema funzionante deployato con pazienti reali in ospedale
- Miglioramento rispetto al sistema precedente (Alana V2) che era dyadic e interrompeva ogni turno
- Data collection in corso per valutazione quantitativa

## Limiti

- Paper corto (3 pagine) -- pochi dettagli tecnici e nessuna valutazione quantitativa
- LLM locale (Vicuna-13b) -- non i modelli piu capaci disponibili
- Hallucination problem non risolto (solo mitigato con guardrails nel prompt)
- Gaze detection dipende da hardware del robot -- non generalizzabile
- Nessuna gestione esplicita di conversazioni a 3+ persone (solo 2 umani + robot)

## Rilevanza per la tesi

**Molto alta**. Questo e il lavoro piu direttamente confrontabile con AIutami:

1. **Stessa pipeline**: entrambi usano STT -> LLM -> TTS
2. **Addressee detection vs Turn-taking esplicito**: Addlesee usa gaze + LLM prompt per decidere se rispondere. AIutami usa un sistema esplicito di richiesta turno + reservation window. Approcci complementari.
3. **Clarification requests**: AIutami non ha questa funzionalita -- potrebbe essere un'estensione interessante
4. **Grounding**: Addlesee usa in-prompt knowledge. AIutami usa trigger-based moderation con contesto di sessione (summary evolutivo).
5. **Scalabilita**: Addlesee gestisce 2 umani + 1 robot. AIutami gestisce N partecipanti + 1 moderatore AI.
6. **Contesto**: Addlesee in healthcare (memory clinic). AIutami in contesti vari (murder mystery, terapeutico, accademico, lavorativo).

### Differenze chiave con AIutami

| Aspetto | Addlesee (ARI Robot) | AIutami |
|---------|---------------------|---------|
| Modalita | Multimodale (speech + gaze + gesti) | Solo speech |
| Turn-taking | Implicito (addressee detection) | Esplicito (request + reservation) |
| Partecipanti | 2 umani + 1 robot | N umani + 1 AI moderator |
| Ruolo AI | Receptionist/intrattenitore | Moderatore di discussione |
| LLM | Vicuna-13b locale | Azure OpenAI (cloud) |
| Deployment | Robot fisico in ospedale | Web-based (WebRTC) |
| Addressee | Gaze + text analysis | Non necessario (moderatore parla al gruppo) |

## Paper citati da approfondire

- **Addlesee et al. (2023)**: "Multi-party Goal Tracking with LLMs" -- pre-training, fine-tuning, prompt engineering per MPC
- **Gunson et al. (2022)**: sistema precedente (Alana V2) -- utile per capire l'evoluzione
- **Chiyah-Garcia et al. (2023)**: clarificational exchanges in multi-modal dialogue
- **Traum (2004)**: citato anche qui come riferimento fondamentale per MPC
