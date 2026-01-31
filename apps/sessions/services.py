"""
Session services - business logic for session management.
"""
import logging
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.sessions.models import (
    Session,
    SessionState,
    SessionParticipant,
    SessionVote,
    MURDER_MYSTERY_GUILTY,
)

logger = logging.getLogger(__name__)


def close_session(session_id: str) -> Session:
    """
    Chiude la sessione, genera il report e salva.

    - Genera report_text via LLM con dati voti e partecipazione
    - Recupera summary da ModerationState se presente
    - Aggiorna stato a CLOSED
    - Cleanup chiavi Redis (transcript, turns, moderation)

    Args:
        session_id: ID della sessione da chiudere

    Returns:
        Session aggiornata
    """
    # Lock row to prevent race condition with parallel close requests
    with transaction.atomic():
        session = Session.objects.select_for_update().get(id=session_id)

        # Early return if already closed
        if session.state == SessionState.CLOSED:
            logger.info(f"Session {session_id} already closed, skipping")
            return session

        # Mark as CLOSED immediately to block other requests
        session.state = SessionState.CLOSED
        session.ended_at = timezone.now()
        session.save(update_fields=["state", "ended_at"])

    # From here, session is locked as CLOSED - safe to do expensive operations
    mod_state = None

    # 1. Recupera summary da ModerationState (se disponibile)
    try:
        from apps.moderation.state import load_moderation_state
        mod_state = load_moderation_state(session_id)
        if mod_state and hasattr(mod_state, 'summary') and mod_state.summary:
            session.final_summary = mod_state.summary
    except Exception as e:
        logger.warning(f"Could not load moderation state for session {session_id}: {e}")

    # 2. Generate report text via LLM
    try:
        report_data = _collect_report_data(session, mod_state)
        from apps.reports.llm_service import ReportLLMService
        session.report_text = ReportLLMService.generate_report_text(report_data)
    except Exception as e:
        logger.warning(f"Could not generate report for session {session_id}: {e}")
        session.report_text = ""

    # 3. Salva report e summary (stato già aggiornato sopra)
    update_fields = ["report_text"]
    if session.final_summary:
        update_fields.append("final_summary")
    session.save(update_fields=update_fields)

    # 4. Cleanup Redis keys
    _cleanup_session_redis_keys(session_id)

    logger.info(f"Session {session_id} closed and cleaned up")
    return session


def _collect_report_data(session, mod_state=None) -> dict:
    """
    Raccoglie i dati per la generazione del report.
    """
    # Calculate duration
    duration_minutes = 0
    if session.started_at and session.ended_at:
        duration_minutes = int((session.ended_at - session.started_at).total_seconds() / 60)
    elif session.started_at:
        duration_minutes = int((timezone.now() - session.started_at).total_seconds() / 60)

    # Get participant turns from moderation state
    turns_per_participant = {}
    if mod_state and hasattr(mod_state, 'turns_per_participant'):
        turns_per_participant = mod_state.turns_per_participant

    total_human_turns = sum(turns_per_participant.values()) if turns_per_participant else 1

    # AI interventions
    ai_interventions = 0
    if mod_state and hasattr(mod_state, 'ai_interventions_count'):
        ai_interventions = mod_state.ai_interventions_count

    total_turns = total_human_turns + ai_interventions
    ai_percentage = int((ai_interventions / total_turns) * 100) if total_turns > 0 else 0

    # Participants with turn stats
    participants_data = []
    for name, turns in turns_per_participant.items():
        percentage = int((turns / total_human_turns) * 100) if total_human_turns > 0 else 0
        participants_data.append({
            "name": name,
            "turns": turns,
            "percentage": percentage,
        })

    # Votes
    votes = SessionVote.objects.filter(session=session).select_related("participant__user")
    votes_data = []
    correct_count = 0
    for vote in votes:
        username = getattr(vote.participant.user, "display_name", None) or vote.participant.user.get_username()
        is_correct = vote.suspect_chosen == MURDER_MYSTERY_GUILTY
        if is_correct:
            correct_count += 1
        votes_data.append({
            "name": username,
            "chose": vote.suspect_chosen,
            "correct": is_correct,
        })

    total_voters = votes.count()
    success_rate = int((correct_count / total_voters) * 100) if total_voters > 0 else 0

    return {
        "session_title": session.title,
        "duration_minutes": duration_minutes,
        "participants": participants_data,
        "ai_interventions": ai_interventions,
        "ai_intervention_percentage": ai_percentage,
        "votes": votes_data,
        "guilty": MURDER_MYSTERY_GUILTY,
        "success_rate": success_rate,
        "final_summary": session.final_summary or "",
    }


def _cleanup_session_redis_keys(session_id: str) -> None:
    """
    Cancella le chiavi Redis associate alla sessione.
    """
    keys_to_delete = [
        f"session:{session_id}:transcript",
        f"turns:{session_id}",
        f"moderation:{session_id}",
    ]

    for key in keys_to_delete:
        try:
            cache.delete(key)
            logger.debug(f"Deleted Redis key: {key}")
        except Exception as e:
            logger.warning(f"Failed to delete Redis key {key}: {e}")
