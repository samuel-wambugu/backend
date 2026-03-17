from django.contrib import admin
from .models import Incident, IncidentEvidence, IncidentComment, IncidentJournalEntry


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ['title', 'reporter', 'status', 'severity', 'is_anonymous', 'created_at']
    list_filter = ['status', 'severity', 'is_anonymous', 'is_public']
    search_fields = ['title', 'description', 'reporter__username']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(IncidentEvidence)
class IncidentEvidenceAdmin(admin.ModelAdmin):
    list_display = ['incident', 'evidence_type', 'uploaded_at']
    list_filter = ['evidence_type']
    search_fields = ['incident__title']


@admin.register(IncidentComment)
class IncidentCommentAdmin(admin.ModelAdmin):
    list_display = ['incident', 'user', 'is_staff_comment', 'created_at']
    list_filter = ['is_staff_comment']
    search_fields = ['incident__title', 'user__username', 'comment']


@admin.register(IncidentJournalEntry)
class IncidentJournalEntryAdmin(admin.ModelAdmin):
    list_display = ['incident', 'author', 'risk_level', 'created_at']
    list_filter = ['risk_level']
    search_fields = ['incident__title', 'author__username', 'note']
