"""
Logica report-specifica di Lost at Sea.

Prompt LLM per il report, raccolta dati (ranking + scoring), sezioni PDF
con tabella comparativa team vs expert (US Coast Guard).
"""

from typing import Any, Dict

from .config import EXPERT_RANKING, compute_error_score, MAX_ERROR_SCORE


REPORT_LLM_PROMPT = """Sei un analista di sessioni di discussione moderate su AIutami.

Genera un report testuale completo in italiano per una sessione Lost at Sea Survival Challenge.

Il report deve includere queste sezioni (usa esattamente questi titoli):

RISULTATO RANKING
- Error score del gruppo (piu basso = migliore, range 0-112)
- Valutazione qualitativa (eccellente / buono / nella media / scarso)

CONFRONTO CON GLI ESPERTI
- Oggetti posizionati correttamente o quasi
- Errori piu significativi (oggetti molto distanti dalla posizione esperta)

STATISTICHE PARTECIPAZIONE
- Interventi per partecipante con percentuali
- Interventi del moderatore AI con percentuale

RIASSUNTO DELLA DISCUSSIONE
- Basato sul final_summary fornito, rielaboralo in modo discorsivo
- Evidenzia se il gruppo ha seguito le regole procedurali di consenso

ANALISI FINALE
- Un breve paragrafo (3-5 frasi) che analizza come e andata la sessione
- Commenta la qualita del processo decisionale e la partecipazione

Formato:
- Usa testo semplice, NO markdown
- Separa le sezioni con una riga vuota
- Tono informativo ma accessibile
- Lunghezza totale: 300-500 parole
"""


def collect_lost_at_sea_report_context(session) -> Dict[str, Any]:
    """
    Raccoglie ranking di gruppo e calcola error score per il report.
    """
    from .models import LostAtSeaRanking

    try:
        ranking = LostAtSeaRanking.objects.get(session=session)
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
    except LostAtSeaRanking.DoesNotExist:
        return {"has_ranking": False}


def build_lost_at_sea_pdf_sections(session, context: Dict[str, Any], styles: Dict[str, Any]) -> list:
    """
    Sezioni PDF task-specifiche per Lost at Sea: tabella ranking team vs expert + score.
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


def build_lost_at_sea_report_fallback_lines(data: Dict[str, Any]) -> list[str]:
    """
    Righe extra per il fallback report Lost at Sea (ranking + score).
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
