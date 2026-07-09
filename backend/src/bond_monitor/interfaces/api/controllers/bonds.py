"""Bonds and favorites API controllers."""

from __future__ import annotations

from litestar import Controller, delete, get, post, put
from litestar.di import Provide
from litestar.exceptions import NotFoundException
from litestar.status_codes import HTTP_201_CREATED, HTTP_204_NO_CONTENT
from sqlalchemy.ext.asyncio import AsyncSession

from bond_monitor.application.bonds.bond_service import BondService
from bond_monitor.infrastructure.persistence.favorites_repository import FavoritesRepository
from bond_monitor.interfaces.config import Settings
from bond_monitor.interfaces.schemas.api import BondsListResponse
from bond_monitor.interfaces.schemas.serializers import bond_to_response


def provide_bond_service(settings: Settings) -> BondService:
    return BondService(
        key_rate=settings.key_rate,
        tax_rate=settings.tax_rate_fraction,
        tinkoff_token=settings.tinkoff_token,
        max_days=settings.max_days,
        min_volume_rub=settings.min_volume_rub,
    )


async def provide_favorites_repo(db_session: AsyncSession) -> FavoritesRepository:
    return FavoritesRepository(db_session)


class BondsController(Controller):
    path = "/api/v1/bonds"
    dependencies = {
        "bond_service": Provide(provide_bond_service),
        "favorites_repo": Provide(provide_favorites_repo),
    }

    @get("/")
    async def list_bonds(
        self,
        bond_service: BondService,
        favorites_repo: FavoritesRepository,
        filter_by: str = "effective",
    ) -> BondsListResponse:
        result = bond_service.load_screener_bonds(filter_by=filter_by)
        favorite_isins = set(await favorites_repo.list_isins())
        bonds = []
        for b in result.bonds:
            b.is_favorite = b.isin in favorite_isins
            bonds.append(bond_to_response(b))
        return BondsListResponse(bonds=bonds, source=result.source, count=len(bonds))

    @get("/by-isins")
    async def bonds_by_isins(
        self,
        bond_service: BondService,
        favorites_repo: FavoritesRepository,
        isins: str = "",
    ) -> BondsListResponse:
        isin_list = [part.strip() for part in isins.split(",") if part.strip()]
        bonds = bond_service.load_by_isins(isin_list)
        favorite_isins = set(await favorites_repo.list_isins())
        for bond in bonds:
            bond.is_favorite = bond.isin in favorite_isins
        return BondsListResponse(
            bonds=[bond_to_response(b) for b in bonds],
            source="isins",
            count=len(bonds),
        )

    @get("/{secid:str}")
    async def get_bond(
        self,
        secid: str,
        bond_service: BondService,
        favorites_repo: FavoritesRepository,
    ) -> dict:
        bond = bond_service.load_by_secid(secid)
        if bond is None and secid:
            loaded = bond_service.load_by_isins([secid])
            bond = loaded[0] if loaded else None
        if bond is None:
            raise NotFoundException(detail=f"Bond {secid} not found")
        favorite_isins = set(await favorites_repo.list_isins())
        bond.is_favorite = bond.isin in favorite_isins
        coupons = bond_service.get_coupon_schedule(bond.figi) if bond.figi else []
        return {"bond": bond_to_response(bond), "coupons": coupons}

    @post("/refresh")
    async def refresh_bonds(self) -> dict[str, str]:
        from bond_monitor.application.bonds.bond_service import invalidate_all_bond_caches
        from bond_monitor.infrastructure.moex.client import invalidate_moex_cache
        from bond_monitor.infrastructure.tinvest.read_client import invalidate_tinvest_bonds_cache

        invalidate_moex_cache()
        invalidate_tinvest_bonds_cache()
        invalidate_all_bond_caches()
        return {"status": "ok"}


class FavoritesController(Controller):
    path = "/api/v1/favorites"
    dependencies = {
        "favorites_repo": Provide(provide_favorites_repo),
        "bond_service": Provide(provide_bond_service),
    }

    @get("/")
    async def list_favorites(
        self,
        favorites_repo: FavoritesRepository,
        bond_service: BondService,
    ) -> BondsListResponse:
        isins = await favorites_repo.list_isins()
        bonds = bond_service.load_by_isins(isins)
        for b in bonds:
            b.is_favorite = True
        return BondsListResponse(
            bonds=[bond_to_response(b) for b in bonds],
            source="favorites",
            count=len(bonds),
        )

    @put("/{isin:str}", status_code=HTTP_201_CREATED)
    async def add_favorite(self, isin: str, favorites_repo: FavoritesRepository) -> dict[str, str]:
        await favorites_repo.add(isin)
        return {"isin": isin, "status": "added"}

    @delete("/{isin:str}", status_code=HTTP_204_NO_CONTENT)
    async def remove_favorite(self, isin: str, favorites_repo: FavoritesRepository) -> None:
        await favorites_repo.remove(isin)


class RatingsController(Controller):
    path = "/api/v1/ratings"
    dependencies = {"bond_service": Provide(provide_bond_service)}

    @post("/refresh")
    async def refresh_ratings(self, bond_service: BondService) -> dict[str, int]:
        count = bond_service.refresh_ratings()
        return {"count": count}
