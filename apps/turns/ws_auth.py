# apps/turns/ws_auth.py

from urllib.parse import parse_qs

from channels.db import database_sync_to_async


class JwtAuthMiddleware:
    """
    Middleware ASGI che autentica WebSocket via ?token=<JWT>.
    Tutti gli import Django/DRF vengono fatti dentro __call__,
    e le operazioni che toccano il DB passano tramite database_sync_to_async.
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        # Import qui, NON a livello di modulo
        from django.contrib.auth.models import AnonymousUser
        from rest_framework_simplejwt.tokens import UntypedToken
        from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
        from rest_framework_simplejwt.authentication import JWTAuthentication

        # Estrae token dalla querystring
        query_string = scope.get("query_string", b"").decode()
        params = parse_qs(query_string)
        token_list = params.get("token", [])

        user = AnonymousUser()

        if token_list:
            raw_token = token_list[0]
            try:
                jwt_auth = JWTAuthentication()

                # Verifica minima del token (solo parsing/validazione JWT)
                UntypedToken(raw_token)

                # Decodifica del token (sempre sync, ma non usa DB)
                validated = jwt_auth.get_validated_token(raw_token)

                # QUI si tocca il DB → va wrappato
                user = await database_sync_to_async(jwt_auth.get_user)(validated)
            except (InvalidToken, TokenError):
                user = AnonymousUser()
            except Exception:
                # qualsiasi altro errore → utente anonimo
                user = AnonymousUser()

        scope["user"] = user
        return await self.inner(scope, receive, send)


def JwtAuthMiddlewareStack(inner):
    return JwtAuthMiddleware(inner)