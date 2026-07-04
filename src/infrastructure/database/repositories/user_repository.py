"""SQLAlchemy implementation of UserRepository (domain interface)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.entities.user import User
from src.infrastructure.database.models import UserModel


def _to_entity(model: UserModel) -> User:
    return User(
        id=model.id,
        telegram_id=model.telegram_id,
        is_premium=model.is_premium,
        created_at=model.created_at,
    )


class SqlAlchemyUserRepository:
    """Implements domain.interfaces.user_repository.UserRepository.

    No explicit inheritance (Protocol is structural) — this class satisfies
    the interface by having matching method signatures, checked by mypy.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_entity(model) if model else None

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = select(UserModel).where(UserModel.telegram_id == telegram_id)
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return _to_entity(model) if model else None

    async def create(self, user: User) -> User:
        model = UserModel(
            id=user.id,
            telegram_id=user.telegram_id,
            is_premium=user.is_premium,
        )
        self._session.add(model)
        await self._session.flush()
        return user
