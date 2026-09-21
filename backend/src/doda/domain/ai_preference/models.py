"""Provider/model selection persistence — the multi-provider instruction's
priority chain: conversation pin (`doda.domain.conversation.models.
Conversation.pinned_provider/pinned_model`) > user default (here) >
workspace default (here) > system default
(`doda.config.Settings.ai_default_provider` + `ai_model_*`). Resolution
itself lives in `doda.application.ai_preference_service`; this module is
just the two storage rows.

`PreferenceProvider` duplicates `doda.ai.types.Provider`'s three values
for the same layering reason `UsageProvider`
(`doda.domain.ai_usage.models`) duplicates it — a Domain module never
reaches up into the AI layer (6.1/6.2).
"""

import enum
import uuid

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from doda.domain.base import Base, CreatedAtMixin


class PreferenceProvider(enum.StrEnum):
    OPENAI = "OPENAI"
    GEMINI = "GEMINI"
    CLAUDE = "CLAUDE"


class UserAIPreference(CreatedAtMixin, Base):
    """One row per (customer, user) — a user's default provider/model for
    NEW conversations in that customer's workspaces. Scoped by customer
    (not global to the user) because the same person can belong to
    multiple customers (FR-WKS) with no reason to share one AI
    preference across them. `model=None` means "use that provider's own
    configured default model" (`doda.config.Settings.ai_model_*`)."""

    __tablename__ = "user_ai_preferences"

    customer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    provider: Mapped[PreferenceProvider] = mapped_column(
        SAEnum(PreferenceProvider, name="ai_preference_provider_user", native_enum=False, length=16)
    )
    model: Mapped[str | None] = mapped_column(String(64), default=None)


class WorkspaceAIPreference(Base):
    """One row per workspace — the workspace's default provider/model for
    members who have no personal `UserAIPreference` of their own. Set by
    a workspace_admin (`authorize_manage_workspace_ai_preference`),
    mirroring the authority level of every other workspace-wide setting
    in this codebase (kill switch, archive, member management)."""

    __tablename__ = "workspace_ai_preferences"

    workspace_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(index=True)
    provider: Mapped[PreferenceProvider] = mapped_column(
        SAEnum(PreferenceProvider, name="ai_preference_provider_workspace", native_enum=False, length=16)
    )
    model: Mapped[str | None] = mapped_column(String(64), default=None)
