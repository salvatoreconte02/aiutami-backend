# Chapter 7 — Solution: Implementation — Design Document

**Date:** 2026-02-05
**Status:** Approved
**Language:** English (matching the LaTeX document)

---

## Chapter Structure

1. **Deployment Architecture** (diagram + short paragraph)
2. **Software Architecture**
   - 2.1 Functional Architecture (6 modules + diagram)
   - 2.2 Implementation Architecture (5 patterns, prose style, technologies integrated)
3. **AI Moderation System**
   - 3.1 Moderation Pipeline Overview
   - 3.2 Trigger System
   - 3.3 LLM Integration & Prompt Design
   - 3.4 Intervention Control
4. **Data Flow**
   - 4.1 Session Lifecycle (diagram + caption only)
   - 4.2 Speaking Turn Flow (diagram + description)
   - 4.3 Audio Flow (diagram + caption only)

---

## Section 1: Deployment Architecture

AIutami is deployed on a single Azure Virtual Machine hosting all services through Docker Compose. The deployment architecture comprises three containers:

- **web** (aiutami-web): Django application server served by Daphne (ASGI server), exposing port 8000/TCP for HTTP and WebSocket traffic, and ports 10000-10050/UDP for WebRTC media traffic (RTP/RTCP via aiortc)
- **db** (aiutami-db): PostgreSQL 16, port 5432, with persistent data stored on a Docker volume
- **redis** (aiutami-redis): Redis 7, port 6379, used as cache and message broker for Django Channels

The web container depends on both db and redis (sequential startup). In addition to local services, the system communicates with three external Azure services over HTTPS:
- Azure Speech-to-Text (speech transcription)
- Azure OpenAI (moderation decisions)
- Azure Speech TTS (moderator voice synthesis)

**Diagram instructions:** A deployment diagram showing: on the left, clients (browsers); in the center, the Azure VM containing the 3 Docker containers (web, db, redis) with their exposed ports; on the right, the 3 external Azure services. Arrows: client <-> web (HTTP/WS on 8000, WebRTC UDP 10000-10050), web -> Azure services (HTTPS), web <-> db (TCP 5432), web <-> redis (TCP 6379).

---

## Section 2: Software Architecture

### 2.1 Functional Architecture

The system is decomposed into six functional modules, each responsible for a distinct concern:

- **Session Management** — Controls the session lifecycle through four states (Lobby, Active, Conclusion, Closed), manages participants, invitations, and voting.
- **Turn Management** — Coordinates speaking turns through a state machine with four states (Idle, Human Speaking, AI Speaking, AI Introducing). Enforces that only one participant speaks at a time and manages a priority reservation window for the next speaker.
- **Audio Transport** — Handles WebRTC peer connections and server-side audio forwarding. The server receives audio from the current speaker and forwards it to all other participants without mixing. The speaker is excluded from their own stream to prevent echo.
- **Speech Recognition** — Performs real-time speech-to-text transcription of the current speaker's audio using Azure Speech-to-Text. Transcription is gated by the turn state: it only runs when the user is the active speaker.
- **AI Moderation** — Evaluates whether the AI moderator should intervene after each human turn. Uses a trigger system and LLM calls to decide the content and timing of interventions.
- **Text-to-Speech** — Converts AI moderator text responses into audio using Azure Speech TTS, which is then injected into the audio stream via the Audio Transport module.

The modules interact in a pipeline: Turn Management acts as the central coordinator. When a speaker's turn ends, it triggers Speech Recognition to finalize the transcript, passes it to AI Moderation for evaluation, and if the AI decides to intervene, Text-to-Speech generates the audio delivered through Audio Transport.

**Module-to-code mapping:**

| Functional Module | Django App |
|---|---|
| Session Management | `apps/sessions/` |
| Turn Management | `apps/turns/` |
| Audio Transport | `apps/webrtc/` |
| Speech Recognition | `apps/asr/` |
| AI Moderation | `apps/moderation/` |
| Text-to-Speech | `apps/tts/` |

**Diagram instructions:** A block diagram with the 6 modules. Session Management at the top (orchestrates lifecycle). Below it, Turn Management in the center connected to all others. Audio Transport on the left, connected bidirectionally to Turn Management. Speech Recognition between Audio Transport and AI Moderation (receives audio, outputs text). AI Moderation connected to Text-to-Speech. Text-to-Speech connected back to Audio Transport (injects AI voice). External services (Azure) shown as cloud icons connected to Speech Recognition, AI Moderation, and Text-to-Speech.

### 2.2 Implementation Architecture

