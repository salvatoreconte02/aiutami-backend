"""Finalizzazione della fase INDIVIDUAL_RANKING.

Funzione idempotente che chiude la fase pre-discussione di una sessione e
transita ad ACTIVE. Triggerata da:
1) POST /individual-ranking/submit/ quando l'ultimo partecipante submitta;
2) Lazy check sui PUT/POST quando il timer è scaduto;
3) POST /individual-ranking/finalize-if-expired/ chiamato dal frontend al
   setTimeout 8 min.

La funzione vive nel core (apps.tasks) per restare agnostica al task
specifico: delega a TaskDefinition.individual_ranking_model() e
default_individual_ranking() la conoscenza del modello concreto.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.moderation.intro import set_intro_pending
from apps.moderation.timers_state import mark_session_started
from apps.sessions.models import Session, SessionState
from apps.sessions.serializers import SessionDetailSerializer
from apps.sessions.views import _broadcast_session_event
from apps.tasks.registry import get_task
from apps.turns.services import TurnManager


def _finalize_individual_ranking_phase(session: Session) -> bool:
    """Chiude INDIVIDUAL_RANKING e transita ad ACTIVE.

    Idempotente: chiamabile in sicurezza N volte; solo la prima esegue la
    transizione.

    Returns:
        True se la finalizzazione è effettivamente avvenuta in questa chiamata,
        False se la sessione non era in INDIVIDUAL_RANKING (già transizionata
        o stato sbagliato).
    """
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        if session.state != SessionState.INDIVIDUAL_RANKING:
            return False

        task = get_task(session.context)
        Model = task.individual_ranking_model()
        default_items = task.default_individual_ranking()

        if Model is None:
            # Stato inconsistente: fase INDIVIDUAL_RANKING ma il task non
            # espone un modello individuale. Non dovrebbe mai accadere se
            # i task sono configurati correttamente.
            raise RuntimeError(
                f"Task {task.key!r} è in INDIVIDUAL_RANKING ma "
                f"individual_ranking_model() ritorna None."
            )

        for participant in session.participants.all():
            ranking, created = Model.objects.get_or_create(
                session=session,
                participant=participant,
                defaults={
                    "ranked_items": list(default_items),
                    "is_submitted": True,
                },
            )
            if not created and not ranking.is_submitted:
                ranking.is_submitted = True
                ranking.save(update_fields=["is_submitted", "updated_at"])

        session.state = SessionState.ACTIVE
        session.started_at = timezone.now()
        session.save(update_fields=["state", "started_at"])

    # Side-effects ACTIVE-specific (fuori transazione DB).
    # Stesso ordine di SessionStartView: TurnManager prepara il loop, intro
    # pending mette in coda l'intro del moderatore, mark_session_started
    # azzera i timer di moderazione. Eseguiti DOPO il commit DB perché un
    # eventuale fallimento Redis lascia la sessione coerente lato Postgres
    # (gli stessi side-effects sono idempotenti su read successivi).
    TurnManager.set_introducing(session_id=str(session.id))
    set_intro_pending(session_id=str(session.id))
    mark_session_started(session_id=session.id)

    detail_data = SessionDetailSerializer(session).data
    _broadcast_session_event(
        session_id=str(session.id),
        event_type="STATE_CHANGED",
        payload=detail_data,
    )
    return True
