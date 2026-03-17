from django.urls import path
from .views import (
    AIFullAccessGrantView,
    AIOwnerAssistanceView,
    AIOwnerInboxMessageCreateView,
    AIOwnerInboxThreadDetailView,
    AIOwnerInboxThreadListView,
    AIOwnerInboxThreadManageView,
    AuditRecordListView,
    IncidentAnalysisView,
    IncidentTriageView,
    ProviderStatusView,
    SafetyTipsChatbotView,
)

urlpatterns = [
    path('providers/status/', ProviderStatusView.as_view(), name='ai-provider-status'),
    path('audits/', AuditRecordListView.as_view(), name='ai-audit-list'),
    path('chatbot/tips/', SafetyTipsChatbotView.as_view(), name='ai-chatbot-tips'),
    path('chatbot/contact-owner/', AIOwnerAssistanceView.as_view(), name='ai-contact-owner'),
    path('inbox/threads/', AIOwnerInboxThreadListView.as_view(), name='ai-owner-inbox-thread-list'),
    path('inbox/threads/<int:thread_id>/', AIOwnerInboxThreadDetailView.as_view(), name='ai-owner-inbox-thread-detail'),
    path('inbox/threads/<int:thread_id>/messages/', AIOwnerInboxMessageCreateView.as_view(), name='ai-owner-inbox-message-create'),
    path('inbox/threads/<int:thread_id>/manage/', AIOwnerInboxThreadManageView.as_view(), name='ai-owner-inbox-thread-manage'),
    path('permissions/grants/', AIFullAccessGrantView.as_view(), name='ai-full-access-grants'),
    path('incidents/analyze/', IncidentAnalysisView.as_view(), name='ai-analyze-incident'),
    path('incidents/triage/', IncidentTriageView.as_view(), name='ai-triage-incident'),
]
