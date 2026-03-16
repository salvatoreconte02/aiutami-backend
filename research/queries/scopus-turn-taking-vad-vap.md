# Query Scopus: Turn-Taking / VAD / VAP

## Query 1 -- Turn-taking in dialogue systems (broad)

```
TITLE-ABS-KEY(
  "turn-taking"
  AND ("spoken dialogue" OR "conversational AI" OR "dialogue system" OR "voice assistant")
)
AND PUBYEAR > 2018
```

## Query 2 -- Voice Activity Projection (specifico)

```
TITLE-ABS-KEY("voice activity projection")
OR
TITLE-ABS-KEY("voice activity prediction" AND "turn-taking")
```

## Query 3 -- Multi-party turn management

```
TITLE-ABS-KEY(
  ("multi-party" OR "multiparty")
  AND "turn-taking"
  AND ("dialogue" OR "conversation" OR "interaction")
)
```

## Query 4 -- ML-based endpointing

```
TITLE-ABS-KEY(
  ("end-of-turn" OR "endpointing" OR "turn-taking prediction")
  AND ("neural" OR "deep learning" OR "transformer" OR "LSTM")
)
```

## Query 5 -- Backchannel prediction

```
TITLE-ABS-KEY(
  "backchannel prediction"
  AND ("spoken" OR "dialogue" OR "conversation")
)
```

## Query 6 -- Ekstedt & Skantze (autori chiave)

```
AUTH(Ekstedt) AND AUTH(Skantze) AND TITLE-ABS-KEY("turn-taking" OR "voice activity")
```

## Paper chiave gia identificati (da citare direttamente)

| Autori | Anno | Titolo/Topic | Rilevanza |
|--------|------|-------------|-----------|
| Sacks, Schegloff, Jefferson | 1974 | A Simplest Systematics for Turn-Taking | Framework fondamentale CA |
| Gravano & Hirschberg | 2011 | Turn-Taking Cues in Task-Oriented Dialogue | Cues prosodiche/lessicali |
| Skantze | 2017 | Continuous Turn-Taking Model using LSTMs | Paradigma predizione continua |
| Ekstedt & Skantze | 2020 | TurnGPT | Transformer per turn prediction |
| Ekstedt & Skantze | 2022 | Voice Activity Projection | Paper fondamentale VAP |
| Bohus & Horvitz | 2009/2011 | Multi-party engagement models | Floor management multi-party |
| Raux & Eskenazi | 2009 | Finite-State Turn-Taking Model | Primo endpointing ML-based |
| Heldner & Edlund | 2010 | Pauses, gaps and overlaps | Timing transizioni turno |
