"""
Logica report-specifica di Murder Mystery.

Step 5 del refactor task-pluggable: il prompt LLM per il report, la sezione
PDF dei voti e la raccolta dati voti/colpevole vivevano hardcoded nel core
(apps/reports/ e apps/sessions/services.py). Ora sono isolati qui e il core
li ottiene tramite MurderMysteryTask.build_report_*() / collect_report_context().
"""

from typing import Any, Dict


def build_mm_report_llm_prompt(language: str = "Italian") -> str:
    """System prompt LLM per il report Murder Mystery, parametrizzato per
    lingua di output (il PDF e' user-facing). Le istruzioni sono in inglese
    per coerenza con il moderator system prompt; la lingua di output e'
    iniettata via {language}."""
    return f"""You are an analyst of moderated group discussion sessions on AIutami.

Generate a complete text report in {language} for a Murder Mystery session.

The report must include these sections (use exactly these titles, translated into {language}):

FINAL RESULT
- Who the murderer was
- How many participants guessed correctly (e.g. "2 out of 3")
- Success rate

PARTICIPANT VOTES
- List of participants with who they chose and whether it was correct (use ✓ or ✗)

PARTICIPATION STATISTICS
- Turns per participant with percentages
- AI moderator interventions with percentage
- Comment on the Gini index of participation (0 = perfect equality, 1 = max inequality)

MODERATOR INTERVENTIONS
If `interventions_log` is present, include:
- Total number of AI interventions
- Breakdown by reason (e.g. "3 off_topic, 2 monopolization, 1 user_request")
- For each intervention: timestamp, reason, speaker who had spoken

DISCUSSION SUMMARY
- Based on the provided final_summary, reformulate it in a discursive way

FINAL ANALYSIS
- A short paragraph (3-5 sentences) analyzing how the session went
- Comment on participation, any interesting dynamics, and the final result

Format:
- Use plain text, NO markdown
- Separate sections with a blank line
- Informative but accessible tone (audience: young adults)
- Total length: 300-500 words

IMPORTANT: write the entire report in {language}, including section titles.
"""


# Backward-compat alias (default Italian).
REPORT_LLM_PROMPT = build_mm_report_llm_prompt("Italian")


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
