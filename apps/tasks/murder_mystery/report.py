"""
Logica report-specifica di Murder Mystery.

Step 5 del refactor task-pluggable: il prompt LLM per il report, la sezione
PDF dei voti e la raccolta dati voti/colpevole vivevano hardcoded nel core
(apps/reports/ e apps/sessions/services.py). Ora sono isolati qui e il core
li ottiene tramite MurderMysteryTask.build_report_*() / collect_report_context().
"""

from typing import Any, Dict


# Prompt LLM per il report MM — verbatim dal pre-refactor
# (apps/reports/llm_service.py:REPORT_SYSTEM_PROMPT).
REPORT_LLM_PROMPT = """Sei un analista di sessioni di discussione moderate su AIutami.

Genera un report testuale completo in italiano per una sessione di Murder Mystery.

Il report deve includere queste sezioni (usa esattamente questi titoli):

RISULTATO FINALE
- Chi era il colpevole
- Quanti partecipanti hanno indovinato (es. "2 su 3")
- Percentuale di successo

VOTI DEI PARTECIPANTI
- Lista dei partecipanti con chi hanno scelto e se era corretto (usa ✓ o ✗)

STATISTICHE PARTECIPAZIONE
- Interventi per partecipante con percentuali
- Interventi del moderatore AI con percentuale
- Commenta il Gini index della partecipazione (0 = perfetta uguaglianza, 1 = massima disuguaglianza)

RIASSUNTO DELLA DISCUSSIONE
- Basato sul final_summary fornito, rielaboralo in modo discorsivo

ANALISI FINALE
- Un breve paragrafo (3-5 frasi) che analizza come è andata la sessione
- Commenta la partecipazione, eventuali dinamiche interessanti, e il risultato finale

Formato:
- Usa testo semplice, NO markdown
- Separa le sezioni con una riga vuota
- Tono informativo ma accessibile (il pubblico sono ragazzi)
- Lunghezza totale: 300-500 parole
"""


def collect_mm_report_context(session) -> Dict[str, Any]:
    """
    Raccoglie voti e calcola correttezza per il report MM.
    Logica verbatim da apps/sessions/services.py:_collect_report_data.
    """
    from .models import SessionVote, MURDER_MYSTERY_GUILTY

    votes = SessionVote.objects.filter(session=session).select_related(
        "participant__user"
    )
    votes_data = []
    correct_count = 0
    for vote in votes:
        username = (
            getattr(vote.participant.user, "display_name", None)
            or vote.participant.user.get_username()
        )
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
        "votes": votes_data,
        "guilty": MURDER_MYSTERY_GUILTY,
        "success_rate": success_rate,
    }


def build_mm_pdf_sections(session, context: Dict[str, Any], styles: Dict[str, Any]) -> list:
    """
    Sezioni PDF task-specifiche per MM: risultato finale + tabella voti.
    Logica verbatim da apps/reports/pdf_service.py:generate_pdf (righe 102-137).
    """
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from .models import SessionVote, MURDER_MYSTERY_GUILTY

    section_style = styles["section"]
    body_style = styles["body"]

    elements = []

    votes = SessionVote.objects.filter(session=session).select_related(
        "participant__user"
    )
    total = votes.count()
    correct = sum(1 for v in votes if v.suspect_chosen == MURDER_MYSTERY_GUILTY)
    success_rate = int((correct / total) * 100) if total > 0 else 0

    # Sezione risultato finale
    elements.append(Paragraph("RISULTATO FINALE", section_style))
    elements.append(Paragraph(
        f"Il colpevole era: <b>{MURDER_MYSTERY_GUILTY}</b>", body_style
    ))
    elements.append(Paragraph(
        f"Partecipanti che hanno indovinato: {correct}/{total}", body_style
    ))
    elements.append(Paragraph(
        f"Percentuale di successo: {success_rate}%", body_style
    ))
    elements.append(Spacer(1, 12))

    # Tabella voti
    elements.append(Paragraph("VOTI", section_style))
    vote_data = [["Partecipante", "Scelta", "Risultato"]]
    for vote in votes:
        username = (
            getattr(vote.participant.user, "display_name", None)
            or vote.participant.user.get_username()
        )
        result = "Corretto" if vote.suspect_chosen == MURDER_MYSTERY_GUILTY else "Sbagliato"
        vote_data.append([username, vote.suspect_chosen, result])

    vote_table = Table(vote_data, colWidths=[6 * cm, 4 * cm, 4 * cm])
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
    elements.append(vote_table)
    elements.append(Spacer(1, 12))

    return elements


def build_mm_report_fallback_lines(data: Dict[str, Any]) -> list[str]:
    """
    Righe extra per il fallback report MM (voti + colpevole).
    Logica verbatim da apps/reports/llm_service.py:_fallback_report.
    """
    lines = [
        f"Il colpevole era: {data.get('guilty', 'Sconosciuto')}",
        f"Percentuale di successo: {data.get('success_rate', 0)}%",
        "",
        "VOTI DEI PARTECIPANTI",
    ]
    for vote in data.get("votes", []):
        symbol = "\u2713" if vote.get("correct") else "\u2717"
        lines.append(f"- {vote.get('name')}: {vote.get('chose')} {symbol}")
    return lines
