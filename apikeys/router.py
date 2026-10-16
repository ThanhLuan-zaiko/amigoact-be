"""HTTP layer for org API keys. No business logic here."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response

from apikeys.schemas import (
    ApiKeyCreateRequest,
    ApiKeyIssuedResponse,
    ApiKeyItem,
)
from apikeys.service import ApiKeyService
from core.dependencies import CurrentUser, get_api_key_service, get_current_user

router = APIRouter(tags=["apikeys"])


@router.post("/orgs/{org_id}/api-keys", response_model=ApiKeyIssuedResponse, status_code=201)
def create_key(
    org_id: UUID,
    body: ApiKeyCreateRequest,
    current: CurrentUser = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyIssuedResponse:
    """Mint a new org API key; the secret is shown once."""
    issued = service.create(
        org_id, current.id, body.name, body.scopes, body.ttl_days
    )
    return ApiKeyIssuedResponse(**vars(issued))


@router.get("/orgs/{org_id}/api-keys", response_model=list[ApiKeyItem])
def list_keys(
    org_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> list[ApiKeyItem]:
    """List every key of the org (managers only)."""
    return [ApiKeyItem(**vars(view)) for view in service.list_for_org(org_id, current.id)]


@router.post("/orgs/{org_id}/api-keys/{key_id}/revoke", status_code=204)
def revoke_key(
    org_id: UUID,
    key_id: UUID,
    current: CurrentUser = Depends(get_current_user),
    service: ApiKeyService = Depends(get_api_key_service),
) -> Response:
    """Revoke one key; it stops authenticating immediately."""
    service.revoke(org_id, current.id, key_id)
    return Response(status_code=204)
