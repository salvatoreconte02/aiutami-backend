
import logging
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.sessions.models import (
    Session,
    SessionState,
)

logger = logging.getLogger(__name__)


def _compute_gini(values: list[int]) -> float:
    """Gini index: 0 = perfetta uguaglianza, 1 = massima disuguaglianza."""
    if not values or all(v == 0 for v in values):
        return 0.0
    n = len(values)
    sorted_vals = sorted(values)
    total = sum(sorted_vals)
    gini_sum = 0
    for i, v in enumerate(sorted_vals):
        gini_sum += (2 * (i + 1) - n - 1) * v
    return gini_sum / (n * total)


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
    # Lock riga per evitare race condition con richieste parallele
    with transaction.atomic():
        session = Session.objects.select_for_update().get(id=session_id)

        # Se già chiusa, esci subito
        if session.state == SessionState.CLOSED:
            logger.info(f"Session {session_id} already closed, skipping")
            return session

        # Segna come CLOSED subito per bloccare altre richieste
        session.state = SessionState.CLOSED
        session.ended_at = timezone.now()
        session.save(update_fields=["state", "ended_at"])

    # Da qui la sessione è CLOSED - sicuro fare operazioni costose
    mod_state = None

    # 1. Recupera summary da ModerationState (se disponibile)
    try:
        from apps.moderation.state import load_moderation_state
        mod_state = load_moderation_state(session_id)
        if mod_state and hasattr(mod_state, 'summary') and mod_state.summary:
            session.final_summary = mod_state.summary
    except Exception as e:
        logger.warning(f"Could not load moderation state for session {session_id}: {e}")

    # 2. Genera report text via LLM
    try:
        from apps.tasks.registry import get_task
        task = get_task(session.context)
        report_data = _collect_report_data(session, mod_state, task)
        session.report_data = report_data
        from apps.reports.llm_service import ReportLLMService
        session.report_text = ReportLLMService.generate_report_text(report_data, task=task)
    except Exception as e:
        logger.warning(f"Could not generate report for session {session_id}: {e}")
        session.report_text = ""

    # 3. Salva report, report_data e summary (stato già aggiornato sopra)
    update_fields = ["report_text", "report_data"]
    if session.final_summary:
        update_fields.append("final_summary")
    session.save(update_fields=update_fields)

    # 4. Pulizia chiavi Redis
    _cleanup_session_redis_keys(session_id)

    logger.info(f"Session {session_id} closed and cleaned up")
    return session


def _collect_report_data(session, mod_state=None, task=None) -> dict:
    """
    Raccoglie i dati per la generazione del report.
    La parte generica (titolo, durata, partecipanti, summary) è qui.
    La parte task-specifica (es. voti MM) è delegata a task.collect_report_context().
    """
    duration_minutes = 0
    if session.started_at and session.ended_at:
        duration_minutes = int((session.ended_at - session.started_at).total_seconds() / 60)
    elif session.started_at:
        duration_minutes = int((timezone.now() - session.started_at).total_seconds() / 60)

    turns_per_participant = {}
    if mod_state and hasattr(mod_state, 'turns_per_participant'):
        turns_per_participant = mod_state.turns_per_participant

    total_human_turns = sum(turns_per_participant.values()) if turns_per_participant else 1

    ai_interventions = 0
    if mod_state and hasattr(mod_state, 'ai_interventions_count'):
        ai_interventions = mod_state.ai_interventions_count

    total_turns = total_human_turns + ai_interventions
    ai_percentage = int((ai_interventions / total_turns) * 100) if total_turns > 0 else 0

    participants_data = []
    for name, turns in turns_per_participant.items():
        percentage = int((turns / total_human_turns) * 100) if total_human_turns > 0 else 0
        participants_data.append({
            "name": name,
            "turns": turns,
            "percentage": percentage,
        })

    gini_index = _compute_gini(list(turns_per_participant.values()))

    data = {
        "session_title": session.title,
        "duration_minutes": duration_minutes,
        "participants": participants_data,
        "total_human_turns": total_human_turns,
        "total_turns": total_turns,
        "ai_interventions": ai_interventions,
        "ai_intervention_percentage": ai_percentage,
        "gini_index": round(gini_index, 4),
        "final_summary": session.final_summary or "",
    }

    # Mergia dati task-specifici (per MM: votes, guilty, success_rate)
    if task is not None:
        data.update(task.collect_report_context(session))

    return data


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
