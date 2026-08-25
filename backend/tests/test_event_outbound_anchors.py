"""事件外发行为锚定（ADR-016）：MQ 占位移除后，出口仅剩 WS 推送 + Webhook 投递。

锁定三层事实，防止死配置 / 占位调用链悄悄回归：
1. Settings 不再包含 kafka_* 字段；
2. 评分编排器不存在 MQ 发布入口（原 _publish_to_kafka 占位已删）；
3. 两条已接线出口（publish_ws_event / store_webhook_event）仍被主路径引用。
"""

from app.config import settings
from app.services import scoring as scoring_module
from app.services.scoring import scoring_orchestrator


def test_settings_has_no_kafka_fields() -> None:
    """ADR-016：Kafka 配置组整体移除，不得残留死字段。"""
    leftover = [name for name in type(settings).model_fields if "kafka" in name]
    assert leftover == []


def test_orchestrator_has_no_mq_publish_entrypoint() -> None:
    """ADR-016：评分主路径不得存在 MQ 发布入口。"""
    assert not hasattr(scoring_orchestrator, "_publish_to_kafka")
    assert not any("kafka" in name.lower() for name in dir(scoring_orchestrator))


def test_wired_event_outlets_remain() -> None:
    """ADR-016：WS 实时推送与 Webhook 事件存储两条出口不受影响。"""
    assert callable(scoring_module.publish_ws_event)
    assert callable(scoring_module.store_webhook_event)
