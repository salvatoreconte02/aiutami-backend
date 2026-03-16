# Controlling AI Agent Participation in Group Conversations: A Human-Centered Approach

- **Autori**: Houde, Brimijoin, Muller, Ross, Silva Moran, Gonzalez, Kunde, Foreman, Weisz
- **Anno**: 2025
- **Fonte**: IUI '25 (30th International Conference on Intelligent User Interfaces), Cagliari, Italy
- **DOI**: 10.1145/3708359.3712089
- **Citazioni**: 7
- **Pagine**: 19
- **Affiliazione**: IBM Research

## Problema affrontato

I conversational agent basati su LLM sono tipicamente progettati per interazioni dyadic (1 utente + 1 agente) dove la meccanica e banale: l'utente scrive, l'agente risponde. Ma nel lavoro reale, molte attivita avvengono in gruppo. Come dovrebbe comportarsi un agente AI in una conversazione di gruppo? Quando intervenire? Quanto contribuire? Chi controlla il suo comportamento? Il paper affronta queste domande attraverso un approccio human-centered.

## Sistema: Koala

**Koala** e un agente conversazionale AI basato su LLM, implementato come bot Slack, progettato per partecipare a sessioni di brainstorming di gruppo.

### Architettura
- **Koala I**: basato su Llama 2
- **Koala II**: basato su Llama 3 (upgrade dopo Study 1)
- L'agente appare come un partecipante nel canale Slack, con tag "APP"

### Due varianti di comportamento
1. **Reactive**: risponde solo quando indirizzato direttamente ("@Koala" o "Koala")
2. **Proactive**: decide autonomamente quando contribuire, basandosi su un meccanismo di self-scoring

### Meccanismo di decisione proattiva (Figure 2)
Per ogni messaggio degli utenti, Koala:
1. Genera una risposta potenziale via LLM
2. L'LLM assegna un punteggio di "value" (0-100) alla risposta
3. Se il valore supera una soglia -> `<SUBMIT>` (pubblica)
4. Se il valore e sotto la soglia -> `<PASS>` (resta in silenzio)
5. Risponde SEMPRE se indirizzato direttamente (target = Koala)

Il prompt include anche logica per identificare source, target, e generare una evaluation testuale del perche rispondere o meno (vedi Appendix A per il prompt completo).

**Logica di controllo esterna**: l'LLM era inaffidabile nell'identificare il destinatario, quindi hanno aggiunto regole esterne (es. forzare risposta se "Koala" nel messaggio, sopprimere se menzionato un altro partecipante).

## Study 1: Brainstorming con Koala I

### Design
- 6 sessioni, 3 partecipanti umani ciascuna (18 totale)
- 3 round di brainstorming da 3 minuti ciascuno su Slack
- Condizioni in ordine fisso: (1) No AI, (2) Reactive AI, (3) Proactive AI
- Topic diversi e controbilanciati (meeting ibridi, chatbot HR, gadget conferenza)
- Dipendenti IBM con relazioni lavorative preesistenti

### Risultati quantitativi
- **73% di tutte le idee** nelle condizioni AI venivano da Koala
- Le idee di Koala costituivano **33% delle top ideas** selezionate
- **72.2% dei partecipanti** preferiva la variante **reactive**
- Tutti preferivano avere Koala piuttosto che non averlo

### Risultati qualitativi - 3 temi

**Tema 1: Vantaggi**
- Help getting started: rimuove il "white page problem"
- Velocita percepita: "much more fluid and expedited"
- Struttura: Koala come "pseudo-moderatore"
- Summarization: riassunti delle idee molto apprezzati
- Validazione: vedere idee simili da Koala dava conferma
- Informazione: colmare gap di conoscenza
- Collaborazione umano-AI: "very innovative ideas resulted combining innovative ideas from people to ask Koala for concrete ideas"

**Tema 2: Svantaggi**
- **Proattivita dirompente**: contributi intrusivi, distraenti, opprimenti
- **Effetto soffocante**: "less room for expressing unique ideas" -- production blocking online
- **Risposte inaccurate**: ~1/3 dei partecipanti noto errori nelle summarization

**Tema 3: Migliorare il comportamento AI**
- Richieste di regolazione dei default: "give some extra time to answer, so you allow real people to answer first"
- Tentativi di controllo in-chat: "koala - leave the rest to us, ok?"
- Ma anche incoraggiamento: "Can Koala help choose the 3 solutions?"

### Citazioni chiave sullo svantaggi della proattivita
- P6.2: "Koala dominated the conversation. It felt like a pedantic student who wouldn't create space for others to participate."
- P4.2: "I was having a hard time building up on the ideas from the others, because everything moved so fast."
- P1.3: "I think I would pick [Proactive AI] if there was a way to temporarily disable koala if needed."

