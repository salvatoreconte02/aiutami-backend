"""
Contratto astratto per un task plugin di AIutami.

Un TaskDefinition descrive tutto ciò che è specifico di un task (Murder Mystery,
NASA Moon Survival, discussione generica...). Il core del backend non conosce
i task specifici: interagisce con essi solo attraverso questa interfaccia.

In Step 0 il contratto è minimale (solo `key` e `display_name`) perché serve
unicamente a far girare il registry. I metodi veri (prompt building, intro,
submission, report, ...) verranno aggiunti negli step successivi del refactor,
uno per volta, man mano che il core smette di avere logica MM-specifica.

Vedi docs/plans/2026-04-08-task-pluggable-architecture.md per il piano completo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class TaskDefinition(ABC):
    """
    Classe astratta che ogni task plugin deve estendere.

    Ogni sottoclasse concreta (es. MurderMysteryTask) fornisce:
      - `key`: stringa identificatrice univoca, usata come valore di
        Session.context e come chiave nel registry (es. "murder_mystery")
      - `display_name`: etichetta leggibile per UI e log (es. "Murder Mystery")
    """

    @property
    @abstractmethod
    def key(self) -> str:
        """Chiave univoca del task nel registry."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Nome leggibile del task."""

    # --- Capienza della sessione ---
    # Step 2: questi campi servono al core (Session.clean, serializer validate)
    # per validare min_size/max_size di una sessione senza hardcodare Murder
    # Mystery. Task a numero fisso di partecipanti (es. MM 3/3) dichiarano
    # `fixed_size=True` e usano min_participants == max_participants.

    @property
    @abstractmethod
    def min_participants(self) -> int:
        """Numero minimo di partecipanti ammesso dal task."""

    @property
    @abstractmethod
    def max_participants(self) -> int:
        """Numero massimo di partecipanti ammesso dal task."""

    @property
    @abstractmethod
    def fixed_size(self) -> bool:
        """
        True se il task richiede esattamente `min_participants` partecipanti
        (es. Murder Mystery: sempre 3). In quel caso min_size e max_size di
        una Session devono coincidere con min_participants/max_participants.
        False se il task accetta un range (es. discussione generica).
        """

    # --- Prompt building per il moderatore LLM ---
    # Step 3: il core moderation mantiene uno scheletro di system prompt
    # task-agnostic (tono, cooldown, output JSON, criteri generici) e delega
    # al task un blocco di testo con lo scenario e un dict `scenario` da
    # inserire nel payload LLM. I default sono pensati per GENERIC: blocco
    # vuoto + payload vuoto. I task concreti (MM, NASA) li sovrascrivono.

    def task_context_block(self, mode: str, language: str = "Italian") -> str:
        """
        Ritorna il blocco di testo task-specifico da iniettare nello scheletro
        del system prompt del moderatore.

        `mode` è uno di: "normal", "forced_conclusion".
        `language` controlla la lingua del blocco ("Italian" | "English" | ...).
        Default "Italian" per backward-compat. I task concreti che vogliono
        supportare l'inglese forniscono entrambe le varianti.
        Stringa vuota = task completamente generico (nessuno scenario specifico).
        """
        return ""

    def llm_scenario_payload(
        self, mode: str = "normal", language: str = "Italian"
    ) -> Dict[str, Any]:
        """
        Ritorna il dict da inserire come `scenario` nel payload JSON inviato
        all'LLM. I task concreti mettono qui tipo, obiettivo e info di contesto
        che l'LLM può consultare. Stringhe localizzate via `language`.
        Default vuoto = GENERIC.
        """
        return {}

    def enforces_ground_rules(self) -> bool:
        """
        True se il task usa le ground rules di Hall & Watson (1970) e vuole
        che il moderatore AI le faccia rispettare a runtime tramite reason
        `ground_rule_violation`. Default False (task senza ground rules).
        """
        return False

    def intro_message_tail(self) -> str:
        """
        Frase finale task-specifica iniettata nel template intro prima del
        "Buona discussione!". I task concreti spiegano qui come concludere
        (es. MM: "Quando avrete capito chi è il colpevole..."). Default
        generico per task senza condizione di terminazione specifica.
        """
        return "Quando sarete pronti a concludere, premete 'Pronto alla conclusione'."

    def ready_to_conclude_messages(self) -> Dict[str, list[str]]:
        """
        Template dei messaggi pronunciati dal moderatore quando un partecipante
        preme "Pronto alla conclusione". Tre varianti:

          - "normal": un partecipante è pronto, ne mancano altri.
          - "last_one": manca un solo partecipante.
          - "all_ready": tutti pronti, si transiziona a CONCLUSION.

        I template "normal" e "last_one" devono contenere il placeholder
        `{nome}`; "all_ready" no. Default = testi task-agnostici (nessun
        riferimento a colpevole/ranking/ecc.). I task concreti possono
        sovrascrivere per aggiungere terminologia di scenario.
        """
        return {
            "normal": [
                "{nome} è pronto a concludere. Quando anche tu sei pronto, premi 'Pronto alla conclusione' per terminare la sessione.",
                "{nome} ha indicato di essere pronto alla conclusione. Premi anche tu il pulsante quando vuoi chiudere la discussione.",
                "{nome} si è dichiarato pronto a concludere. Se sei pronto anche tu, premi 'Pronto alla conclusione'.",
            ],
            "last_one": [
                "{nome} è pronto a concludere. Manca solo un partecipante per avviare la fase finale.",
                "{nome} si è dichiarato pronto. Manca solo una persona: quando sei pronto, premi 'Pronto alla conclusione'.",
                "{nome} è pronto. Manca solo un voto per concludere la sessione.",
            ],
            "all_ready": [
                "Tutti i partecipanti sono pronti. Possiamo avviarci alla fase di conclusione.",
                "Tutti hanno deciso. Possiamo avviarci alla fase di conclusione.",
                "Siete tutti pronti. Possiamo avviarci alla fase di conclusione.",
            ],
        }

    def fallback_forced_conclusion_body(
        self,
        summary: str,
        conclusion_reason: str,
        language: str = "Italian",
    ) -> str:
        """
        Testo pre-scritto usato se la chiamata LLM per forced_conclusion
        fallisce. Va in TTS ai partecipanti — quindi localizzato.
        I task concreti possono personalizzarlo con istruzioni specifiche
        (es. "selezionate il colpevole"). Default generico: riepilogo +
        ringraziamento.
        """
        if language == "English":
            if conclusion_reason == "timer_expired":
                intro = "Time is up."
            elif conclusion_reason == "all_participants_ready":
                intro = "You've decided to conclude the session."
            else:
                intro = "In conclusion:"
            return (
                f"{intro} "
                f"Here is a brief recap of your discussion: {summary}. "
                f"Thank you for using AIutami for your session!"
            )
        if conclusion_reason == "timer_expired":
            intro = "Il tempo a disposizione è terminato."
        elif conclusion_reason == "all_participants_ready":
            intro = "Avete deciso di concludere la sessione."
        else:
            intro = "In conclusione:"
        return (
            f"{intro} "
            f"Ecco un breve riepilogo della vostra discussione: {summary}. "
            f"Grazie per aver usato AIutami per la vostra sessione!"
        )

    # --- Report PDF e LLM ---
    # Step 5: il core dei report (apps/reports/) diventa uno scheletro
    # task-agnostic. I task concreti forniscono prompt LLM, titolo PDF,
    # dati task-specifici e sezioni PDF extra.

    def build_report_llm_prompt(self, language: str = "Italian") -> str:
        """
        System prompt inviato all'LLM per generare il testo narrativo del
        report. Il PDF e' user-facing (scaricato dai partecipanti) quindi
        l'output deve essere nella loro lingua. Le istruzioni al modello
        sono in inglese per coerenza con il moderator system prompt; la
        lingua di output e' iniettata via {LANGUAGE} placeholder.
        I task concreti descrivono il proprio scenario e le sezioni desiderate.
        """
        return (
            "You are an analyst of moderated group discussion sessions on AIutami.\n\n"
            f"Generate a text report in {language} for a discussion session.\n\n"
            "The report must include:\n"
            "- PARTICIPATION STATISTICS: each participant's `speaking_time_s` "
            "(seconds spoken) and `percentage` of the group's total speaking "
            "time. Mention the total `duration_minutes` for context.\n"
            "- MODERATOR INTERVENTIONS: if `interventions_log` is present, "
            "include total number of AI interventions, breakdown by reason "
            "(e.g. '3 off_topic, 2 monopolization'), and for each intervention "
            "the timestamp, reason and the speaker who had just spoken\n"
            "- DISCUSSION SUMMARY: based on final_summary\n"
            "- FINAL ANALYSIS: brief analysis of how the session went\n\n"
            "Format: plain text, NO markdown, sections separated by blank lines.\n"
            "Length: 200-400 words.\n\n"
            f"IMPORTANT: write the entire report in {language}."
        )

    def report_title(self) -> str:
        """Titolo del PDF del report. Default: 'REPORT SESSIONE'."""
        return "REPORT SESSIONE"

    def collect_report_context(self, session) -> Dict[str, Any]:
        """
        Raccoglie dal DB i dati task-specifici per il report (es. voti,
        risultato). Ritorna un dict che viene mergiato nei dati generici
        (titolo, durata, partecipanti, summary) e passato sia all'LLM
        che al PDF builder. Default vuoto = nessun dato task-specifico.
        """
        return {}

    def build_report_pdf_sections(self, session, context: Dict[str, Any], styles: Dict[str, Any]) -> list:
        """
        Ritorna una lista di elementi ReportLab (Paragraph, Spacer, Table...)
        da appendere alla story del PDF dopo le sezioni generiche.
        `context` è il dict ritornato da collect_report_context().
        `styles` contiene gli stili ReportLab ('section', 'body') usati dal core.
        Default vuoto = nessuna sezione extra.
        """
        return []

    def build_report_fallback(self, data: Dict[str, Any]) -> list[str]:
        """
        Righe extra da appendere al report di fallback (quando LLM non
        disponibile). Default vuoto.
        """
        return []

    # --- Submission (voto, ranking, ecc.) ---
    # Step 6: il core usa questi metodi per sapere se tutti i partecipanti
    # hanno completato la loro submission task-specifica e per serializzare
    # il riepilogo delle submission nella risposta API.

    def all_submissions_received(self, session) -> bool:
        """
        True se tutti i partecipanti hanno completato la submission
        task-specifica (es. voto colpevole per MM, ranking per NASA).
        Default True = task senza submission.
        """
        return True

    def submission_summary(self, session) -> Any:
        """
        Riepilogo delle submission per il SessionDetail API.
        Per MM: dict con results/guilty/success_rate.
        Default None = nessuna submission per questo task.
        """
        return None

    def __repr__(self) -> str:
        return f"<TaskDefinition key={self.key!r}>"
