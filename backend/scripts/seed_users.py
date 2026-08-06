"""FRD 用户/租户/API Key 种子脚本 — 创建默认租户、管理员账号与 API Key。

用法：
    set FRD_ADMIN_PASSWORD=<强口令>
    python -m scripts.seed_users

凭据一律通过环境变量注入，禁止硬编码默认口令：
    FRD_ADMIN_USER     管理员用户名（默认 admin）
    FRD_ADMIN_PASSWORD 管理员密码（必填，长度≥12）
    FRD_ADMIN_API_KEY  API Key（可选，长度≥32，未设置则生成随机并打印一次）
"""
import asyncio
import os
import secrets
import uuid

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import get_session_factory
from app.models.tenant import ApiKey, Tenant
from app.models.user import User
from app.services.api_key_service import hash_api_key

DEFAULT_TENANT_CODE = "t0001"


def _env_password() -> str:
    """从环境变量读取管理员密码（默认可空，空则报错退出）。"""
    value = os.getenv("FRD_ADMIN_PASSWORD", "").strip()
    if len(value) < 12:
        raise SystemExit(
            "FRD_ADMIN_PASSWORD 未设置或长度不足 12 位；"
            "请通过环境变量注入强口令后重试，禁止使用默认口令。"
        )
    return value


async def main() -> None:
    factory = get_session_factory()
    admin_user = os.getenv("FRD_ADMIN_USER", "admin").strip() or "admin"
    admin_password = _env_password()
    admin_api_key = os.getenv("FRD_ADMIN_API_KEY", "").strip()

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

    created = False
    async with session_scope(str(tenant.id)) as session:
        result = await session.execute(
            select(User).where(User.username == admin_user)
        )
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                tenant_id=tenant.id,
                username=admin_user,
                full_name="系统管理员",
                password_hash=hash_password(admin_password),
                roles=["TENANT_ADMIN"],
                status="ACTIVE",
            )
            session.add(user)
            print(f"created user: {admin_user}")
            created = True
        else:
            print(f"user exists: {admin_user}")

        # 3. API Key：未显式配置时生成随机 key（仅打印一次）
        if len(admin_api_key) < 32:
            admin_api_key = f"frd_live_{secrets.token_hex(32)}"
        key_hash = hash_api_key(admin_api_key)
        result = await session.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash)
        )
        if result.scalar_one_or_none() is None:
            api_key = ApiKey(
                tenant_id=tenant.id,
                merchant_id=None,
                key_hash=key_hash,
                key_prefix=admin_api_key[:8],
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
            print(f"created api key: {admin_api_key}")
        else:
            print("api key exists")

    if created:
        print("\n完成。请在安全通道中向管理员下发初始口令。")


if __name__ == "__main__":
    asyncio.run(main())
