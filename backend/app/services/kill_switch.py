"""KillSwitch：4 级作用域分级（D03 V1.1 §4.8 / ADR-013）。

| 级别 | 作用域 | 触发条件 | 兜底策略 |
|---|---|---|---|
| L1 全局 | 全系统 | 重大事故/安全事件 | 启发式规则 |
| L2 模型级 | 单一 ML 模型 | AUC 跌破/PSI>0.25 | 备用模型 |
| L3 模态级 | 单模态 | 连续超时>5%/熔断>50次 | 其他模态降权 |
| L4 规则级 | 单条规则 | 误报率>50%/版本异常 | 无 |

状态机：IDLE → ARMED → ACTIVE → COOLDOWN → IDLE
- L1/L2：合规官 + 双签触发（含短信二次确认）
- L3/L4：系统自动触发，可手动 override
- 状态一致性：读路径每次直查 Redis（无本地缓存），写入经 pubsub 广播；
  listen_kill_switch 提供跨副本事件留痕（可观测性），非一致性依赖
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from enum import StrEnum
from typing import Any

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class KillSwitchScope(StrEnum):
    """Kill Switch 作用域（4 级）。"""

    L1_GLOBAL = "L1_GLOBAL"
    L2_MODEL = "L2_MODEL"
    L3_MODALITY = "L3_MODALITY"
    L4_RULE = "L4_RULE"


class KillSwitchState(StrEnum):
    """Kill Switch 状态机。"""

    IDLE = "IDLE"
    ARMED = "ARMED"
    ACTIVE = "ACTIVE"
    COOLDOWN = "COOLDOWN"


# Redis key 前缀
_KEY_PREFIX = "kill_switch"


def _make_key(scope: KillSwitchScope, target: str | None = None) -> str:
    if target:
        return f"{_KEY_PREFIX}:{scope.value}:{target}"
    return f"{_KEY_PREFIX}:{scope.value}"


class KillSwitch:
    """Kill Switch 状态机（从 Redis 读取状态，热更新）。"""

    async def is_active(
        self,
        scope: KillSwitchScope,
        target: str | None = None,
    ) -> bool:
        """检查指定作用域的 Kill Switch 是否激活。"""
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            key = _make_key(scope, target)
            value = await redis.get(key)
            if value is None:
                return False
            state = json.loads(value)
            return bool(state.get("state") == KillSwitchState.ACTIVE.value)
        except Exception as exc:
            logger.warning("kill_switch_check_failed", scope=scope.value, target=target, error=str(exc))
            # Redis 故障时降级读取环境变量初始值
            return self._fallback_from_env(scope)

    def _fallback_from_env(self, scope: KillSwitchScope) -> bool:
        """Redis 不可用时从环境变量降级读取。"""
        if scope == KillSwitchScope.L1_GLOBAL:
            return settings.kill_switch_global
        if scope == KillSwitchScope.L2_MODEL:
            return settings.kill_switch_ml
        if scope == KillSwitchScope.L4_RULE:
            return settings.kill_switch_rules
        return False

    async def activate(
        self,
        scope: KillSwitchScope,
        target: str | None,
        reason: str,
        operator_id: uuid.UUID,
        duration_minutes: int = 60,
    ) -> dict[str, Any]:
        """激活 Kill Switch。

        L1/L2 需真人二次确认（短信验证码，骨架中先 log）。
        L3/L4 系统自动触发。
        """
        if scope in (KillSwitchScope.L1_GLOBAL, KillSwitchScope.L2_MODEL):
            # TODO: 真人二次确认（短信验证码）
            logger.warning(
                "kill_switch_activate_requires_2fa",
                scope=scope.value,
                target=target,
                operator_id=str(operator_id),
                note="TODO: SMS verification required for L1/L2",
            )

        state = {
            "state": KillSwitchState.ACTIVE.value,
            "scope": scope.value,
            "target": target,
            "reason": reason,
            "operator_id": str(operator_id),
            "duration_minutes": duration_minutes,
        }
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            key = _make_key(scope, target)
            await redis.set(key, json.dumps(state), ex=duration_minutes * 60)
            # 发布 pubsub 通知全节点
            await redis.publish(
                settings.kill_switch_pubsub_channel,
                json.dumps({"event": "activate", **state}),
            )
            logger.info("kill_switch_activated", **state)
        except Exception as exc:
            logger.error("kill_switch_activate_failed", error=str(exc), **state)

        # TODO: 记录到 audit_logs（哈希链）
        return state

    async def deactivate(
        self,
        scope: KillSwitchScope,
        target: str | None,
        operator_id: uuid.UUID,
    ) -> bool:
        """关闭 Kill Switch（转入 COOLDOWN 30 分钟）。"""
        try:
            from app.db.redis import get_redis

            redis = get_redis()
            key = _make_key(scope, target)
            # COOLDOWN 30 分钟
            cooldown_state = {
                "state": KillSwitchState.COOLDOWN.value,
                "scope": scope.value,
                "target": target,
                "operator_id": str(operator_id),
            }
            await redis.set(key, json.dumps(cooldown_state), ex=1800)
            await redis.publish(
                settings.kill_switch_pubsub_channel,
                json.dumps({"event": "deactivate", **cooldown_state}),
            )
            logger.info("kill_switch_deactivated", **cooldown_state)
            return True
        except Exception as exc:
            logger.error("kill_switch_deactivate_failed", error=str(exc))
            return False


async def listen_kill_switch() -> None:
    """订阅 kill switch 频道（跨副本事件留痕，可观测性）。

    读路径每次直查 Redis、无本地缓存，状态天然即时一致；
    本监听用于多副本部署下的激活/解除事件日志与未来告警联动扩展。
    断线 5s 重连；取消（应用关闭）时静默退出。
    """
    while True:
        pubsub = None
        try:
            from app.db.redis import get_redis

            pubsub = get_redis().pubsub()
            await pubsub.subscribe(settings.kill_switch_pubsub_channel)
            logger.info(
                "kill_switch_subscribed", channel=settings.kill_switch_pubsub_channel
            )
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message.get("data") or "{}")
                except ValueError:
                    continue
                logger.info(
                    "kill_switch_event",
                    action=payload.get("event"),
                    scope=payload.get("scope"),
                    target=payload.get("target"),
                    reason=payload.get("reason"),
                    operator_id=payload.get("operator_id"),
                )
        except asyncio.CancelledError:
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()  # type: ignore[no-untyped-call]
            raise
        except Exception as exc:
            logger.warning("kill_switch_listener_retry", error=str(exc))
            if pubsub is not None:
                with contextlib.suppress(Exception):
                    await pubsub.aclose()  # type: ignore[no-untyped-call]
            await asyncio.sleep(5)


# 单例
kill_switch = KillSwitch()


__all__ = [
    "KillSwitch",
    "KillSwitchScope",
    "KillSwitchState",
    "kill_switch",
    "listen_kill_switch",
]
