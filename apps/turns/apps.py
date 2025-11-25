from django.apps import AppConfig


class TurnsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    # percorso completo dell'app
    name = "apps.turns"
    # etichetta breve usata da Django (e dai test)
    label = "turns"