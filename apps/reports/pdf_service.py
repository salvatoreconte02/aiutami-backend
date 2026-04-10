"""
Report PDF Service - genera PDF del report usando ReportLab.
"""

import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

logger = logging.getLogger(__name__)


class ReportPDFService:
    """
    Servizio per generare PDF del report sessione.
    Scheletro task-agnostic: titolo, data/durata e testo LLM sono generici.
    Le sezioni task-specifiche (es. tabella voti MM) vengono iniettate dal
    TaskDefinition tramite build_report_pdf_sections().
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
        from apps.tasks.registry import get_task

        task = get_task(session.context)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2*cm,
        )

        # Stili
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

        # Dict di stili passato al task per le sezioni extra
        task_styles = {
            "section": section_style,
            "body": body_style,
        }

        # Costruisci contenuto
        story = []

        # Titolo (dal task)
        story.append(Paragraph(task.report_title(), title_style))
        story.append(Paragraph(f'"{session.title}"', subtitle_style))

        # Data e durata
        date_str = session.created_at.strftime("%d/%m/%Y")
        duration = 0
        if session.started_at and session.ended_at:
            duration = int((session.ended_at - session.started_at).total_seconds() / 60)
        story.append(Paragraph(f"Data: {date_str} - Durata: {duration} minuti", body_style))
        story.append(Spacer(1, 12))

        # Sezioni task-specifiche (per MM: risultato finale + tabella voti)
        task_sections = task.build_report_pdf_sections(session, {}, task_styles)
        story.extend(task_sections)

        # Testo report (generato da LLM)
        if session.report_text:
            story.append(Paragraph("ANALISI DELLA SESSIONE", section_style))
            # Dividi per paragrafi e aggiungi
            for para in session.report_text.split('\n\n'):
                if para.strip():
                    # Escape entità HTML
                    safe_para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    story.append(Paragraph(safe_para, body_style))
                    story.append(Spacer(1, 6))

        # Riassunto se disponibile
        if session.final_summary and not session.report_text:
            story.append(Paragraph("RIASSUNTO DELLA DISCUSSIONE", section_style))
            safe_summary = session.final_summary.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(safe_summary, body_style))
            story.append(Spacer(1, 12))

        # Footer
        story.append(Paragraph("Generato da AIutami", footer_style))

        # Genera PDF
        doc.build(story)

        pdf_bytes = buffer.getvalue()
        buffer.close()

        logger.info("[REPORT][PDF] Generated PDF for session %s, size: %d bytes", session.id, len(pdf_bytes))
        return pdf_bytes
