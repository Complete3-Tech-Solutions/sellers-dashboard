from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterTenantIn(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=128)
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)


class RegisterTenantOut(BaseModel):
    tenant_id: uuid.UUID
    user_id: uuid.UUID


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    totp: str | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    tenant_id: uuid.UUID


class LoginOut(BaseModel):
    user: UserOut


class TotpEnrollOut(BaseModel):
    secret: str
    provisioning_uri: str


class TotpVerifyIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)
