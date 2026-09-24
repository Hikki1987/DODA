"""Request/response shapes for FR-AUTH-009's service actor endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CreateServiceActorRequest(BaseModel):
    name: str


class ServiceActorCredentialOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    revoked_at: datetime | None


class ServiceActorCredentialCreatedOut(ServiceActorCredentialOut):
    secret: str
    """Shown exactly once, at creation — never returned by any other
    endpoint (list/get). See ServiceActorCredential's own docstring."""


class AuthenticateServiceActorRequest(BaseModel):
    secret: str


class ServiceActorSessionOut(BaseModel):
    session_id: uuid.UUID
