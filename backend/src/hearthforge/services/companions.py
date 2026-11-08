"""Phase 16b: pets and mounts. Adopt or unlock them, pick which one is out, name your pet.

Tokens are the `cosmetic_token` stacks in your bag and bank (weekly quests and the login calendar hand
them out). A pet's perk is folded into your perks by `domain.skills.with_pet`; a mount's speed is
applied by the room while you ride (MOVE_MODS)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hearthforge.config.loader import GameConfig
from hearthforge.core.errors import GameError, NotFound
from hearthforge.core.profanity import is_profane
from hearthforge.db.models import Avatar, Mount, Pet, Wallet
from hearthforge.services import inventory, ledger, stats
from hearthforge.services.progress import _village_numbers

TOKEN = "cosmetic_token"
MOUNT_BUY = "mount.buy"


async def tokens(session: AsyncSession, user_id: uuid.UUID) -> int:
    b = await inventory.bags(session, user_id, ("inventory", "bank"), lock=False)
    return sum(s.quantity for bag in b.values() for s in bag.slots.values() if s.item_key == TOKEN)


async def _spend_tokens(session: AsyncSession, user_id: uuid.UUID, n: int) -> None:
    b = await inventory.bags(session, user_id, ("inventory", "bank"))
    have = sum(s.quantity for bag in b.values() for s in bag.slots.values() if s.item_key == TOKEN)
    if have < n:
        raise GameError("no_tokens", f"You need {n} cosmetic tokens (you have {have}).")
    left = n
    for kind in ("inventory", "bank"):
        if left and kind in b:
            left -= await inventory.take_stack(session, b[kind], TOKEN, left)


async def view(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    cc = cfg.companions
    av = (await session.execute(select(Avatar.pet, Avatar.mount).where(Avatar.user_id == user_id))).one()
    pets = {
        r.pet_key: r for r in (await session.execute(select(Pet).where(Pet.user_id == user_id))).scalars()
    }
    mounts = set((await session.execute(select(Mount.mount_key).where(Mount.user_id == user_id))).scalars())
    want = {p.unlock.stat for p in cc.pets.values() if p.unlock}
    values = await stats.read(session, user_id, want) if want else {}
    th, _ = await _village_numbers(session, user_id)
    coins = (
        await session.execute(select(Wallet.coins).where(Wallet.user_id == user_id))
    ).scalar_one_or_none()
    out_pets = []
    for k, p in cc.pets.items():
        row = pets.get(k)
        entry: dict[str, Any] = {
            "key": k,
            "name": p.name,
            "desc": p.desc,
            "perks": p.perks,
            "owned": row is not None,
            "nickname": row.nickname if row else None,
            "active": av.pet == k,
            "cost": p.cost.model_dump() if p.cost else None,
        }
        if p.unlock:
            entry["unlock"] = {
                "hint": p.unlock.hint,
                "progress": min(values.get(p.unlock.stat, 0), p.unlock.target),
                "target": p.unlock.target,
            }
        out_pets.append(entry)
    out_mounts = [
        {
            "key": k,
            "name": m.name,
            "desc": m.desc,
            "speed": m.speed,
            "owned": k in mounts,
            "active": av.mount == k,
            "cost": m.cost.model_dump(),
            "town_hall": m.town_hall,
            "locked": th < m.town_hall,
        }
        for k, m in cc.mounts.items()
    ]
    return {
        "pets": out_pets,
        "mounts": out_mounts,
        "tokens": await tokens(session, user_id),
        "coins": coins or 0,
        "town_hall": th,
    }


async def adopt(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str) -> None:
    """Adopt a token pet, or take home one you've unlocked. It comes out with you straight away."""
    p = cfg.companions.pets.get(key)
    if p is None:
        raise NotFound("no_pet", "No such pet.")
    if await session.get(Pet, (user_id, key)) is not None:
        raise GameError("owned", "You already have this one.")
    if p.cost is not None:
        await _spend_tokens(session, user_id, p.cost.tokens)
        source = "tokens"
    else:
        assert p.unlock is not None
        have = (await stats.read(session, user_id, [p.unlock.stat])).get(p.unlock.stat, 0)
        if have < p.unlock.target:
            raise GameError("locked", f"{p.unlock.hint} first ({have}/{p.unlock.target}).")
        source = "unlock"
    session.add(Pet(user_id=user_id, pet_key=key, source=source))
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    av.pet = key
    await stats.bump(session, user_id, {"pet.adopted": 1})


