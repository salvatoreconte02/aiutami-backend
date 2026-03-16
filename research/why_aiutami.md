# Le 4 tematiche della tesi -- spiegazione ad alto livello

## Il problema di fondo

Tu vuoi costruire un sistema dove **piu persone parlano a voce** e un **agente AI partecipa alla conversazione**. Questo e AIutami. Sembra semplice, ma in realta tocca 4 problemi distinti che la ricerca affronta separatamente. Sono le nostre 4 tematiche.

---

## 1. Architetture Speech-Based Chatbots

**La domanda**: come fai a far "parlare" un'AI?

Un LLM (tipo GPT) capisce e produce solo **testo**. Ma tu vuoi che capisca la **voce** e risponda **a voce**. Come colleghi questi due mondi?

Ci sono tre strade:

**Pipeline (STT-TTT-TTS)** -- quella che usa AIutami:
```
Voce umana → [ASR: trasforma voce in testo] → [LLM: ragiona sul testo] → [TTS: trasforma testo in voce] → Voce AI
```
Tre pezzi separati, ognuno fa il suo lavoro. E come avere un traduttore, un pensatore e un lettore in sequenza. Funziona bene, e maturo, ma ha due problemi: e **lento** (ogni pezzo aggiunge tempo) e **perde informazioni** (quando trasformi la voce in testo, perdi il tono, l'emozione, l'esitazione -- tutto cio che non sono parole).

**Half-cascade** -- un ibrido:
```
Voce umana → [Speech Encoder integrato nell'LLM] → [LLM ragiona] → [Speech Decoder integrato] → Voce AI
```
Invece di avere tre pezzi indipendenti, l'LLM "capisce" direttamente l'audio in ingresso e/o produce direttamente audio in uscita. Il ragionamento avviene ancora in testo internamente, ma l'integrazione e piu stretta. Esempio: Freeze-Omni, LLaMA-Omni.

**End-to-end** -- il piu ambizioso:
```
Voce umana → [Un unico modello] → Voce AI
```
Un singolo modello neurale prende audio e produce audio. Non c'e mai testo nel mezzo (o c'e solo come "pensiero interno"). Esempio: Moshi. Vantaggi: velocissimo (~200ms, come un umano), preserva tutto (emozione, prosodia). Svantaggi: ragiona peggio (il modello e meno intelligente della versione solo-testo), costa tantissimo da addestrare, e ancora poco affidabile.

**Perche ci interessa**: per la tesi, devi sapere che AIutami usa l'approccio piu "semplice" (pipeline), e devi saper spiegare perche, e conoscere le alternative. Il punto chiave: **tutti** questi approcci sono progettati per conversazioni a 2 (io e l'AI). Nessuno e stato pensato per gruppi.

---

## 2. Turn-Taking

**La domanda**: come decidete chi parla e quando?

Quando due persone parlano, si alternano in modo naturale. Non ci pensiamo, ma e un meccanismo sofisticatissimo. Gli umani hanno gap di circa 200ms tra un turno e l'altro -- cioe iniziano a preparare la risposta **prima** ancora che l'altro abbia finito.

Per un'AI, questo e un incubo. I problemi concreti:

- **Quando l'utente ha finito di parlare?** Se l'AI aspetta troppo, sembra lenta. Se interrompe troppo presto, e maleducata. Una pausa di 2 secondi puo significare "sto pensando" o "ho finito" -- dipende dal contesto.
- **Quando l'AI deve rispondere?** Subito? Dopo un po'? E se l'utente fa solo un "mhm" (backchannel), l'AI deve rispondere o no?

Gli approcci nella letteratura:

- **Soglie fisse** (quello che fanno Alexa/Siri): se l'utente sta zitto per 700ms, considero che ha finito. Semplice ma spesso sbagliato.
- **Modelli predittivi** (Skantze 2017, TurnGPT 2020, VAP 2022): modelli di machine learning che imparano dai dati quando un turno sta per finire, analizzando prosodia, contesto linguistico, storia della conversazione.
- **Turn-taking esplicito** (quello che fa AIutami): l'utente preme un bottone per chiedere il turno, il sistema glielo assegna, e quando finisce c'e una finestra di 8 secondi in cui il prossimo ha priorita. E come alzare la mano in classe.

**In multiparty il problema esplode**: con 2 persone, se uno smette di parlare, l'altro inizia. Con 5 persone, chi parla dopo? Chi decide? Come eviti che parlino tutti insieme? E se l'AI deve moderare, quando si inserisce senza essere invadente?

---

## 3. VAD e VAP

**La domanda**: come capisci se qualcuno sta parlando (o sta per parlare)?

