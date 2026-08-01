"""FRD 用户/租户/API Key 种子脚本 — 创建默认租户、管理员账号与 API Key。

用法：
    python -m scripts.seed_users
"""
import asyncio
import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import get_session_factory
from app.models.tenant import ApiKey, Tenant
from app.models.user import User
from app.services.api_key_service import hash_api_key

DEFAULT_TENANT_CODE = "t0001"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "test12345"
DEFAULT_API_KEY = "frd_live_testkey00000000000000000000000000000000000000000000000000"


async def main() -> None:
    factory = get_session_factory()

    async with factory() as session:
        # 1. 租户
        result = await session.execute(
            select(Tenant).where(Tenant.code == DEFAULT_TENANT_CODE)
        )
        tenant = result.scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(
                name="默认租户",
                code=DEFAULT_TENANT_CODE,
                type="BANK",
                plan="STANDARD",
                status="ACTIVE",
                encryption_key_id=uuid.uuid4(),
                settings={},
                pci_scope="CDE",
            )
            session.add(tenant)
            await session.flush()
            print(f"created tenant: {tenant.code} ({tenant.id})")
        else:
            print(f"tenant exists: {tenant.code} ({tenant.id})")
        await session.commit()

    # 2. 用户（RLS：需 SET app.tenant_id）
    from app.db.session import session_scope

    async with session_scope(str(tenant.id)) as session:
        result = await session.execute(
            select(User).where(User.username == DEFAULT_ADMIN_USER)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id=tenant.id,
                username=DEFAULT_ADMIN_USER,
                full_name="系统管理员",
                password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
                roles=["TENANT_ADMIN"],
                status="ACTIVE",
            )
            session.add(user)
            print(f"created user: {DEFAULT_ADMIN_USER} / {DEFAULT_ADMIN_PASSWORD}")
        else:
            print(f"user exists: {DEFAULT_ADMIN_USER}")

        # 3. API Key
        key_hash = hash_api_key(DEFAULT_API_KEY)
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if result.scalar_one_or_none() is None:
            api_key = ApiKey(
                tenant_id=tenant.id,
                merchant_id=None,
                key_hash=key_hash,
                key_prefix=DEFAULT_API_KEY[:8],
                name="default-admin-key",
                scopes=[
                    "transaction:score",
                    "transaction:read",
                    "case:read",
                    "case:write",
                    "rule:read",
                    "rule:write",
                    "model:read",
                    "model:write",
                    "audit:read",
                    "pipl:read",
                    "webhook:write",
                ],
                ip_whitelist=[],
                status="ACTIVE",
            )
            session.add(api_key)
            print(f"created api key: {DEFAULT_API_KEY}")
        else:
            print("api key exists")


if __name__ == "__main__":
    asyncio.run(main())
