# AIutami – Frontend
### Real-Time AI-Moderated Voice Discussion Platform

Advanced User Interfaces – Group 8  
Politecnico di Milano  
Academic Year 2025/2026  

---

# Overview

This repository contains the **React frontend** of AIutami, a real-time AI-moderated voice discussion platform.

AIutami is not a traditional conferencing tool. It is a structured conversational system where:

- Only one participant can speak at a time
- Turn-taking is explicitly regulated
- Participation levels are monitored
- AI interventions are context-aware
- Sessions follow a strict lifecycle
- Structured conclusion and voting are supported (Murder Mystery context)

The frontend acts as a **deterministic interaction layer** that reflects backend moderation decisions in real time.

It integrates with:

- WebRTC audio streaming
- WebSocket-based state synchronization
- Django backend (ASGI + Channels)
- Redis ephemeral state
- PostgreSQL persistent storage
- Azure Speech-to-Text
- Azure OpenAI
- Azure Text-to-Speech

The frontend never decides moderation logic. It reacts to backend events.

---

# System Architecture (Frontend Perspective)

The frontend communicates with the backend through three independent channels:

## 1. REST API

Used for:

- Authentication (signup / login)
- Session creation
- Join by invitation token
- Session history retrieval
- Vote submission
- PDF report download

---

## 2. WebSocket Channels

Three separate WebSocket endpoints are used:

### `sessions`

Handles:
- Session state transitions (LOBBY → ACTIVE → CONCLUSION → CLOSED)
- Participant join/leave
- Timer events
- Ready-to-conclude events
- Session termination

### `turns`

Handles:
- Human turn start/end
- AI turn start/end
- Reservation events
- AI introduction
- AI interventions
- Moderation lock states

### `webrtc`

Handles:
- SDP negotiation
- ICE candidate exchange
- Media coordination

This separation guarantees clear domain boundaries and deterministic synchronization.

---

## 3. WebRTC Audio Model

All audio flows through the server (server-side forwarding).

Frontend responsibilities:

- Capture microphone input
- Enable/disable local track (push-to-talk)
- Send audio to backend
- Play remote participant audio
- Play AI moderator voice
- Avoid echo (speaker excluded server-side)

Audio normalization (48kHz mono PCM) occurs server-side.

---

# Session Lifecycle

Sessions move through four strict states:

1. LOBBY  
2. ACTIVE  
3. CONCLUSION  
4. CLOSED  

The frontend never transitions states autonomously.

---

## LOBBY

- Invitation link visible
- Real-time participant counter
- Start button visible only to host
- Backend validates participant constraints

### Participant Constraints

- Backend enforces `max_size >= 2`
- In the **Murder Mystery** context, participants must be exactly 3 (`min_size = max_size = 3`)
- Other contexts are configurable

The frontend reflects backend validation only.

---

## ACTIVE

Upon entering ACTIVE:

- AI Introduction delivered
- Turn state = `AI_INTRODUCING`
- Push-to-talk disabled
- After introduction → state moves to `IDLE`

---

# Turn State Machine (Frontend View)

The frontend reacts to backend turn states:

- `IDLE`
- `HUMAN_SPEAKING`
- `AI_SPEAKING`
- `AI_INTRODUCING`

Push-to-talk is enabled only when:

- Session state = ACTIVE
- Turn state = IDLE
- No moderation lock
- AI is not speaking

---

# Speaking Flow

## Human Turn

1. User presses push-to-talk
2. Backend validates request
3. `turns` event broadcasts new speaker
4. ASR gating activates server-side
5. User speaks
6. User ends turn
7. Moderation window begins

During moderation window:

- Turn requests blocked
- Trigger engine evaluated
- Static messages may be delivered
- AI may speak

Frontend waits for:

- `turns.ai_started`
- `turns.ai_ended`

Then returns to IDLE.

---

# Reservation Mechanism

If another participant is speaking:

- User presses “Reserve turn”
- Backend assigns 8-second exclusive window (stored in Redis)
- After current turn:
  - Only reserved user can speak
  - Countdown displayed
  - If expired → return to IDLE

Frontend reflects reservation state.

---

# AI Moderation Pipeline (Frontend-Relevant)

After each human turn:

1. Transcript finalized
2. Moderation lock activated
3. Trigger engine evaluated
4. LLM called (if required)
5. Static messages delivered
6. Optional AI voice intervention executed
7. Lock released