## Koala II: Miglioramenti

### Modifiche al comportamento proattivo
1. Upgrade LLM da Llama 2 a Llama 3 (meno hallucination, context piu lungo)
2. Prompt rivisto: suggerimenti piu mirati, critica costruttiva, idee nuove, meno dominante
3. Soglia di contribuzione resa configurabile dall'utente

### Pannello di controllo (Figure 5)
4 controlli esposti agli utenti:
- **(A) Toggle Proactive/Reactive**: scegliere la variante
- **(B) Proactive contribution threshold**: High (90), Medium (75), Low (50)
- **(C) Where to respond**: nel canale o in un thread
- **(D) Long message display**: mostrare per intero o troncare (>1000 char)

## Study 2: Brainstorming con Koala II

### Design
- Stessi 18 partecipanti (14 disponibili), 9 mesi dopo
- 2 round di brainstorming + discussione sui controlli + design probes
- Nuovi topic (community nel team, riconoscimento contributi)

### Risultati
- Koala II percepito come **migliorato**: "more quiet", "reacted at the right pace", "very natural interaction", "more on topic"
- Nessun gruppo ha scelto di tornare alla variante reactive
- Utilita controlli: media **4.46/5** (SD = 0.66)
- Thread response: controproducente! Rallentava la collaborazione real-time
- Importanza di poter cambiare i controlli **durante** l'interazione

### Design probes per controlli alternativi (Figure 6)
Tre mockup presentati ai partecipanti:
1. **Role options** (preferito): assegnare un ruolo a Koala (facilitatore, critico, brainstormer)
2. **Conversational control**: dare feedback in linguaggio naturale nella chat
3. **Persona selection**: scegliere una "personalita" con attributi comportamentali predefiniti

Preferenza: Role > Conversational > Persona. Ma tutti concordi che non si escludono a vicenda.

## Tassonomia dei controlli (Figure 7) -- Contributo principale

### Aspetti del comportamento da controllare

**WHEN (Quando contribuire)**
- **Triggers**: rispondere a ogni messaggio, solo se indirizzato, quando il gruppo ha bisogno di steering
- **Filters**: punteggio di valore, soglia di rilevanza, approvazione del moderatore
- **Rate**: immediatamente, dopo una durata, solo dopo che gli umani hanno iniziato, adeguarsi al ritmo del gruppo

**WHAT (Cosa contribuire)**
- **Content**: dominio-specifico (idee conservative vs. "crazy", creative vs. pragmatiche)
- **Style**: lunghezza, tono (formale vs. friendly), struttura (testo vs. liste puntate), livello di entusiasmo
- **Modality**: testo, emoji, codice, immagini

**WHERE (Dove contribuire)**
- **Location**: nel canale, in un thread, come DM, taggando il destinatario

### Modi per controllare il comportamento

**How to SPECIFY it**
- **Interaction**: in-conversation (linguaggio naturale) vs. pannello UI
- **Granularity**: controlli low-level diretti, specifiche basate su ruoli, specifiche basate su persona

**Who has ACCESS**
- **Permissions**: solo admin/leader, chiunque nel gruppo, consenso democratico, dipende dalla dimensione del gruppo
- **Visibility**: informare il gruppo quando i controlli cambiano o meno

**How to IMPLEMENT it**
- **Implementation**: system prompt engineering, end-user prompt engineering, logica algoritmica esterna all'LLM

## Discussione: Ripensare la proattivita

Il paper sfida i framework esistenti di mixed-initiative interaction:

1. **Fitts (1951)**: allocazione binaria umano/macchina -- troppo rigido
2. **Sheridan (1988) / Parasuraman (2000)**: continuum da full-human a full-machine -- ma statico
3. **Shneiderman (2022)**: due assi indipendenti (human control + automation) -- ma proattivita trattata come attributo fisso
4. **Muller & Weisz (2022)**: iniziativa cambia durante il workflow -- ma determinata dal workflow stesso

**Contributo di Houde et al.**: la proattivita non e ne binaria ne fissa. Gli **utenti** devono poterla controllare **dinamicamente** durante l'interazione. Questo democratizza il design degli agenti AI.

## Limiti

- Solo un tipo di attivita collaborativa (brainstorming di gruppo)
- Solo text-based (Slack) -- nessun contesto speech-based
- Partecipanti IBM con relazioni preesistenti (non generalizzabile a sconosciuti)
- Piccoli gruppi (3 persone)
- Non valutata la qualita delle idee, solo la quantita
- Solo contesto lavorativo occidentale

## Rilevanza per la tesi