Sono due cose correlate al turn-taking ma piu "a basso livello":

**VAD (Voice Activity Detection)** -- "chi sta parlando adesso?"
E il problema piu basilare: dato un flusso audio, distinguere quando c'e voce e quando c'e silenzio. Sembra banale ma non lo e: c'e rumore di fondo, respiri, colpi di tosse, "mmh" che non sono veri turni. Strumenti come Silero VAD sono molto accurati oggi, ma in multiparty devi anche capire **chi** sta parlando (speaker diarization), e li le cose si complicano parecchio.

**VAP (Voice Activity Projection)** -- "chi parlera tra poco?"
Questo e il salto concettuale: non solo rilevare chi parla **adesso**, ma **predire** chi parlera nei prossimi 2 secondi. Il modello VAP di Ekstedt e Skantze (2022) analizza l'audio e produce una distribuzione di probabilita su 256 possibili stati futuri della conversazione.

**Perche ci interessa**: la VAD e gia nel cuore di AIutami (il sistema deve sapere quando un utente parla per attivare la trascrizione). La VAP e interessante come possibile estensione -- immagina un moderatore AI che "sente" che qualcuno sta per iniziare a parlare e gli da spazio, oppure che anticipa la fine di un turno per preparare il suo intervento.

**Il problema multiparty**: VAP funziona per 2 persone (256 stati). Con N persone, gli stati diventano 2^(4N) -- con 4 persone sono gia oltre 65.000 stati. Non scala.

---

## 4. Multiparty Conversational AI

**La domanda**: come fa un'AI a partecipare a una conversazione di gruppo?

Questa e la tematica centrale della tesi, e in un certo senso le prime tre convergono qui. Se le architetture speech rispondono a "come fai parlare l'AI", il turn-taking a "come gestisci l'alternanza", e VAD/VAP a "come percepisci chi parla" -- il multiparty chiede: **come metti tutto insieme con piu di 2 persone?**

I problemi nuovi che emergono in multiparty:

**WHO -- chi ha parlato?** Con 2 persone e ovvio. Con 5, devi sapere chi ha detto cosa. In testo e facile (ogni messaggio ha un autore). In voce servono microfoni separati o speaker diarization (che funziona male, come mostra Addlesee 2020).

**WHOM -- a chi e rivolto?** "Puoi ripetere?" -- lo sta dicendo a me (l'AI) o al collega? Senza video/gaze, dal solo audio e quasi impossibile da capire (53% accuratezza). Con gaze si arriva all'85% (Addlesee 2024), ma solo con 2 umani.

**WHEN -- quando l'AI deve intervenire?** Questo e il problema di design piu importante. Houde (2025) ha dimostrato con Koala che se l'AI interviene troppo, soffoca la conversazione ("pedantic student who wouldn't create space for others"). Se interviene troppo poco, e inutile. Gli utenti vogliono poter controllare questo comportamento **durante** la sessione.

**WHAT -- cosa deve dire l'AI?** Dipende dal suo ruolo:
- Partecipante (Koala): contribuisce idee come gli altri
- Receptionist (ARI Robot): risponde a domande
- Co-facilitatore (Adikari): monitora in background e segnala al terapista umano
- **Moderatore (AIutami)**: gestisce attivamente il flusso della discussione

**Il gap fondamentale**: quasi tutta la ricerca su multiparty CA e **text-based**. Koala funziona su Slack, Adikari su chat, i survey di Gu e Zheng coprono solo testo. L'unico sistema multiparty **speech-based** e il robot ARI di Addlesee, ma gestisce solo 2 umani + 1 robot e ha bisogno di una videocamera per il gaze.

AIutami si trova nel quadrante praticamente vuoto: **multiparty + speech + AI moderatore + LLM + N partecipanti**. Questo e il contributo originale della tesi.

---

## Come si collegano

```
Architetture Speech ──► COME fa l'AI a capire/produrre voce
         │
         ▼
    Turn-Taking ──────► QUANDO ciascuno parla (chi ha il turno)
         │
         ▼
     VAD / VAP ────────► input percettivo per il turn-taking
         │                (chi parla ora, chi parlera tra poco)
         │
         ▼
  Multiparty CA ──────► TUTTO insieme con N persone
                         (chi parla, a chi, quando l'AI interviene,
                          cosa dice, come controllare il suo comportamento)
```

Le prime tre tematiche sono "ingredienti tecnici". La quarta e il "piatto finito" -- il problema completo che la tesi affronta. E il punto e che nessuno ha ancora cucinato questo piatto in versione speech-based con piu di 2 persone.