The implementation follows a **service-oriented design**, where business logic is encapsulated in dedicated service classes separate from the communication layer. `TurnManager` manages the turn state machine, `ModerationOrchestrator` coordinates moderation decisions, and `ASRStreamManager` controls speech recognition streams. WebSocket consumers act as coordinators: they receive client messages, delegate to services, and broadcast results. This separation keeps business rules testable independently from the transport layer.

A **dual storage strategy** assigns each data category to the backend best suited for it. PostgreSQL stores persistent data that must survive restarts: sessions, participants, invitations, votes, and transcripts. Redis stores high-frequency ephemeral state that requires low-latency access: turn state, moderation state, and ASR transcript cache. This split avoids the overhead of database transactions for state that changes multiple times per second during active sessions.

WebSocket consumers are **asynchronous**, built on Django Channels, since they must handle concurrent connections and I/O-bound operations like network broadcasting. However, the service layer remains **synchronous** for simplicity and easier reasoning about state. The bridge between the two layers is Django's `database_sync_to_async` wrapper, which allows synchronous service calls to run safely within the asynchronous consumer context.

Every state change is propagated to all connected clients through an **event-driven broadcasting** mechanism. When a participant joins, requests a turn, or when the AI moderator intervenes, the corresponding consumer broadcasts an event to the session's channel group. Clients subscribe to three WebSocket endpoints — sessions, turns, and WebRTC — each carrying its own category of events. This decouples the sender from the receivers and ensures all clients maintain a consistent view of the session state.

Finally, rather than establishing direct peer-to-peer connections between participants, all audio flows through the server following a **server-side forwarding** pattern. The server receives PCM audio frames from the current speaker and forwards them to every other participant's outbound track, explicitly excluding the speaker from their own stream to prevent echo. This server-centric approach enables two key features: ASR gating, where the server feeds only the current speaker's audio to the transcription service, and AI audio injection, where the moderator's synthesized voice is delivered through a virtual audio track to all peers.

---

## Section 3: AI Moderation System

### 3.1 Moderation Pipeline Overview

The AI moderation system evaluates whether the moderator should intervene after each human speaking turn. The pipeline executes during a moderation window in which no participant can take the floor, ensuring the AI's evaluation is based on a complete turn.

The pipeline follows a fixed sequence. First, the `ModerationOrchestrator` loads the current moderation state from Redis, which includes a running summary of the discussion, the number of turns per participant, and timestamps of previous AI interventions. Second, it evaluates the trigger engine to determine if any rule-based condition requires a hard action (such as a forced summary) or if any static messages need to be delivered. Third, it calls the LLM via `ModerationService` to analyze the last speaker's transcript against the discussion summary. The LLM returns a structured JSON response containing an updated summary, a boolean indicating whether the AI should speak, a proposed message, a reason classification, and an intervention score. Fourth, the backend applies its own filtering rules on top of the LLM's proposal — checking cooldown timers, score thresholds, and session phase — before producing a final `FullModerationDecision`. This decision contains the list of static messages to deliver, whether the AI should speak, the AI message content, and whether the session should transition to the conclusion phase.

**Diagram instructions:** A vertical sequence diagram showing the pipeline: Human turn ends -> Load ModerationState (Redis) -> Evaluate Triggers -> Call LLM (Azure OpenAI) -> Backend filters (cooldown, score, phase) -> FullModerationDecision -> Execute (static messages + optional AI voice via TTS).

### 3.2 Trigger System

The moderation system uses a trigger engine that evaluates rule-based conditions independently from the LLM. Triggers are divided into three categories based on how they are activated.

**Turn-based triggers** are evaluated at the end of each human speaking turn. The primary trigger in this category is the periodic summary: after every four human turns, the system forces a summary intervention where the AI recaps the discussion so far and optionally corrects participation imbalances such as monopolization or exclusion of quiet participants.

**Time-based triggers** are evaluated by a background loop that runs every five seconds, independently from speaking turns. These include: a silence trigger that fires when no activity is detected for a configurable period, prompting participants to resume the discussion; an inactive user trigger with two escalation levels — a private text notification after five minutes of individual silence, followed by a public voice solicitation after ten minutes, with a maximum of two voice solicitations per user to avoid being intrusive; and session duration milestones at twenty-five and thirty minutes. The twenty-five minute mark delivers a text-only notification to the frontend, which activates a visual countdown timer. The thirty-minute mark triggers a voice announcement and automatically transitions the session to the conclusion phase. Importantly, time-based triggers are suppressed while someone is speaking — they are re-evaluated at the next cycle when the session is idle.

**Event-based triggers** respond to participant actions. When a participant presses the "ready to conclude" button, the system generates a contextual message that varies based on how many participants are ready: a general notification for early votes, an urgency message when only one vote is missing, and a transition announcement when all participants have voted.

