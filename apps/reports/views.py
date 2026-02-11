"""
Report views - endpoint download.
"""

from django.shortcuts import get_object_or_404
from django.http import HttpResponse

from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.sessions.models import Session, SessionParticipant, SessionState
from .pdf_service import ReportPDFService


class SessionReportDownloadView(APIView):
    """
    GET /api/sessions/{session_id}/report/
    Scarica il report PDF della sessione.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, session_id: str):
        session = get_object_or_404(Session, pk=session_id)

        # Verifica che utente sia partecipante
        if not SessionParticipant.objects.filter(
            session=session, user=request.user
        ).exists():
            return Response(
                {"detail": "Non sei un partecipante di questa sessione."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Verifica che sessione sia CLOSED
        if session.state != SessionState.CLOSED:
            return Response(
                {"detail": "Il report è disponibile solo per sessioni concluse."},
                status=status.HTTP_409_CONFLICT,
            )

        # Genera PDF
        pdf_bytes = ReportPDFService.generate_pdf(session)

        # Ritorna come download
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="report-{session.id}.pdf"'
        return response
