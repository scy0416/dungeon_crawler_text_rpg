"""라우팅 전용 계층. 비즈니스 로직을 두지 않는다.

- 공개 경로: 요청을 그대로 해당 서비스로 전달
- 보호 경로: auth-service에 토큰 검증을 위임하고, 통과하면 X-User-Id 헤더를 붙여 전달
"""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response

from app.config import settings
from app.errors import error_response
from app.schemas import HealthResponse, VerifyResponse

SERVICE_NAME = "gateway"
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
# 외부에 공개하는 auth-service 경로 (/auth/verify 같은 내부용 경로는 노출하지 않음)
PUBLIC_AUTH_PATHS = {"register", "login"}
# 내부 서비스로 전달할 클라이언트 헤더. X-User-Id 위조를 막기 위해 허용 목록 방식으로 거른다.
FORWARDED_HEADERS = {"content-type", "accept"}

router = APIRouter()


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def upstream_unavailable() -> Response:
    return error_response(502, "UPSTREAM_UNAVAILABLE", "내부 서비스에 연결할 수 없습니다.")


async def forward(
    client: httpx.AsyncClient,
    request: Request,
    url: str,
    extra_headers: dict[str, str] | None = None,
) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARDED_HEADERS}
    headers.update(extra_headers or {})
    try:
        upstream = await client.request(
            request.method,
            url,
            params=request.query_params.multi_items(),
            content=await request.body(),
            headers=headers,
        )
    except httpx.RequestError:
        return upstream_unavailable()
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


async def authenticate(client: httpx.AsyncClient, request: Request) -> VerifyResponse | Response:
    """토큰 검증을 auth-service에 위임한다. 실패하면 클라이언트에 돌려줄 Response를 반환."""
    authorization = request.headers.get("authorization")
    if not authorization:
        return error_response(401, "MISSING_TOKEN", "Authorization 헤더가 필요합니다.")
    try:
        verified = await client.get(
            f"{settings.auth_service_url}/auth/verify",
            headers={"Authorization": authorization},
        )
    except httpx.RequestError:
        return upstream_unavailable()
    if verified.status_code != 200:
        return Response(
            content=verified.content,
            status_code=verified.status_code,
            media_type=verified.headers.get("content-type"),
        )
    return VerifyResponse.model_validate(verified.json())


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME)


@router.api_route("/auth/{path}", methods=METHODS)
async def auth_proxy(path: str, request: Request, client: HttpClient) -> Response:
    if path not in PUBLIC_AUTH_PATHS:
        return error_response(404, "NOT_FOUND", "존재하지 않는 경로입니다.")
    return await forward(client, request, f"{settings.auth_service_url}/auth/{path}")


@router.api_route("/characters", methods=METHODS)
@router.api_route("/characters/{path:path}", methods=METHODS)
async def character_proxy(request: Request, client: HttpClient, path: str = "") -> Response:
    auth = await authenticate(client, request)
    if isinstance(auth, Response):
        return auth
    url = f"{settings.character_service_url}/characters" + (f"/{path}" if path else "")
    return await forward(client, request, url, {"X-User-Id": str(auth.user_id)})


@router.api_route("/dungeons", methods=METHODS)
@router.api_route("/dungeons/{path:path}", methods=METHODS)
async def dungeon_proxy(request: Request, client: HttpClient, path: str = "") -> Response:
    auth = await authenticate(client, request)
    if isinstance(auth, Response):
        return auth
    url = f"{settings.dungeon_service_url}/dungeons" + (f"/{path}" if path else "")
    return await forward(client, request, url, {"X-User-Id": str(auth.user_id)})


@router.api_route("/quests", methods=METHODS)
@router.api_route("/quests/{path:path}", methods=METHODS)
async def quest_proxy(request: Request, client: HttpClient, path: str = "") -> Response:
    auth = await authenticate(client, request)
    if isinstance(auth, Response):
        return auth
    url = f"{settings.quest_service_url}/quests" + (f"/{path}" if path else "")
    return await forward(client, request, url, {"X-User-Id": str(auth.user_id)})


@router.api_route("/notifications", methods=METHODS)
@router.api_route("/notifications/{path:path}", methods=METHODS)
async def notification_proxy(request: Request, client: HttpClient, path: str = "") -> Response:
    auth = await authenticate(client, request)
    if isinstance(auth, Response):
        return auth
    url = f"{settings.notification_service_url}/notifications" + (f"/{path}" if path else "")
    return await forward(client, request, url, {"X-User-Id": str(auth.user_id)})