Frontend behavior:

- Display AI speaking indicator
- Disable interaction during AI turn
- Reflect static notifications
- Resume after `ai_ended`

---

# Trigger System – Complete Frontend Handling

Triggers are divided into:

- Turn-based
- Time-based
- Event-based

The frontend must handle them explicitly.

---

## Turn-Based Trigger

### Periodic Summary (Every 6 Human Turns)

- Forced summary mode
- AI recap delivered via voice
- Incremental summary updated

Frontend:
- Disable interaction during AI speaking
- Show AI indicator
- Resume afterward

---

## Time-Based Triggers

Evaluated every 5 seconds when session is IDLE.

### `TIMER_25`

- Fired at 25 minutes
- Text-only notification

Frontend:
- Display "5 minutes remaining"
- Start visible 5-minute countdown
- No state transition occurs

---

### `TIMER_30`

- Fired at 30 minutes
- AI announces end
- Session transitions to CONCLUSION

Frontend:
- Wait for `sessions.state_changed`
- Switch layout to CONCLUSION
- Disable standard speaking

---

### `NO_PUSH`

- Triggered after prolonged silence (~20–30 seconds)
- AI prompts discussion restart

Frontend:
- Optionally show subtle silence indicator
- Wait for AI speaking events
- Do not change turn permissions

---

### Inactive User Escalation

#### `INACTIVE_USER_TEXT` (5 minutes)

- Private notification to inactive user

Frontend:
- Display private toast only to targeted user
- Do not expose inactivity publicly

#### `INACTIVE_USER_VOICE` (10 minutes)

- AI addresses user by name

Frontend:
- Render as normal AI speaking turn
- Disable interaction during speech

Backend limits voice solicitations per user.

---

## Event-Based Trigger

### Ready to Conclude (Murder Mystery)

When participant presses “Ready to conclude”:

- Backend sends contextual feedback
- When all ready → transition to CONCLUSION
- AI summary delivered

Frontend:
- Reflect ready indicators
- Wait for state transition event

---

# Conclusion Phase

In CONCLUSION:

- Standard speaking disabled
- AI delivers final summary
- Voting enabled only after `ai_ended`

---

# Voting (Murder Mystery Context)

- Exactly 3 participants
- Each selects suspect
- Votes submitted via REST
- After all votes:
  - Session transitions to CLOSED
  - Final report generated

Frontend:
- Display voting UI
- Show results
- Provide PDF download

---

# Incremental Summarization

Backend maintains:

- `SessionSummary.summary_text`
- `last_segment_seq`

Only new transcript segments are sent to LLM.

Frontend displays summaries but does not manage them.

---

# Environment Configuration (.env.local)

Create a file in the project root:

.env.local


Required variables:



VITE_API_BASE=http://<BACKEND_IP>:8000/api
VITE_WS_BASE=ws://<BACKEND_IP>:8000/ws


Examples:

### Local Development



VITE_API_BASE=http://127.0.0.1:8000/api

VITE_WS_BASE=ws://127.0.0.1:8000/ws


### VM Deployment



VITE_API_BASE=http://4.210.242.217:8000/api

VITE_WS_BASE=ws://4.210.242.217:8000/ws


Notes:

- `.env.local` is not committed to version control
- Restart dev server after editing
- For HTTPS deployments use `wss://`
- No backend URLs are hardcoded

---

# Installation



npm install
npm run dev


---

# Limitations

- Single-server backend architecture
- Murder Mystery strictly requires 3 participants
- Optimized for small-group discussions
- Not horizontally scaled
- Dependent on Azure latency
- Optimized for desktop browsers

---

# Future Improvements

- Participation analytics dashboard
- Speaking-time visualization
- Multi-context UI theming
- Accessibility enhancements
- Horizontal scaling
- Multi-language support

---

# Authors

Salvatore Pio Conte – Backend Architecture  
Simone Cosenza – Frontend Development  
Sara Imparato – Frontend Development  

Politecnico di Milano  
Advanced User Interfaces  

---

# Final Note

AIutami is a research-oriented AI moderation system.

The frontend is a deterministic interaction layer tightly coupled to:

- A turn state machine
- A trigger engine
- An incremental summarization pipeline
- A structured session lifecycle

Its goal is to enable fair, focused, and procedurally guided group discussions in real-time voice environments.