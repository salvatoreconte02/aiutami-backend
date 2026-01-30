"""
Report PDF Service - genera PDF del report usando ReportLab.
"""

import io
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)


class ReportPDFService:
    """
    Servizio per generare PDF del report sessione.
    """

    @classmethod
    def generate_pdf(cls, session) -> bytes:
        """
        Genera un PDF dal report della sessione.

        Args:
            session: istanza Session con report_text popolato

        Returns:
            bytes del PDF generato
        """
        from apps.sessions.models import SessionVote, SessionParticipant, MURDER_MYSTERY_GUILTY

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
        )

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=12,
            alignment=1,  # Center
        )
        subtitle_style = ParagraphStyle(
            'CustomSubtitle',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.grey,
            alignment=1,
            spaceAfter=20,
        )
        section_style = ParagraphStyle(
            'SectionHeader',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor('#2E86AB'),
        )
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=11,
            leading=14,
            spaceAfter=8,
        )
        footer_style = ParagraphStyle(
            'Footer',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.grey,
            alignment=1,
            spaceBefore=30,
        )

        # Build content
        story = []

        # Title
        story.append(Paragraph("REPORT SESSIONE MURDER MYSTERY", title_style))
        story.append(Paragraph(f'"{session.title}"', subtitle_style))

        # Date and duration
        date_str = session.created_at.strftime("%d/%m/%Y")
        duration = 0
        if session.started_at and session.ended_at:
            duration = int((session.ended_at - session.started_at).total_seconds() / 60)
        story.append(Paragraph(f"Data: {date_str} - Durata: {duration} minuti", body_style))
        story.append(Spacer(1, 12))

        # Results section
        votes = SessionVote.objects.filter(session=session).select_related("participant__user")
        total = votes.count()
        correct = sum(1 for v in votes if v.suspect_chosen == MURDER_MYSTERY_GUILTY)
        success_rate = int((correct / total) * 100) if total > 0 else 0

        story.append(Paragraph("RISULTATO FINALE", section_style))
        story.append(Paragraph(f"Il colpevole era: <b>{MURDER_MYSTERY_GUILTY}</b>", body_style))
        story.append(Paragraph(f"Partecipanti che hanno indovinato: {correct}/{total}", body_style))
        story.append(Paragraph(f"Percentuale di successo: {success_rate}%", body_style))
        story.append(Spacer(1, 12))

        # Votes table
        story.append(Paragraph("VOTI", section_style))
        vote_data = [["Partecipante", "Scelta", "Risultato"]]
        for vote in votes:
            username = getattr(vote.participant.user, "display_name", None) or vote.participant.user.get_username()
            result = "Corretto" if vote.suspect_chosen == MURDER_MYSTERY_GUILTY else "Sbagliato"
            vote_data.append([username, vote.suspect_chosen, result])

        vote_table = Table(vote_data, colWidths=[6*cm, 4*cm, 4*cm])
        vote_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.white),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ]))
        story.append(vote_table)
        story.append(Spacer(1, 12))

        # Report text (LLM generated)
        if session.report_text:
            story.append(Paragraph("ANALISI DELLA SESSIONE", section_style))
            # Split by paragraphs and add each
            for para in session.report_text.split('\n\n'):
                if para.strip():
                    # Escape HTML entities
                    safe_para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    story.append(Paragraph(safe_para, body_style))
                    story.append(Spacer(1, 6))

        # Summary if available
        if session.final_summary and not session.report_text:
            story.append(Paragraph("RIASSUNTO DELLA DISCUSSIONE", section_style))
            safe_summary = session.final_summary.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(safe_summary, body_style))
            story.append(Spacer(1, 12))

        # Footer
        story.append(Paragraph("Generato da AIutami", footer_style))

        # Build PDF
        doc.build(story)

        pdf_bytes = buffer.getvalue()
        buffer.close()

        logger.info("[REPORT][PDF] Generated PDF for session %s, size: %d bytes", session.id, len(pdf_bytes))
        return pdf_bytes
