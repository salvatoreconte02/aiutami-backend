"""
Report PDF Service - genera PDF del report usando ReportLab.
"""

import io
import logging

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

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

        # Sezioni task-specifiche (per MM: tabella voti; per NASA/LostAtSea:
        # ranking finale + confronto esperto). Passare session.report_data al
        # task: e' il dict completo gia' popolato in _collect_report_data
        # (con has_ranking, items_detail, ranked_items, etc.). Pre-fix era un
        # {} vuoto che faceva uscire sempre "Nessun ranking sottomesso".
        task_sections = task.build_report_pdf_sections(
            session, session.report_data or {}, task_styles
        )
        story.extend(task_sections)

        # Sezione partecipazione (dal report_data salvato)
        if session.report_data:
            story.extend(cls._build_participation_section(
                session.report_data, section_style, body_style
            ))

        # Sezione interventi del moderatore
        if session.report_data and session.report_data.get("interventions_log"):
            story.extend(cls._build_interventions_section(
                session.report_data, section_style, body_style
            ))

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

    @classmethod
    def _build_interventions_section(cls, data: dict, section_style, body_style) -> list:
        """Costruisce la sezione INTERVENTI DEL MODERATORE per il PDF."""
        elements = []
        log = data.get("interventions_log", [])
        if not log:
            return elements

        elements.append(Paragraph("INTERVENTI DEL MODERATORE", section_style))

        # Tabella dettaglio
        table_data = [["#", "Timestamp", "Speaker", "Reason", "Score"]]
        reason_counts: dict[str, int] = {}
        for i, entry in enumerate(log, 1):
            reason = entry.get("reason", "unknown")
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
            ts = entry.get("ts", "")
            # Mostra solo HH:MM:SS se possibile
            if "T" in ts:
                ts = ts.split("T")[1][:8]
            table_data.append([
                str(i),
                ts,
                entry.get("speaker", ""),
                reason,
                f"{entry.get('score', 0):.2f}",
            ])

        interventions_table = Table(
            table_data,
            colWidths=[1 * cm, 3 * cm, 4 * cm, 3.5 * cm, 2.5 * cm],
        )
        interventions_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (2, 1), (2, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.white),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        elements.append(interventions_table)
        elements.append(Spacer(1, 8))

        # Riepilogo per reason
        breakdown = ", ".join(f"{count} {reason}" for reason, count in sorted(reason_counts.items()))
        elements.append(Paragraph(
            f"Totale: <b>{len(log)}</b> interventi &mdash; {breakdown}",
            body_style,
        ))
        elements.append(Spacer(1, 12))

        return elements

    @classmethod
    def _build_participation_section(cls, data: dict, section_style, body_style) -> list:
        """Costruisce la sezione STATISTICHE PARTECIPAZIONE per il PDF."""
        elements = []

        elements.append(Paragraph("STATISTICHE PARTECIPAZIONE", section_style))

        # Tabella partecipanti — tempo di parlato (sec) + percentuale sul totale
        def _fmt_secs(secs: float) -> str:
            mm, ss = divmod(int(secs), 60)
            return f"{mm}:{ss:02d}"

        table_data = [["Partecipante", "Tempo parlato", "%"]]
        for p in data.get("participants", []):
            secs = float(p.get("speaking_time_s") or 0)
            table_data.append([
                p.get("name", ""),
                _fmt_secs(secs),
                f"{p.get('percentage', 0)}%",
            ])
        # Riga moderatore AI: numero di interventi (no percentuale: AI parla
        # in time slots distinti, percentuale non confrontabile con i partecipanti)
        ai_interventions = data.get("ai_interventions", 0)
        table_data.append(["Moderatore AI", f"{ai_interventions} interventi", "—"])

        part_table = Table(
            table_data,
            colWidths=[8 * cm, 3 * cm, 3 * cm],
        )
        part_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
            ('GRID', (0, 0), (-1, -1), 1, colors.white),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))
        elements.append(part_table)
        elements.append(Spacer(1, 8))

        # Gini index — evidenziato in box dedicato (metrica chiave per
        # l'analisi empirica: confronto moderato vs unmoderated)
        gini = data.get("gini_index", 0)
        if gini <= 0.2:
            gini_label = "molto equilibrata"
        elif gini <= 0.4:
            gini_label = "abbastanza equilibrata"
        elif gini <= 0.6:
            gini_label = "moderatamente sbilanciata"
        else:
            gini_label = "sbilanciata"

        elements.append(Spacer(1, 4))
        gini_style = ParagraphStyle(
            "GiniHighlight",
            parent=body_style,
            fontSize=12,
            leading=16,
            textColor=colors.HexColor('#1B4F72'),
            alignment=1,  # center
        )
        # Box visivo: tabella di una sola cella con sfondo colorato
        gini_box_data = [[Paragraph(
            f"<b>Indice di Gini (tempo parlato): {gini:.2f}</b><br/>"
            f"Partecipazione <b>{gini_label}</b><br/>"
            f"<font size=\"9\" color=\"#555555\">"
            f"0 = perfetta uguaglianza, 1 = massima disuguaglianza"
            f"</font>",
            gini_style,
        )]]
        gini_box = Table(gini_box_data, colWidths=[14 * cm])
        gini_box.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#EAF4FB')),
            ('BOX', (0, 0), (-1, -1), 1.5, colors.HexColor('#2E86AB')),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(gini_box)
        elements.append(Spacer(1, 12))

        return elements
