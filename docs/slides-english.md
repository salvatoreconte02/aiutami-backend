# SLIDE 1 — Title

**ARCHITECTURES AND AI MODERATION STRATEGIES FOR MULTI-PARTY SPEECH CONVERSATIONAL SYSTEMS**

Salvatore Conte

Prof. Franca Garzotto
Tutor Pietro Ammaturo

Politecnico di Milano — 2026

---

# SLIDE 2 — Research Gaps (GAP 1 & 2)

## Research Gaps from the State of the Art

### GAP 1 — Voice-based systems are almost always dyadic

- Voice conversational systems are designed for 1 user ↔ 1 agent
- Existing multiparty systems are almost all text-based (chat, forums, Slack)
- The very few multiparty + speech systems (ARI, Furhat) support only 2 humans + 1 robot and rely on gaze/video

### GAP 2 — Existing multiparty systems are almost all text-based

**Table:**

|              | Dyadic                      | Multiparty            |
|--------------|-----------------------------|-----------------------|
| Text-based   | Chatbot, ChatGPT            | Koala, Slack, forums  |
| Speech-based | Moshi, GPT-4o, Alexa, Siri  | **AIutami**           |

---

# SLIDE 3 — Research Gaps (GAP 3 & 4)

## Research Gaps from the State of the Art

### GAP 3 — No architectures designed for multiparty speech

Current voice architectures (STT→LLM→TTS pipeline, half-cascade, end-to-end) assume a single speaker ↔ a single agent.

Multiparty requires:
- Managing N parallel audio streams
- Turn-taking among N participants
- Deciding when and to whom to respond

### GAP 4 — The role of AI as a group moderator is understudied

- Most conversational agents act as assistants, Q&A systems, or information support
- Very few works study AI in the role of conversation moderator
- No work studies a voice-based AI moderator that in real time:
  - Manages turn-taking
  - Balances participation
  - Guides the discussion without suggesting answers

---

# SLIDE 4 — Thesis Direction

## Thesis Direction

**Title:**
Architectures and AI Moderation Strategies for Multi-Party Speech Conversational Systems

### 1. Architecture for multiparty speech with AI moderator
- Managing N audio streams
- Explicit turn-taking among N participants
- STT → LLM → TTS pipeline with ASR gating
- Modular design: sessions, turns, ASR, moderation, WebRTC

### 2. AI moderation strategies
- When to intervene (end of turn, silence, participation imbalance)
- How to intervene (summarize, re-engage, involve quiet participants)
- Prompt engineering for the moderator role

### 3. Empirical evaluation →

---

# SLIDE 5 — Empirical Evaluation: Proposal A

## Empirical Evaluation — Proposal A: Murder Mystery

- **Task:** 3 participants receive different versions of a detective case; only by combining critical clues can they find the culprit
- **Qualitative comparison** with Dubini's thesis (2024) — same task, but text-based moderation → voice-based
- **Design:** single-condition (all groups with voice AI moderator), then comparison with Dubini's results
- **Metrics:** correct culprit, critical clues, Gini index, discussion focus + SUS, UX
- **Participants:** 30–36 volunteers, 10–12 groups of 3
- **Session duration:** ~75 min (30m reading, 30m moderation, 15m questionnaires)

**Limitations:**
- "Dirty" comparison (modality, platform, and participants all change)
- Long sessions → difficult to recruit unpaid volunteers
- Main metric is binary (correct/incorrect) → low statistical power

---

# SLIDE 6 — Empirical Evaluation: Proposal B

## Empirical Evaluation — Proposal B: Desert Survival Problem

**Task:** plane crash in the desert; rank 15 items for survival.
Expert ranking exists → objective, continuous metric.
Equivalent variants in the literature: Arctic Survival, NASA Moon Survival (same structure, same authors, used in combination for within-subjects studies).

**Procedure (~40 min per session):**
1. Briefing + consent (5 min)
2. Read scenario + individual ranking (5 min)
3. Voice discussion on AIutami (20 min) → group ranking
4. UX questionnaires (10 min)

→ Comparison: individual ranking vs group ranking vs expert ranking = **decision accuracy + synergy score**

### Two design proposals

|                  | B1 — Between-subjects                                      | B2 — Within-subjects                                                                          |
|------------------|-------------------------------------------------------------|-----------------------------------------------------------------------------------------------|
| **Setup**        | 5 groups with, 5 without moderator. All do Desert           | Counterbalanced order: half start with moderator, half without (then switch)                   |
| **Participants** | 30 people, 10 groups                                        | 30 people, 10 groups                                                                          |
| **Duration**     | ~40 min (1 session)                                         | ~80 min (2 sessions)                                                                          |
| **Advantage**    | Single session                                              | Each group is its own control → more statistical power, eliminates between-group variability   |

---

# SLIDE 7 — Why Desert Survival

## Why Choose Desert Survival

|                          | Murder Mystery                                                                                  | Desert Survival                                                                        |
|--------------------------|-------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------|
| **Reading materials**    | 30 min, must memorize clues — heavy for unpaid volunteers                                       | 5 min — one A4 sheet with scenario and item list                                       |
| **Recruitment**          | Difficult; long session. Dubini with Prolific (paid) already had quality issues                  | Realistic — short session, low initial cognitive load                                   |
| **Metric type**          | Binary (correct/incorrect culprit) → low statistical power                                      | Continuous (distance from expert ranking) → higher statistical power                    |
| **Experimental design**  | Single condition, "dirty" comparison with Dubini (modality, platform, participants all change)   | Clean comparison: moderator ON vs OFF, same platform, single variable                   |

---

# SLIDE 8 — The Survival Task in the Literature

## The Survival Task in the Literature

The survival ranking task is one of the most established experimental paradigms in group decision-making research. The original task, the **Desert Survival Problem**, was developed by Lafferty and Eady in 1974: participants must rank 15 items in order of usefulness for survival after a plane crash in the Sonora desert. A correct ranking defined by survival experts provides an objective, continuous metric for evaluating decision quality. It belongs to a family of equivalent variants — Arctic Survival, NASA Moon Survival — used in combination for within-subjects studies.

The paradigm was introduced in research by **Hall and Watson in 1970**, who used the NASA Moon Survival to study the effect of procedural instructions on group decisions. Groups that receive consensus instructions — seek differences of opinion, avoid majority voting — make significantly better decisions and achieve strong synergy (i.e., the group outperforms its best individual member) at higher rates than groups in free discussion. This study, with over 321 citations, established the experimental paradigm used by all subsequent literature.

**Hamada, Nakayama, and Saiki in 2020** used the NASA Moon Survival with 119 participants organized into 25 groups. They confirmed that groups outperform individuals, with a mean error of 36.88 vs 46.99. However, they found an interesting result: free group discussion, without guidance, does not significantly outperform statistical aggregation of individual rankings. This suggests that simply discussing is not enough to unlock the group's potential — deliberative process guidance is needed.

Finally, **Hémon, Cherbonnier, Michinov, Jamet, and Michinov in 2024** used the Desert Survival Problem with 125 participants collaborating via videoconference. Groups that received instructions based on constructive controversy achieved strong synergy at significantly higher rates than free discussion groups, and reported greater epistemic conflict regulation. This paper is particularly relevant because it demonstrates two things: that the Desert Survival works in online and videoconference settings, and that guiding the deliberative process improves group synergy — exactly what AIutami's AI moderator does in real time during the discussion.