Each trigger produces either a static message (delivered as text or voice) or a hard action that overrides the normal LLM evaluation path.

### 3.3 LLM Integration & Prompt Design

The system integrates with Azure OpenAI through a structured request-response protocol. Each LLM call sends a system prompt defining the moderator's role and a user message containing a JSON object with the current discussion state. The LLM responds with a JSON object following a strict contract, which the backend parses and validates.

The LLM operates in three modes, each with a dedicated system prompt. In **normal mode**, the LLM acts as a neutral facilitator. It receives the discussion summary, the last speaker's transcript, and the turn count per participant. It evaluates whether an intervention is needed based on five criteria: monopolization of the conversation, exclusion of quiet participants, off-topic drift, interpersonal conflict, or a direct request for help from a participant. It returns an intervention score between 0 and 1, and only proposes to speak when the score reaches 0.7 or above. In **forced summary mode**, the LLM generates a periodic recap of the discussion. It combines two responsibilities: detecting and gently correcting participation imbalances, and summarizing the key points and clues that have emerged so far. In **forced conclusion mode**, the LLM produces a closing message that summarizes the entire discussion, provides voting instructions, and thanks the participants.

A central mechanism across all modes is the **running summary**. The LLM receives the current summary and the latest transcript, and returns an updated summary that incorporates the new information. This summary persists in Redis across turns, allowing the LLM to maintain context of the full discussion without receiving the entire transcript history in each call — keeping token usage bounded regardless of session length.

The system includes a fallback mechanism: if the Azure API call fails or returns unparsable output, a local fallback generates a safe default response — no intervention in normal mode, a basic recap in summary mode, and a template closing message in conclusion mode.

### 3.4 Intervention Control

Beyond the LLM's own judgment, the backend enforces several control mechanisms that regulate when and how the AI moderator can speak.

The primary mechanism is a **cooldown timer**: after each normal intervention, the system blocks further normal interventions for sixty seconds. This prevents the AI from dominating the conversation with frequent remarks. The cooldown can be bypassed only when the LLM classifies the situation as a conflict or a direct user request — cases where delayed intervention could be harmful. Forced modes (summary and conclusion) are exempt from the cooldown entirely, as they serve structural purposes that must execute regardless of recent activity.

A **moderation lock** ensures mutual exclusion between the moderation pipeline and speaking turns. When a human turn ends and the pipeline begins evaluating, a `moderation_in_progress` flag is set. While this flag is active, no participant can request a new speaking turn. This guarantees that the AI's evaluation is not disrupted by concurrent speech and that the subsequent voice intervention, if any, is delivered without interruption. The flag is cleared only after all static messages and the optional AI voice message have been fully delivered.

The system also manages an **intro message** at session start. When a session transitions to the active state, a pending flag is set in Redis. Before the first human turn is allowed, the AI moderator delivers a welcome message that greets participants by name, explains the interaction mechanics (how to speak, how to reserve, how to conclude), and sets the session duration. This message uses a template populated with participant names retrieved from the database.

Finally, a **pending message queue** handles situations where the AI needs to speak but the floor is occupied. If a time-based trigger fires while someone is speaking, the message is enqueued in a Redis FIFO queue. When the turn returns to idle, the queue is flushed and all pending messages are delivered in order. The queue includes deduplication to avoid repeating identical messages and blocks new entries once a conclusion-triggering message has been enqueued.

---

## Section 4: Data Flow

### 4.1 Session Lifecycle (diagram + caption only)

**Diagram instructions:** A horizontal state diagram with four boxes: Lobby -> Active -> Conclusion -> Closed. Below each transition arrow, annotate the trigger: "all participants joined, host starts" for Lobby->Active, "timer expires OR all ready to conclude" for Active->Conclusion, "all votes collected" for Conclusion->Closed. Above Active, a note: "AI intro message, turn-taking enabled, moderation active". Above Conclusion, a note: "AI delivers final summary, participants vote".

**Caption:** A session progresses through four states in a fixed sequence. It begins in Lobby, where participants join via invitation tokens. The host starts the session when all participants are present, transitioning to Active. During the Active phase, participants take turns speaking, and the AI moderation pipeline evaluates each turn. The session transitions to Conclusion either when the thirty-minute timer expires or when all participants indicate readiness. In this phase, the AI delivers a closing summary and participants cast their votes. Once all votes are collected, the session moves to Closed and a final report is generated.

### 4.2 Speaking Turn Flow (diagram + description)

This is the central data flow of the system, describing what happens from the moment a participant requests to speak until the floor is open for the next speaker.

