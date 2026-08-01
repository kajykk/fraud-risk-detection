"""Kill Switch 状态机单元测试（ADR-013）。

覆盖：
- is_active：无 key / ACTIVE / 非 ACTIVE / Redis 故障降级
- activate / deactivate：写 Redis + pubsub 通知
- _fallback_from_env：4 级作用域映射
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest

from app.services.kill_switch import (
    KillSwitch,
    KillSwitchScope,
    KillSwitchState,
)


class FakeRedis:
    """内存版 Redis 替身（支持 set/get/publish）。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.published: list[tuple[str, str]] = []

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value

    async def publish(self, channel: str, message: str) -> None:
        self.published.append((channel, message))


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def ks() -> KillSwitch:
    return KillSwitch()


class TestIsActive:
    async def test_no_key_returns_false(
        self, ks: KillSwitch, fake_redis: FakeRedis
    ) -> None:
        with patch("app.db.redis.get_redis", return_value=fake_redis):
            assert (
                await ks.is_active(KillSwitchScope.L2_MODEL, "model_v1")
            ) is False

    async def test_active_state_returns_true(
        self, ks: KillSwitch, fake_redis: FakeRedis
    ) -> None:
        fake_redis.data["kill_switch:L2_MODEL:model_v1"] = json.dumps(
            {"state": KillSwitchState.ACTIVE.value}
        )
        with patch("app.db.redis.get_redis", return_value=fake_redis):
            assert (
                await ks.is_active(KillSwitchScope.L2_MODEL, "model_v1")
            ) is True

    async def test_cooldown_state_returns_false(
        self, ks: KillSwitch, fake_redis: FakeRedis
    ) -> None:
        fake_redis.data["kill_switch:L1_GLOBAL"] = json.dumps(
            {"state": KillSwitchState.COOLDOWN.value}
        )
        with patch("app.db.redis.get_redis", return_value=fake_redis):
            assert await ks.is_active(KillSwitchScope.L1_GLOBAL) is False

    async def test_redis_failure_falls_back_to_env(
        self, ks: KillSwitch, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def boom(*_args, **_kwargs):
            raise RuntimeError("redis down")

        fake = FakeRedis()
        fake.get = boom
        monkeypatch.setattr("app.config.settings.kill_switch_global", True)
        with patch("app.db.redis.get_redis", return_value=fake):
            # Redis 异常 → 读环境变量
            assert await ks.is_active(KillSwitchScope.L1_GLOBAL) is True


class TestActivateDeactivate:
    async def test_activate_writes_state_and_publishes(
        self, ks: KillSwitch, fake_redis: FakeRedis
    ) -> None:
        with patch("app.db.redis.get_redis", return_value=fake_redis):
            state = await ks.activate(
                scope=KillSwitchScope.L2_MODEL,
                target="model_v1",
                reason="PSI > 0.25",
                operator_id=uuid.uuid4(),
                duration_minutes=30,
            )
        assert state["state"] == KillSwitchState.ACTIVE.value
        stored = json.loads(fake_redis.data["kill_switch:L2_MODEL:model_v1"])
        assert stored["reason"] == "PSI > 0.25"
        assert stored["duration_minutes"] == 30
        assert fake_redis.published, "应发布 pubsub 通知"
        channel, message = fake_redis.published[0]
        assert channel.endswith("kill_switch")
        assert "activate" in message

    async def test_deactivate_enters_cooldown(
        self, ks: KillSwitch, fake_redis: FakeRedis
    ) -> None:
        with patch("app.db.redis.get_redis", return_value=fake_redis):
            ok = await ks.deactivate(
                scope=KillSwitchScope.L2_MODEL,
                target="model_v1",
                operator_id=uuid.uuid4(),
            )
        assert ok is True
        stored = json.loads(fake_redis.data["kill_switch:L2_MODEL:model_v1"])
        assert stored["state"] == KillSwitchState.COOLDOWN.value


class TestFallbackFromEnv:
    def test_l1_maps_to_global(self, ks: KillSwitch) -> None:
        assert ks._fallback_from_env(KillSwitchScope.L1_GLOBAL) is (
            __import__("app.config", fromlist=["settings"]).settings.kill_switch_global
        )

    def test_unknown_scope_false(self, ks: KillSwitch) -> None:
        assert ks._fallback_from_env(KillSwitchScope.L3_MODALITY) is False
