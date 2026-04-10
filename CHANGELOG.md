# Changelog

## 2026-04-11 — 飞书多维表格全流程打通

### 功能完成
- **自动镜片码分配**：后台 poller 线程每 60 秒轮询飞书多维表格，检测新订单（镜片码字段为空），自动分配唯一 16 位 hex 镜片码并写回 Feishu 记录
- **QR 码本地生成**：每条订单同步在 `static/qrcodes/` 生成 PNG，供工厂导出包使用
- **全流程验证**：提交测试单 TEST-FLOW-001 → 60 秒内 poller 检测 → 镜片码 `1B33F560056B4658` 写回飞书，端到端通过

### 技术修复
- **InvalidFilter 1254018**：`订单状态` 字段对 app token 不可见（已从表单删除），改为仅按 `镜片码 is empty` 过滤，消除 API 报错
- **Feishu workflow HTTP action 不可用**：飞书自动化 v3 API 不支持发送 HTTP 请求节点，改用 pull 轮询模型替代 webhook push
- **双 worker 竞争写入**：2 个 gunicorn worker 各启动一个 poller 线程，同一记录被重复处理，Dockerfile 改为 `-w 1` 单 worker 解决
- **字段值格式**：`订单编号`、`患者姓名` 等文本字段返回 `[{"text": "...", "type": "text"}]` 列表格式，解析时做兼容处理
- **PATCH → PUT**：Feishu Bitable 记录更新用 PUT，不是 PATCH（之前导致 404）

### 架构说明
代理商无需二维码，流程如下：
1. 代理商填飞书表单提交订单
2. Poller 自动分配镜片码（≤60s）、本地生成 QR PNG
3. 管理员在 `/admin` 查看订单，导出工厂包（含二维码）交生产