The flow begins when a participant sends a turn request through the turns WebSocket. `TurnManager` validates that the session is active, no one else is speaking, and moderation is not in progress. If valid, the turn state transitions to Human Speaking, and a `HUMAN_STARTED` event is broadcast to all clients. The `WebRTCConsumer` receives this event, updates its local shadow state, sets the speaker in the `SessionAudioHub`, and activates ASR gating — starting the transcription stream for this user only.

While the participant speaks, audio frames arrive through the WebRTC connection. Each frame is resampled to 48kHz mono 16-bit PCM and processed in two parallel paths: it is forwarded by the audio hub to all other participants' outbound tracks (excluding the speaker), and it is fed to the `ASRStreamWorker`, which sends audio chunks to Azure Speech-to-Text and caches the final transcript segments in Redis.

When the participant ends their turn, the moderation pipeline takes over. The consumer first waits briefly (up to 1.2 seconds) for the ASR cache to stabilize — polling until two consecutive reads return the same result — then collects the final transcript. If the ASR cache is empty, it falls back to the transcript sent by the frontend. The `moderation_in_progress` flag is set, blocking new turn requests. The `ModerationOrchestrator` evaluates triggers and calls the LLM. Static messages are delivered first (text-only or with TTS). If the LLM decides the AI should speak, a full AI turn is executed: `TurnManager` transitions to AI Speaking, the TTS service synthesizes the message into audio chunks streamed to all participants through the audio hub, and the turn returns to Idle. Finally, if a participant had reserved the floor during the previous turn, an eight-second priority window opens for them.

**Diagram instructions:** A vertical sequence diagram with four columns: Client, TurnsConsumer, WebRTCConsumer, Azure Services. Show: (1) client sends request_speak -> TurnsConsumer validates -> broadcast HUMAN_STARTED, (2) WebRTCConsumer receives event -> starts ASR -> hub.set_speaker, (3) audio frames flow: client -> WebRTCConsumer -> hub forwards to other clients + ASR ingest -> Azure STT -> cache in Redis, (4) client sends end_speak -> TurnsConsumer collects ASR from cache -> ModerationOrchestrator -> Azure OpenAI -> decision, (5) if AI speaks: ai_start -> TTS -> Azure TTS -> audio chunks -> hub -> all clients -> ai_end, (6) reservation window opens.

### 4.3 Audio Flow (diagram + caption only)

**Diagram instructions:** A diagram showing the audio path through the system. On the left, Speaker's browser with a microphone icon. Arrow labeled "WebRTC (opus)" to the center box: Server (WebRTCConsumer). Inside the server box, two outgoing paths: one arrow down labeled "PCM 48kHz" to ASR StreamWorker -> Azure Speech-to-Text, and one arrow right labeled "PCM forwarding" to AudioHub. From AudioHub, multiple arrows labeled "WebRTC (opus)" going right to Listener browsers (with speaker icons). A separate path below: Azure TTS -> "PCM 48kHz" -> AI Virtual Track -> AudioHub -> all listeners. A crossed-out arrow from AudioHub back to the Speaker's browser, labeled "excluded (no echo)".

**Caption:** All audio flows through the server rather than directly between participants. The current speaker's audio is received via WebRTC, resampled to 48kHz mono 16-bit PCM, and processed along two paths: it is forwarded by the audio hub to every other participant's outbound track (the speaker is excluded to prevent echo), and simultaneously fed to the ASR stream for real-time transcription. When the AI moderator speaks, its synthesized voice follows the reverse path: Azure TTS generates PCM audio that is injected into a virtual track in the audio hub and delivered to all participants.

---

## Diagrams Checklist

The following diagrams need to be created externally (Draw.io, Figma, or similar):

- [ ] Deployment Architecture diagram (VM + containers + Azure services)
- [ ] Functional Architecture block diagram (6 modules + interactions)
- [ ] Moderation Pipeline sequence diagram
- [ ] Session Lifecycle state diagram (4 states)
- [ ] Speaking Turn Flow sequence diagram
- [ ] Audio Flow diagram (forwarding paths)

---

## Implementation Checklist

- [ ] Section 1: Deployment Architecture
- [ ] Section 2.1: Functional Architecture
- [ ] Section 2.2: Implementation Architecture
- [ ] Section 3.1: Moderation Pipeline Overview
- [ ] Section 3.2: Trigger System
- [ ] Section 3.3: LLM Integration & Prompt Design
- [ ] Section 3.4: Intervention Control
- [ ] Section 4.1: Session Lifecycle (diagram + caption)
- [ ] Section 4.2: Speaking Turn Flow
- [ ] Section 4.3: Audio Flow (diagram + caption)