**Molto alta**. Questo e il paper piu direttamente rilevante per il design delle interazioni di AIutami.

1. **La tassonomia WHEN/WHAT/WHERE + SPECIFY/ACCESS/IMPLEMENT** e direttamente applicabile ad AIutami:
   - **WHEN**: AIutami usa trigger-based moderation (soglie temporali, NO_PUSH_THRESHOLD) come meccanismo di filtraggio -- analogo al "value scoring" di Koala, ma implementato con logica esterna
   - **WHAT**: il moderatore di AIutami genera summary, domande, interventi di re-indirizzamento -- controllabili via prompt di sessione
   - **WHERE**: AIutami usa TTS (voce) come unico canale -- il "dove" e il flusso audio condiviso

2. **Reactive vs. Proactive**: AIutami e un ibrido:
   - **Proattivo**: il moderatore decide autonomamente quando intervenire (trigger-based)
   - **Controllato**: il sistema di turn-taking con reservation window impedisce che il moderatore "domini" (come faceva Koala proattivo)
   - La reservation window di 8 secondi e una forma di "rate control" dalla tassonomia

3. **Il problema della proattivita dirompente** e esattamente quello che AIutami affronta:
   - Koala proattivo era "too talkative, both in length of message and frequency" -- AIutami mitiga questo con soglie temporali e trigger condizionali
   - "give some extra time to answer, so you allow real people to answer first" -- AIutami fa esattamente questo con la reservation window

4. **Controllo dinamico**: i partecipanti volevano cambiare il comportamento di Koala durante la sessione. In AIutami, il moderatore si adatta tramite il summary evolutivo della sessione, ma non c'e un pannello di controllo utente. Possibile estensione.

5. **Permissions (WHO has access)**: in AIutami, il creatore della sessione configura i parametri iniziali, ma i partecipanti non possono modificare il comportamento del moderatore durante la sessione. La tassonomia suggerisce che questo potrebbe essere un gap.

6. **Gap speech-based**: Koala opera su Slack (text). Il paper cita esplicitamente come future work "collaborative activities situated in different collaborative applications beyond text-based group chats." AIutami e esattamente questo.

7. **Effetto soffocante**: il rischio di "production blocking" e reale anche per AIutami. Se il moderatore interviene troppo, gli utenti potrebbero limitarsi a seguire la sua direzione piuttosto che esprimere idee proprie.

### Confronto diretto con AIutami

| Aspetto | Koala (IBM) | AIutami |
|---------|------------|---------|
| Piattaforma | Slack (text) | WebRTC (speech) |
| LLM | Llama 2/3 locale | Azure OpenAI (cloud) |
| Ruolo AI | Partecipante/contributor | Moderatore di discussione |
| Proattivita | Self-scoring LLM (0-100) + soglia | Trigger-based (timer + condizioni) |
| Rate control | Soglia configurabile | Reservation window (8s) |
| Controllo utente | Pannello settings in-session | Configurazione iniziale sessione |
| Partecipanti | 3 umani + 1 AI | N umani + 1 AI moderatore |
| Contesto | Brainstorming aziendale | Multi-contesto (murder mystery, terapeutico, accademico) |
| Turn-taking | Implicito (text-based) | Esplicito (request + reservation + moderation-in-progress) |

## Collegamento con gli altri paper letti

- **Zheng et al. (2022)**: il concetto di "Ignorable" si ritrova qui -- Koala proattivo era troppo invasivo, confermando che i polyadic CA devono essere ignorabili. La tassonomia di Houde e un'operazionalizzazione concreta del boundary-awareness di Zheng.
- **Gu et al. (2022)**: Houde cita Gu [21] per il response generation e l'addressee detection. Il framework WHO/WHAT/WHOM di Gu si mappa sulla tassonomia WHEN/WHAT/WHERE di Houde.
- **Addlesee et al. (2024)**: Addlesee usa addressee detection (gaze + LLM) per decidere QUANDO rispondere. Houde esplora il design space completo di QUANDO + COSA + DOVE + chi controlla.

## Paper citati da approfondire

- **Muller et al. (2024)** [50]: "Group Brainstorming with an AI Agent: Creating and Selecting Ideas" -- analisi di come le idee evolvono tra umani e Koala
- **Liu et al. (2024)** [36]: "PeerGPT: Probing the Roles of LLM-based Peer Agents as Team Moderators and Participants in Children's Collaborative Learning" -- LLM come moderatore in gruppi di bambini
- **Seering et al. (2019)** [66]: "Beyond dyadic interactions" -- chatbot come community members (citato anche da Zheng)
- **Shneiderman (2022)** [69]: "Human-centered AI" -- framework per human control vs. automation
