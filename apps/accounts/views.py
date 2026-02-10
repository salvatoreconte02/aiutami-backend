from rest_framework import generics, permissions
from rest_framework.response import Response
from django.contrib.auth.models import User
from .serializers import UserSerializer, SignupSerializer

class MeView(generics.RetrieveAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

class SignupView(generics.CreateAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = SignupSerializer

    def create(self, request, *args, **kwargs):
        # evita duplicati basici
        if User.objects.filter(username=request.data.get("username")).exists():
            return Response({"detail": "Username già in uso."}, status=400)
        if request.data.get("email") and User.objects.filter(email=request.data["email"]).exists():
            return Response({"detail": "Email già in uso."}, status=400)
        return super().create(request, *args, **kwargs)