async def set_pet(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str | None) -> None:
    if key is not None and await session.get(Pet, (user_id, key)) is None:
        raise NotFound("no_pet", "That pet isn't yours yet.")
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    av.pet = key


async def rename(
    session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str, name: str | None
) -> None:
    row = await session.get(Pet, (user_id, key))
    if row is None:
        raise NotFound("no_pet", "That pet isn't yours yet.")
    if name is not None:
        name = " ".join(name.split())
        nr = cfg.companions.names
        if not nr.min <= len(name) <= nr.max:
            raise GameError("bad_name", f"Names are {nr.min} to {nr.max} letters.")
        if is_profane(name, cfg.profanity):
            raise GameError("bad_name", "Let's pick a kinder name.")
    row.nickname = name or None


async def buy_mount(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str) -> None:
    m = cfg.companions.mounts.get(key)
    if m is None:
        raise NotFound("no_mount", "No such mount.")
    if await session.get(Mount, (user_id, key)) is not None:
        raise GameError("owned", "You already have this one.")
    th, _ = await _village_numbers(session, user_id)
    if th < m.town_hall:
        raise GameError("locked", f"Needs a level {m.town_hall} Town Hall.")
    if m.cost.tokens:
        await _spend_tokens(session, user_id, m.cost.tokens)
    if m.cost.coins:
        wallet = await ledger.lock_wallet(session, user_id)
        if wallet.coins < m.cost.coins:
            raise GameError("insufficient_coins", f"You need {m.cost.coins} coins.")
        await ledger.change_coins(session, wallet, -m.cost.coins, MOUNT_BUY, ref_type="mount", ref_id=key)
    session.add(Mount(user_id=user_id, mount_key=key, source="tokens" if m.cost.tokens else "coins"))
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    av.mount = key


async def set_mount(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID, key: str | None) -> None:
    if key is not None and await session.get(Mount, (user_id, key)) is None:
        raise NotFound("no_mount", "That mount isn't yours yet.")
    av = (
        await session.execute(select(Avatar).where(Avatar.user_id == user_id).with_for_update())
    ).scalar_one()
    av.mount = key


async def trophy_hall(session: AsyncSession, cfg: GameConfig, user_id: uuid.UUID) -> dict[str, Any]:
    """Your trophies and personal bests: boss kills, biggest catches, the big totals."""
    st = await stats.read(session, user_id)
    bosses = [
        {
            "key": bk,
            "name": b.name,
            "enemy": b.enemy,
            "trophy": b.loot.trophy,
            "trophy_name": cfg.items[b.loot.trophy].name,
            "icon": cfg.items[b.loot.trophy].icon,
            "kills": st.get(f"kill.{b.enemy}", 0),
        }
        for bk, b in cfg.bosses.bosses.items()
    ]
    fish = [
        {
            "key": fk,
            "name": sp.name,
            "rarity": sp.rarity,
            "caught": st.get(f"fish.{fk}", 0),
            "best_g": st.get(f"best.fish.{fk}", 0),
            "max_g": int(sp.kg[1] * 1000),
        }
        for fk, sp in cfg.fishing.species.items()
    ]
    totals = {
        k: st.get(k, 0)
        for k in (
            "kill.any",
            "kill.realm_boss",
            "delve.cleared",
            "wave.won",
            "fish.any",
            "fish.legendary",
            "forge.epic_plus",
            "help.given",
        )
    }
    return {"bosses": bosses, "fish": fish, "totals": totals}
