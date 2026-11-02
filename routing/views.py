from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from stations.index import warm

from .errors import PlanError
from .service import plan_route


class RoutePlanRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200)
    finish = serializers.CharField(max_length=200)


def error_response(code, message, status):
    return Response({"error": {"code": code, "message": message}}, status=status)


class HealthView(APIView):
    def get(self, request):
        warm()
        return Response({"status": "ok"})


class RoutePlanView(APIView):
    def post(self, request):
        serializer = RoutePlanRequestSerializer(data=request.data)
        if not serializer.is_valid():
            problems = "; ".join(f"{field}: {' '.join(map(str, errs))}" for field, errs in serializer.errors.items())
            return error_response("invalid_request", problems, 400)
        try:
            data = plan_route(**serializer.validated_data)
            data["map_url"] = request.build_absolute_uri(data["map_url"])
            return Response(data)
        except PlanError as exc:
            return error_response(exc.code, exc.message, exc.status)
