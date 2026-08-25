"""workers 模块：Celery 异步任务（D03 V1.1 §1.3 / ADR-014）。

任务分组：
- celery_app: Celery 实例与配置
- tasks_scoring: 自动建案 / 漂移检测 / 备用持久化任务
- tasks_shap: SHAP 异步计算（D03 ADR-007）
- tasks_pipl: PIPL 数据导出 / 删除 / 更正异步任务
"""
