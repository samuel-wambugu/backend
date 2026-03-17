from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model

from .models import AIFullAccessGrant
from .serializers import (
    AIAuditRecordSerializer,
    AIFullAccessGrantSerializer,
    AIFullAccessGrantUpsertSerializer,
    IncidentAnalysisRequestSerializer,
    OwnerInboxMessageCreateSerializer,
    OwnerInboxMessageSerializer,
    OwnerInboxThreadManageSerializer,
    OwnerInboxThreadDetailSerializer,
    OwnerInboxThreadSerializer,
    OwnerAssistanceRequestSerializer,
    SafetyTipsChatRequestSerializer,
    IncidentTriageRequestSerializer,
)
from .services import AIGatewayService


class ProviderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = AIGatewayService()
        return Response(service.provider_status())


class IncidentAnalysisView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = IncidentAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = AIGatewayService()
        if not serializer.validated_data.get('dry_run', True) and not service.has_owner_approved_full_access(request.user):
            return Response(
                {'detail': 'Owner approval required for full AI functionality.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        result = service.analyze_incident(serializer.validated_data, user=request.user)
        return Response(result, status=status.HTTP_200_OK)


class IncidentTriageView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = IncidentTriageRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = AIGatewayService()
        if not serializer.validated_data.get('dry_run', True) and not service.has_owner_approved_full_access(request.user):
            return Response(
                {'detail': 'Owner approval required for full AI functionality.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        incident = service.get_incident_for_user(request.user, serializer.validated_data['incident_id'])
        result = service.triage_incident(
            incident,
            dry_run=serializer.validated_data.get('dry_run', True),
            provider_name=serializer.validated_data.get('provider', ''),
            sensor_limit=serializer.validated_data['sensor_limit'],
            user=request.user,
        )
        return Response(result, status=status.HTTP_200_OK)


class AuditRecordListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = AIGatewayService()
        serializer = AIAuditRecordSerializer(service.get_recent_audits_for_user(request.user), many=True)
        return Response(serializer.data)


class SafetyTipsChatbotView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SafetyTipsChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = AIGatewayService()
        result = service.chatbot_safety_tips(
            serializer.validated_data['message'],
            location=serializer.validated_data.get('location'),
            language=serializer.validated_data.get('language', 'en'),
        )
        return Response(result, status=status.HTTP_200_OK)


class AIOwnerAssistanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = OwnerAssistanceRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = AIGatewayService()
        result = service.contact_owner_assistance(
            request.user,
            serializer.validated_data['message'],
            conversation_summary=serializer.validated_data.get('conversation_summary', ''),
        )
        return Response(result, status=status.HTTP_200_OK)


class AIOwnerInboxThreadListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = AIGatewayService()
        queryset = service.get_owner_inbox_threads_for_user(request.user)
        serializer = OwnerInboxThreadSerializer(
            queryset,
            many=True,
            context={
                'request': request,
                'is_owner_user': service.is_owner_user(request.user),
            },
        )
        return Response(serializer.data)


class AIOwnerInboxThreadDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, thread_id):
        service = AIGatewayService()
        thread = service.get_owner_inbox_thread_for_user(request.user, thread_id)
        service.mark_owner_inbox_thread_read(thread, request.user)
        serializer = OwnerInboxThreadDetailSerializer(
            thread,
            context={
                'request': request,
                'is_owner_user': service.is_owner_user(request.user),
                'available_owner_options': service.get_owner_users(),
            },
        )
        return Response(serializer.data)


class AIOwnerInboxThreadManageView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, thread_id):
        serializer = OwnerInboxThreadManageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = AIGatewayService()
        thread = service.get_owner_inbox_thread_for_user(request.user, thread_id)
        thread = service.update_owner_inbox_thread(
            thread,
            request.user,
            status=serializer.validated_data.get('status'),
            assigned_owner_user_id=serializer.validated_data.get('assigned_owner_user_id'),
            assigned_owner_provided='assigned_owner_user_id' in request.data,
        )
        response_serializer = OwnerInboxThreadDetailSerializer(
            thread,
            context={
                'request': request,
                'is_owner_user': service.is_owner_user(request.user),
                'available_owner_options': service.get_owner_users(),
            },
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class AIOwnerInboxMessageCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, thread_id):
        serializer = OwnerInboxMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        service = AIGatewayService()
        thread = service.get_owner_inbox_thread_for_user(request.user, thread_id)
        message = service.create_owner_inbox_message(
            thread,
            request.user,
            serializer.validated_data['body'],
        )
        response_serializer = OwnerInboxMessageSerializer(message)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class AIFullAccessGrantView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        service = AIGatewayService()
        if service.is_owner_user(request.user):
            queryset = AIFullAccessGrant.objects.select_related('owner', 'grantee').filter(owner=request.user)
        else:
            queryset = AIFullAccessGrant.objects.select_related('owner', 'grantee').filter(grantee=request.user, is_active=True)
        serializer = AIFullAccessGrantSerializer(queryset.order_by('-updated_at'), many=True)
        return Response(serializer.data)

    def post(self, request):
        service = AIGatewayService()
        if not service.is_owner_user(request.user):
            return Response({'detail': 'Only owner accounts can grant AI full access.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = AIFullAccessGrantUpsertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_model = get_user_model()
        try:
            grantee = user_model.objects.get(id=serializer.validated_data['grantee_user_id'])
        except user_model.DoesNotExist:
            return Response({'detail': 'Target user not found.'}, status=status.HTTP_404_NOT_FOUND)

        grant, _ = AIFullAccessGrant.objects.get_or_create(owner=request.user, grantee=grantee)
        grant.can_use_all_features = serializer.validated_data.get('can_use_all_features', True)
        grant.is_active = serializer.validated_data.get('is_active', True)
        grant.note = serializer.validated_data.get('note', '')
        grant.save(update_fields=['can_use_all_features', 'is_active', 'note', 'updated_at'])

        response_serializer = AIFullAccessGrantSerializer(grant)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
