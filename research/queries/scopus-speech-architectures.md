# Query Scopus: Architetture Speech Dialogue

## Query 1 -- Architetture speech dialogue (broad)

```
TITLE-ABS-KEY(
  ("spoken dialogue model" OR "speech dialogue system" OR
   "spoken language model" OR "speech language model")
  AND
  ("cascaded" OR "modular pipeline" OR "ASR" OR "end-to-end" OR
   "speech-to-speech" OR "neural audio codec" OR "speech token*" OR "full-duplex")
)
AND PUBYEAR > 2022
```

## Query 2 -- End-to-end speech (escludi translation)

```
TITLE-ABS-KEY(
  ("speech-to-speech" OR "end-to-end spoken" OR "spoken dialogue model")
  AND
  ("language model" OR "transformer" OR "neural")
  AND NOT "translation"
)
AND PUBYEAR > 2022
```

## Query 3 -- Cascaded pipeline

```
TITLE-ABS-KEY(
  ("speech recognition" OR "ASR")
  AND ("language model" OR "LLM")
  AND ("text-to-speech" OR "TTS")
  AND ("pipeline" OR "cascaded" OR "modular")
)
AND PUBYEAR > 2022
```

## Survey gia identificate (da citare direttamente, non serve Scopus)

1. **WavChat** -- Ji et al., Nov 2024, arXiv:2411.13577 (60pp, la piu completa)
2. **On The Landscape of Spoken Language Models** -- Apr 2025, arXiv:2504.08528, TMLR
3. **Recent Advances in Speech Language Models** -- Oct 2024, arXiv:2410.03751, ACL 2025
4. **From Turn-Taking to Synchronous Dialogue** -- Sep 2025, arXiv:2509.14515
5. **ESPnet-SDS** -- NAACL 2025, arXiv:2503.08533

## Sistemi chiave da citare

| Sistema | Tipo | Anno | Ref |
|---------|------|------|-----|
| X-Talk | Cascaded ottimizzato | 2025 | arXiv:2512.18706 |
| Moshi | End-to-end, full-duplex | 2024 | arXiv:2410.00037 |
| GPT-4o | End-to-end, proprietario | 2024 | OpenAI System Card |
| LLaMA-Omni | Half-cascade | 2024 | ICLR 2025, arXiv:2409.06666 |
| Freeze-Omni | Half-cascade (LLM frozen) | 2024 | arXiv:2411.00774 |
| SALMONN | Half-cascade (speech encoder) | 2023 | ICLR 2024, arXiv:2310.13289 |
| SpeechGPT | Half-cascade (chain-of-modality) | 2023 | arXiv:2305.11000 |
| AudioPaLM | Half-cascade (joint vocab) | 2023 | arXiv:2306.12925 |
