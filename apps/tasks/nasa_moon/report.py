"""
Logica report-specifica di NASA Moon Survival.

Prompt LLM per il report, raccolta dati (ranking + scoring), sezioni PDF
con tabella comparativa team vs expert.
"""

from typing import Any, Dict

from .config import EXPERT_RANKING, compute_error_score, MAX_ERROR_SCORE


def build_nasa_report_llm_prompt(language: str = "Italian") -> str:
    """System prompt LLM per il report NASA Moon Survival.

    NOTA: questo prompt genera SOLO la parte narrativa del report. Le tabelle
    strutturate (ranking finale, partecipazione, interventi del moderatore,
    confronto con esperto) sono gia' renderizzate dal pdf_service come
    elementi visivi separati. NON duplicarle nel testo: il LLM deve produrre
    interpretazione, non riepilogo dei dati grezzi.
    """
    return f"""You are an analyst of moderated group discussion sessions on AIutami.

Generate the NARRATIVE portion of a session report for the NASA Moon Survival
Challenge, in {language}. The PDF that wraps your output ALREADY shows the
following as structured tables / sections, so DO NOT reproduce them verbatim
in your text:

  - The final group ranking of the 15 items (table)
  - Speaking time per participant + Gini index (table + summary line)
  - The list of moderator interventions with timestamp / reason / speaker (table)
  - Item-by-item comparison with the expert ranking (table)

Your job is to produce the INTERPRETATION around those tables.

Generate exactly these four sections (use these titles, translated into {language}):

RANKING RESULT
- Briefly state the group error score and the qualitative evaluation
  (excellent / good / average / poor). One or two sentences.
- If `synergy_gain` is provided, comment whether the group's discussion
  improved over the average individual baseline. If null, do not mention it.

COMPARISON WITH EXPERTS
- Highlight 2-3 items the group got close to the expert ranking, with the
  reason if it can be inferred from the discussion summary.
- Highlight 2-3 items the group placed far from the expert ranking and
  briefly comment what may have driven the divergence.

DISCUSSION SUMMARY
- Reformulate the provided `final_summary` as a fluid narrative paragraph.
- Mention whether the group adhered to the Hall & Watson consensus rules
  (avoiding voting / averaging / ultimatums) only if there is evidence
  for it in the summary or interventions_log.

FINAL ANALYSIS
- A short paragraph (3-5 sentences) interpreting how the session went.
- Comment on the quality of the decision process and the participation
  balance (referring qualitatively to the Gini index — e.g. "balanced",
  "moderately uneven" — without restating the numerical value, which
  is already in the table).

Format:
- Plain text, NO markdown.
- Separate sections with a blank line.
- Use the exact section titles above (translated into {language}).
- Total length: 200-350 words. Be concise — the tables already cover the data.

IMPORTANT: write the entire report in {language}, including section titles.
Do NOT include any "PARTICIPATION STATISTICS" or "MODERATOR INTERVENTIONS"
section: those are shown as tables before your text.
"""


# Backward-compat alias (default Italian).
REPORT_LLM_PROMPT = build_nasa_report_llm_prompt("Italian")


def collect_nasa_report_context(session) -> Dict[str, Any]:
    """Raccoglie ranking di gruppo + ranking individuali per il report.

    Calcola synergy_gain e assembly_bonus se ci sono ranking individuali
    submitted; altrimenti i campi restano None (sessioni legacy).
    """
    from .models import NasaRanking, NasaIndividualRanking

    base: Dict[str, Any] = {
        "synergy_gain": None,
        "individual_errors": None,
        "assembly_bonus": None,
        "mean_individual_error": None,
        "individual_count": 0,
    }

    try:
        ranking = NasaRanking.objects.get(session=session)
        ranked_items = ranking.ranked_items
        error_score = compute_error_score(ranked_items)

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

        base.update({
            "ranked_items": ranked_items,
            "error_score": error_score,
            "max_error_score": MAX_ERROR_SCORE,
            "items_detail": items_detail,
            "has_ranking": True,
        })
    except NasaRanking.DoesNotExist:
        base.update({"has_ranking": False})

    # Synergy gain calc (solo se ci sono ranking individuali submitted)
    individual_rankings = list(
        NasaIndividualRanking.objects.filter(session=session, is_submitted=True)
    )
    if individual_rankings and base.get("has_ranking"):
        individual_errors = [
            compute_error_score(r.ranked_items) for r in individual_rankings
        ]
        group_error = base["error_score"]
        mean_individual_error = sum(individual_errors) / len(individual_errors)
        base["individual_errors"] = individual_errors
        base["mean_individual_error"] = mean_individual_error
        base["synergy_gain"] = mean_individual_error - group_error
        base["assembly_bonus"] = group_error < min(individual_errors)
        base["individual_count"] = len(individual_errors)

    return base


