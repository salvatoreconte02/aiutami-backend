from django.apps import AppConfig


class TasksConfig(AppConfig):
    """
    App contenitore per i plugin di task supportati (murder_mystery,
    nasa_moon_survival, generic).

    Ogni task è un sottopacchetto di apps.tasks che registra la propria
    classe TaskDefinition nel registry al momento dell'import.

    Il core (sessions, moderation, reports, turns, asr, tts, webrtc) non
    importa mai direttamente da apps.tasks.<specifico>: dialoga solo con
    apps.tasks.registry.get_task(key).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.tasks"
    label = "tasks"

    def ready(self) -> None:
        # I sottopacchetti dei task verranno importati qui nei prossimi step.
        # In Step 0 il registry è vuoto: nessun task registrato, il core non
        # lo usa ancora, quindi nessun comportamento cambia.
        pass
