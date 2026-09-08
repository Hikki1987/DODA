import uuid

from pydantic import BaseModel

from doda.domain.security.roles import CustomerRole


class InviteCustomerMemberRequest(BaseModel):
    user_id: uuid.UUID
    role: CustomerRole


class ChangeCustomerMemberRoleRequest(BaseModel):
    role: CustomerRole


class CustomerMembershipOut(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    user_id: uuid.UUID
    role: str
