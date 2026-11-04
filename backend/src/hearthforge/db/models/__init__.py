"""All ORM models. Importing this package registers every table on Base.metadata."""

from hearthforge.db.models.accounts import (
    Avatar,
    AvatarLocation,
    RecoveryCode,
    Session,
    User,
    UserRole,
    UserSettings,
)
from hearthforge.db.models.crafting import CraftJob, Discovery, DiscoveryKind, JobStatus
from hearthforge.db.models.economy import LedgerAsset, Transaction, Wallet
from hearthforge.db.models.infra import (
    AdminAuditLog,
    ConfigVersion,
    EventStatus,
    Notification,
    ScheduledEvent,
)
from hearthforge.db.models.items import (
    Container,
    ContainerKind,
    ContainerSlot,
    ItemDef,
    ItemInstance,
    ItemOrigin,
    Rarity,
)
from hearthforge.db.models.realm import Realm, RealmMember, RealmRole, RealmVisibility
from hearthforge.db.models.village import BuildingState, Presence, Resource, Village, VillageBuilding
from hearthforge.db.models.world import DeathDrop, NodeHarvest

__all__ = [
    "AdminAuditLog",
    "Avatar",
    "AvatarLocation",
    "BuildingState",
    "ConfigVersion",
    "CraftJob",
    "DeathDrop",
    "Discovery",
    "DiscoveryKind",
    "Container",
    "ContainerKind",
    "ContainerSlot",
    "EventStatus",
    "ItemDef",
    "ItemInstance",
    "ItemOrigin",
    "JobStatus",
    "LedgerAsset",
    "NodeHarvest",
    "Notification",
    "Presence",
    "Rarity",
    "Realm",
    "RealmMember",
    "RealmRole",
    "RealmVisibility",
    "RecoveryCode",
    "Resource",
    "ScheduledEvent",
    "Session",
    "Transaction",
    "User",
    "UserRole",
    "UserSettings",
    "Village",
    "VillageBuilding",
    "Wallet",
]
