# Fix Audio Robotico WebRTC - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix robotic audio distortion in WebRTC forwarding by removing FFmpeg buffer padding from PCM extraction.

**Architecture:** The WebRTC consumer extracts PCM audio from PyAV frames for forwarding to other participants. The current extraction includes FFmpeg's internal buffer padding (64 extra bytes per frame), causing constant audio distortion. The fix truncates the extracted bytes to match the actual sample count.

**Tech Stack:** Python, aiortc, PyAV, Django Channels

---

## Task 1: Fix PCM Extraction in WebRTC Consumer

**Files:**
- Modify: `apps/webrtc/ws_consumer.py:327`

**Step 1: Understand the current code**

Current code (line 327):
```python
pcm = bytes(frame.planes[0])
```

This extracts ALL bytes from the PyAV buffer, including FFmpeg's 64-byte alignment padding.

**Step 2: Apply the fix**

Change line 327 to truncate PCM data to actual sample bytes:

```python
pcm = bytes(frame.planes[0])[:frame.samples * 2]  # s16 mono = 2 bytes/sample
```

**Step 3: Verify the change compiles**

Run: `docker compose run --rm web python -c "import apps.webrtc.ws_consumer"`
Expected: No import errors

**Step 4: Commit**

```bash
git add apps/webrtc/ws_consumer.py
git commit -m "fix(webrtc): truncate PCM to actual samples, removing FFmpeg padding

The extracted audio included 64 bytes of FFmpeg buffer padding per frame,
causing constant robotic distortion. Truncating to frame.samples * 2 bytes
ensures only real audio data is forwarded.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Remove Debug Logging for PCM Mismatch

**Files:**
- Modify: `apps/webrtc/ws_consumer.py:331-335`

**Step 1: Identify the debug log to remove**

Lines 331-335:
```python
expected_bytes = samples * 2  # s16 mono = 2 bytes per sample
if len(pcm) != expected_bytes:
    logger.warning(
        "[WebRTC] PCM size mismatch: got=%d expected=%d samples=%d rate=%d user=%s",
        len(pcm), expected_bytes, samples, sample_rate, self.user.id
    )
```

With the fix in Task 1, this warning will never trigger. Remove it.

**Step 2: Remove the debug logging**

Remove lines 330-335 (the `expected_bytes` calculation and the `if` block).

The code should now look like:

```python
try:
    pcm = bytes(frame.planes[0])[:frame.samples * 2]  # s16 mono = 2 bytes/sample
    samples = int(frame.samples)
    sample_rate = int(frame.sample_rate or 48000)
    self._hub.forward_pcm_from_speaker(
        from_user_id=self.user.id,
        pcm=pcm,
        samples=samples,
        sample_rate=sample_rate,
    )
except Exception:
```

**Step 3: Verify the change compiles**

Run: `docker compose run --rm web python -c "import apps.webrtc.ws_consumer"`
Expected: No import errors

**Step 4: Commit**

```bash
git add apps/webrtc/ws_consumer.py
git commit -m "chore(webrtc): remove PCM mismatch debug logging

No longer needed after fixing the padding issue.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Manual Integration Test

**Files:**
- None (manual testing)

**Step 1: Start the services**

Run: `make up-detached`
Expected: All services start successfully

**Step 2: Test audio forwarding**

1. Open the app in two different browser windows/devices
2. Join the same session with both participants
3. Have one participant speak
4. Verify the other participant hears clear audio (no robotic distortion)

**Step 3: Verify ASR still works**

1. During the speaking test, check that transcription appears correctly
2. Verify no errors in logs related to ASR

Run: `make logs | grep -i "asr\|error"`
Expected: No ASR errors, transcription working

**Step 4: Check logs for issues**

Run: `docker compose logs web 2>&1 | grep -i "webrtc\|pcm\|mismatch"`
Expected: No "PCM size mismatch" warnings

**Step 5: Document test results**

Note any issues found. If the fix works, proceed to Task 4.

---

## Task 4: Optional - Keep or Remove Buffer Underrun Log

**Files:**
- Modify: `apps/webrtc/audio_tracks.py:140-143` (optional)

The design document suggests the "Buffer underrun" log in `audio_tracks.py` can be kept as it may be useful for debugging intermittent audio issues. This task is optional.

**Decision point:**
- If buffer underrun logs are excessive during testing, consider reducing log level to DEBUG
- If they're rare, keep as WARNING for production monitoring

**Step 1: Review underrun frequency during testing**

Run: `docker compose logs web 2>&1 | grep "Buffer underrun"`
If: Many warnings -> consider changing to debug level
If: Few or none -> keep as is

**Step 2: (Optional) Change to debug level if needed**

If excessive warnings, change line 140 from:
```python
logger.warning(
```
to:
```python
logger.debug(
```

**Step 3: (Optional) Commit if changed**

```bash
git add apps/webrtc/audio_tracks.py
git commit -m "chore(audio): reduce buffer underrun log to debug level

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Fix PCM extraction (core fix) | `ws_consumer.py:327` |
| 2 | Remove debug logging | `ws_consumer.py:331-335` |
| 3 | Manual integration test | None |
| 4 | (Optional) Adjust underrun log level | `audio_tracks.py:140` |

**Expected outcome:** Audio forwarded via WebRTC no longer sounds robotic because FFmpeg's buffer padding is excluded from the PCM data.