def build_nasa_pdf_sections(session, context: Dict[str, Any], styles: Dict[str, Any]) -> list:
    """
    Sezioni PDF task-specifiche per NASA Moon:
      - RANKING FINALE GRUPPO (15 item ordinati dal 1 al 15)
      - RISULTATO (error score + qualitative + synergy gain placeholder)
      - CONFRONTO CON RANKING ESPERTO (tabella comparativa)
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
    items_detail = context["items_detail"]

    # === RANKING FINALE GRUPPO ===
    elements.append(Paragraph("RANKING FINALE GRUPPO", section_style))
    final_ranking_data = [["Posizione", "Oggetto"]]
    for item_info in items_detail:
        final_ranking_data.append([
            str(item_info["team_rank"]),
            item_info["item"],
        ])

    final_ranking_table = Table(
        final_ranking_data,
        colWidths=[2.5 * cm, 11.5 * cm],
    )
    final_ranking_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E86AB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
        ('GRID', (0, 0), (-1, -1), 1, colors.white),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    elements.append(final_ranking_table)
    elements.append(Spacer(1, 12))

    # === RISULTATO + METRICHE EMPIRICHE ===
    if error_score <= 20:
        quality = "Eccellente"
    elif error_score <= 35:
        quality = "Buono"
    elif error_score <= 50:
        quality = "Nella media"
    else:
        quality = "Scarso"

    elements.append(Paragraph("RISULTATO", section_style))
    elements.append(Paragraph(
        f"Error score: <b>{error_score}</b> / {MAX_ERROR_SCORE} "
        f"&mdash; valutazione: <b>{quality}</b>",
        body_style,
    ))

    # Synergy gain
    synergy = context.get("synergy_gain")
    mean_ind = context.get("mean_individual_error")
    if synergy is None:
        elements.append(Paragraph(
            "Synergy gain: <i>N/A &mdash; nessun ranking individuale registrato.</i>",
            body_style,
        ))
    else:
        sign = "+" if synergy >= 0 else ""
        comment = (
            "il gruppo ha migliorato rispetto alla media individuale"
            if synergy > 0
            else "il gruppo ha peggiorato rispetto alla media individuale (process loss)"
            if synergy < 0
            else "il gruppo ha eguagliato la media individuale"
        )
        elements.append(Paragraph(
            f"Synergy gain: <b>{sign}{synergy:.1f}</b> "
            f"(media individuale {mean_ind:.1f} - error gruppo {error_score} — {comment})",
            body_style,
        ))

    # Assembly bonus
    assembly = context.get("assembly_bonus")
    individual_errors = context.get("individual_errors")
    if assembly is True and individual_errors:
        elements.append(Paragraph(
            f"Assembly bonus: <b>SI</b> &mdash; il gruppo ha fatto meglio "
            f"del miglior individuo: {error_score} vs {min(individual_errors)}.",
            body_style,
        ))
    elif assembly is False and individual_errors:
        elements.append(Paragraph(
            f"Assembly bonus: <b>NO</b> &mdash; almeno un partecipante "
            f"individualmente ha fatto meglio del gruppo "
            f"({min(individual_errors)} vs {error_score}).",
            body_style,
        ))
    # Se None, non mostrare nulla
    elements.append(Spacer(1, 12))

    # === CONFRONTO CON RANKING ESPERTO ===
    elements.append(Paragraph("CONFRONTO CON RANKING ESPERTO", section_style))
    table_data = [["Oggetto", "Gruppo", "Esperto", "Diff."]]
    for item_info in items_detail:
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
