# ADR-016: 事件外发以 Webhook + WebSocket 为准，Kafka 延后

- 状态：已接受（Accepted）
- 日期：2026-08-25
- 关联：D03 SAD §5.3 / ADR-004 / ADR-014（本 ADR 修订其 Kafka 叙事，历史文档不改写）

## 背景

D03 SAD 将 Kafka 列为消息队列选型（frd.transactions / frd.decisions / frd.audit_log
三 topic），代码中仅以占位形式存在：

- `ScoringOrchestrator._publish_to_kafka`：fire-and-forget 占位，仅打日志（TODO 接 aiokafka）；
- `Settings.KafkaConfig` 五个配置字段与 `.env.example` 对应变量；
- helm values 中 `KAFKA_TOPIC_*` 环境变量。

实际运行形态为单机 docker compose 演示：**不存在 Kafka broker，也不存在任何消费者**。
占位实现只制造"具备流处理能力"的虚假叙事，还暗示了并不存在的 aiokafka 依赖与连接管理成本。

## 决策

移除全部 Kafka 占位实现。事件外发以两条已接线的出口为准：

1. **WebSocket 实时推送**：`ws_events.publish_ws_event` → Redis pub/sub `frd:ws_events`
   （评分完成 / 建案 / SHAP 就绪 / Webhook 投递终态等事件）；
2. **Webhook 可靠投递**：`webhook.deliver` Celery 任务，HMAC-SHA256 签名 +
   指数退避重试 + 死信终态（reject / manual_review 决策按商户投递）。

DB 写入维持评分主路径内 await 同步落库，不依赖任何 MQ 消费者兜底。

## 理由

- **无真实消费者**：单机 compose 场景没有任何服务消费这三类 topic；
- **运维成本**：broker 部署、监控、分区规划对演示场景是纯负担；
- **诚实原则**：日志里的 `kafka_publish_skeleton` 不构成能力，删除优于注释承诺。

## 重启条件

出现以下任一需求时重新评估接入（届时按 D03 §5.3 三 topic 规划引入 aiokafka /
confluent-kafka，并恢复独立消费者进程）：

- **多消费者扇出**：≥2 个异构下游需要消费同一事件流（当前 Webhook 按商户定向、
  WS 按租户隔离，均为单用途出口，不构成扇出）；
- **跨服务拆分**：评分主路径与持久化 / 审计需要跨进程异步解耦
  （当前同进程 await 已满足 P99 ≤ 200ms）；
- **重放 / 回填**：出现需要按 offset 重放历史事件的合规或训练场景。

## 后果

- 配置面缩小：`kafka_*` settings 字段、两份 `.env.example` 变量、helm env 全部移除；
- `scoring.persist_score` / `scoring.persist_transaction` 备用任务保留但当前无调用方，
  其"Kafka Consumer 触发"措辞修正为备用任务定位；
- 行为锚定测试锁定：settings 无 `kafka_*` 字段、编排器无 MQ 发布入口、
  WS / Webhook 出口仍被主路径引用。
