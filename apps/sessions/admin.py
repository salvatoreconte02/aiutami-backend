from django.contrib import admin

from apps.sessions.models import (
    DiscussionEvent,
    Invitation,
    Session,
    SessionEvent,
    SessionParticipant,
)


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "context", "state", "host", "created_at")
    list_filter = ("state", "context")
    search_fields = ("title", "id")
    readonly_fields = ("id", "created_at", "started_at", "conclusion_at", "ended_at")


@admin.register(SessionParticipant)
class SessionParticipantAdmin(admin.ModelAdmin):
    list_display = ("session", "user", "role", "joined_at", "ready_to_conclude")
    list_filter = ("role", "ready_to_conclude")
    search_fields = ("session__id", "session__title", "user__username")


@admin.register(SessionEvent)
class SessionEventAdmin(admin.ModelAdmin):
    list_display = ("session", "type", "actor", "created_at")
    list_filter = ("type",)
    search_fields = ("session__id",)
    readonly_fields = ("created_at",)


@admin.register(DiscussionEvent)
class DiscussionEventAdmin(admin.ModelAdmin):
    list_display = (
        "session", "sequence_number", "event_type", "speaker",
        "content_short", "timestamp",
    )
    list_filter = ("event_type",)
    search_fields = ("session__id", "content")
    readonly_fields = (
        "session", "sequence_number", "timestamp", "event_type",
        "speaker", "content", "metadata",
    )
    ordering = ("session", "sequence_number")

    def content_short(self, obj):
        text = obj.content or ""
        return text[:80] + ("…" if len(text) > 80 else "")
    content_short.short_description = "Content"

    def has_add_permission(self, request):
        # Eventi creati solo dal sistema, mai dall'admin
        return False


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("session", "token", "created_at")
    search_fields = ("session__id", "token")
    readonly_fields = ("token", "created_at")
