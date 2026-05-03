"""
Logica report-specifica di NASA Moon Survival.

Prompt LLM per il report, raccolta dati (ranking + scoring), sezioni PDF
con tabella comparativa team vs expert.
"""

from typing import Any, Dict

from .config import EXPERT_RANKING, compute_error_score, MAX_ERROR_SCORE


def build_nasa_report_llm_prompt(language: str = "Italian") -> str:
    """System prompt LLM per il report NASA Moon Survival, parametrizzato
    per lingua di output (il PDF e' user-facing)."""
    return f"""You are an analyst of moderated group discussion sessions on AIutami.

Generate a complete text report in {language} for a NASA Moon Survival Challenge session.

The report must include these sections (use exactly these titles, translated into {language}):

RANKING RESULT
- Group error score (lower = better, range 0-112)
- Qualitative evaluation (excellent / good / average / poor)

COMPARISON WITH EXPERTS
- Items positioned correctly or nearly so
- Most significant errors (items very far from the expert position)

PARTICIPATION STATISTICS
- For each participant report `speaking_time_s` (seconds spoken) and `percentage` of total speaking time. Convert seconds into minutes:seconds for readability (e.g. 245.0s → "4 min 05 sec").
- AI moderator interventions count
- Comment on the Gini index of speaking-time participation (0 = perfect equality, 1 = max inequality). Cite `total_speaking_time_s` as a reference.

MODERATOR INTERVENTIONS
If `interventions_log` is present, include:
- Total number of AI interventions
- Breakdown by reason (e.g. "3 off_topic, 2 monopolization, 1 user_request")
- For each intervention: timestamp, reason, speaker who had spoken

DISCUSSION SUMMARY
- Based on the provided final_summary, reformulate it in a discursive way
- Highlight whether the group followed the procedural consensus rules

FINAL ANALYSIS
- A short paragraph (3-5 sentences) analyzing how the session went
- Comment on the quality of the decision process and participation

Format:
- Use plain text, NO markdown
- Separate sections with a blank line
- Informative but accessible tone
- Total length: 300-500 words

IMPORTANT: write the entire report in {language}, including section titles.
"""


# Backward-compat alias (default Italian).
REPORT_LLM_PROMPT = build_nasa_report_llm_prompt("Italian")


def collect_nasa_report_context(session) -> Dict[str, Any]:
    """
    Raccoglie ranking di gruppo e calcola error score per il report.
    """
    from .models import NasaRanking

    try:
        ranking = NasaRanking.objects.get(session=session)
        ranked_items = ranking.ranked_items
        error_score = compute_error_score(ranked_items)

        # Dettaglio per-item
        items_detail = []
        for i, item in enumerate(ranked_items):
            team_rank = i + 1
            expert_rank = EXPERT_RANKING[item]
            diff = abs(team_rank - expert_rank)
            items_detail.append({
                "item": item,
                "team_rank": team_rank,
                "expert_rank": expert_rank,
                "diff": diff,
            })

        return {
            "ranked_items": ranked_items,
            "error_score": error_score,
            "max_error_score": MAX_ERROR_SCORE,
            "items_detail": items_detail,
            "has_ranking": True,
        }
    except NasaRanking.DoesNotExist:
        return {"has_ranking": False}


def build_nasa_pdf_sections(session, context: Dict[str, Any], styles: Dict[str, Any]) -> list:
    """
    Sezioni PDF task-specifiche per NASA Moon: tabella ranking team vs expert + score.
    """
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    section_style = styles["section"]
    body_style = styles["body"]

    elements = []

    if not context.get("has_ranking"):
        elements.append(Paragraph("RANKING", section_style))
        elements.append(Paragraph(
            "Nessun ranking sottomesso per questa sessione.", body_style
        ))
        return elements

    error_score = context["error_score"]

    # Valutazione qualitativa basata sull'error score
    if error_score <= 20:
        quality = "Eccellente"
    elif error_score <= 35:
        quality = "Buono"
    elif error_score <= 50:
        quality = "Nella media"
    else:
        quality = "Scarso"

    # Sezione risultato
    elements.append(Paragraph("RISULTATO RANKING", section_style))
    elements.append(Paragraph(
        f"Error score: <b>{error_score}</b> / {MAX_ERROR_SCORE} ({quality})", body_style
    ))
    elements.append(Spacer(1, 12))

    # Tabella comparativa
    elements.append(Paragraph("CONFRONTO CON RANKING ESPERTO", section_style))
    table_data = [["Oggetto", "Gruppo", "Esperto", "Diff."]]
    for item_info in context["items_detail"]:
        table_data.append([
            item_info["item"],
            str(item_info["team_rank"]),
            str(item_info["expert_rank"]),
            str(item_info["diff"]),
        ])

    ranking_table = Table(
        table_data,
        colWidths=[8 * cm, 2 * cm, 2 * cm, 2 * cm],
    )
    ranking_table.setStyle(TableStyle([
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
    elements.append(ranking_table)
    elements.append(Spacer(1, 12))

    return elements


def build_nasa_report_fallback_lines(data: Dict[str, Any]) -> list[str]:
    """
    Righe extra per il fallback report NASA Moon (ranking + score).
    """
    if not data.get("has_ranking"):
        return ["Nessun ranking sottomesso."]

    lines = [
        f"Error score: {data.get('error_score', '?')} / {MAX_ERROR_SCORE}",
        "",
        "RANKING GRUPPO vs ESPERTO",
    ]
    for item_info in data.get("items_detail", []):
        diff = item_info["diff"]
        marker = "" if diff == 0 else f" (diff {diff})"
        lines.append(
            f"  {item_info['team_rank']}. {item_info['item']} "
            f"(esperto: {item_info['expert_rank']}){marker}"
        )
    return lines
