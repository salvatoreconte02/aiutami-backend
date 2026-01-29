# Fix Audio Robotico WebRTC

**Data**: 2026-01-27
**Stato**: In revisione
**Autore**: Claude + Salvatore

---

## Problema

L'audio inoltrato via WebRTC agli altri partecipanti suona "robotico" fin dall'inizio della conversazione. L'ASR (speech-to-text) funziona correttamente, quindi il problema è specifico del forwarding audio.

## Causa Root

**Diagnosi confermata dai log:**
```
[WebRTC] PCM size mismatch: got=1984 expected=1920 samples=960 rate=48000
```

Il codice attuale estrae i dati audio così:
```python
pcm = bytes(frame.planes[0])
```

Questo restituisce **tutti i bytes del buffer PyAV**, incluso il **padding di allineamento** che FFmpeg aggiunge internamente.

| Componente | Bytes |
|------------|-------|
| Audio reale (960 samples × 2 bytes) | 1920 |
| Padding FFmpeg | 64 |
| **Totale estratto** | **1984** |

Questi 64 bytes extra per ogni frame (ogni 20ms) vengono interpretati come audio valido ma contengono dati non significativi, creando distorsione costante.

---

## Soluzione

### Approccio scelto: Troncare al numero corretto di bytes

Invece di prendere tutto il buffer, prendiamo solo i bytes che corrispondono ai samples reali:

```python
# Prima (sbagliato)
pcm = bytes(frame.planes[0])

# Dopo (corretto)
pcm = bytes(frame.planes[0])[:frame.samples * 2]  # s16 mono = 2 bytes/sample
```

### Perché questa soluzione

1. **Minima modifica** - una sola riga cambiata
2. **Nessun overhead** - lo slicing in Python è O(1) per bytes
3. **Robusta** - funziona indipendentemente da quanto padding aggiunge FFmpeg

### Alternative considerate

| Alternativa | Pro | Contro |
|-------------|-----|--------|
| `frame.to_ndarray().tobytes()` | API più "pulita" | Crea copia extra, overhead CPU |
| Configurare FFmpeg senza padding | Elimina il problema alla fonte | Complesso, potrebbe rompere altro |

---

## Modifiche da fare

### File: `apps/webrtc/ws_consumer.py`

**Linea ~327** - Nel metodo `reader()` dentro `on_track`:

```python
# PRIMA
pcm = bytes(frame.planes[0])

# DOPO
pcm = bytes(frame.planes[0])[:frame.samples * 2]  # s16 mono
```

### Rimuovere log di debug

Dopo aver verificato che funziona, rimuovere i log di warning aggiunti per il debug:
- `ws_consumer.py`: rimuovere il log "PCM size mismatch"
- `audio_tracks.py`: rimuovere il log "Buffer underrun" (opzionale, può essere utile tenerlo)

---

## Test di verifica

1. Avviare una sessione con 2+ partecipanti
2. Far parlare un partecipante
3. Verificare che:
   - L'audio arriva agli altri partecipanti **senza** effetto robotico
   - L'ASR continua a funzionare correttamente
   - Non ci sono più log "PCM size mismatch"

---

## Note aggiuntive

Il log `Buffer underrun: had=0` indica che a volte il buffer è vuoto quando serve. Questo è un problema secondario che può causare micro-interruzioni, ma il **problema principale** dell'audio robotico costante è il padding.

Se dopo il fix rimangono problemi di qualità audio intermittenti, potrebbe essere necessario:
1. Aggiungere un piccolo buffer iniziale (pre-buffering)
2. Implementare un jitter buffer più sofisticato

Ma questi sono miglioramenti futuri - prima risolviamo il problema del padding.
