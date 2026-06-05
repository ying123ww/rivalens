# Session Persistence & Concurrency Refactor

> 2026-06-04 — 会话记忆、并发控制、持久化数据、可追溯性 全面重构

---

## 1. 持久化基础设施

### 1.1 统一 MetaData + Alembic 迁移

**问题**：`user_store` / `trace_store` / `session_store` 各维护独立的 `MetaData()`，`create_all()` 只能建表不能改表，改 schema 需手动 SQL。

**改动**：

| 文件 | 变更 |
|---|---|
| `backend/server/metadata.py` | **新建**，唯一的 `shared_metadata = MetaData()` |
| `backend/server/user_store.py` | `users` 注册到 `shared_metadata` |
| `backend/server/trace_store.py` | 全部 20 张表注册到 `shared_metadata`，移除 `users.to_metadata()` |
| `backend/server/session_store.py` | `chat_sessions` 注册到 `shared_metadata` |
| `alembic.ini` | **新建**，数据库连接配置 |
| `alembic/env.py` | **新建**，`target_metadata = shared_metadata` |
| `alembic/versions/` | **新建**，初始迁移 + reports 表迁移 |
| `backend/server/app.py` | 启动时 `alembic upgrade head` 替代散落的 `initialize()` 调用 |
| `pyproject.toml` | 新增 `alembic>=1.13.0` 依赖 |

**日常使用**：

```bash
alembic revision --autogenerate -m "add column X"   # 生成迁移
alembic upgrade head                                  # 应用迁移（生产启动自动执行）
alembic downgrade -1                                  # 回滚一个版本
```

### 1.2 ReportStore JSON → SQL

**问题**：报告元数据存 `data/reports.json`，和 trace 数据无关联，一致性靠运气。

**改动**：

| 文件 | 变更 |
|---|---|
| `backend/server/report_store.py` | **重写**，JSON 文件存储 → `reports` 表 + JSONB 灵活字段 |
| `backend/server/app.py` | `ReportStore()` 不再传路径参数；旧 JSON 报告需设置 `RIVALENS_MIGRATE_LEGACY_REPORTS=true` 后按 marker 一次性导入 |
| `alembic/versions/3d6c1c76773f_add_reports_table.py` | `reports` 表迁移 |

**`reports` 表结构**：

| 列 | 类型 | 说明 |
|---|---|---|
| `report_id` | TEXT PK | "task_1717000000_..." |
| `user_id` | UUID FK → users | 可为空 |
| `run_id` | TEXT FK → analysis_runs | **新增：报告和溯源关联** |
| `question` / `answer` / `status` | TEXT | 固定字段 |
| `report_type` / `report_source` / `tone` | VARCHAR | 固定字段 |
| `timestamp` | TIMESTAMPTZ | — |
| `docx_path` / `pdf_path` / `markdown_path` / `html_path` | TEXT | 文件路径 |
| `data` | JSONB | 灵活字段（orderedData, chatMessages, artifacts 等） |
| `error` | TEXT | — |
| `created_at` / `updated_at` | TIMESTAMPTZ | — |

**API 不变**：`get_report` / `upsert_report` / `list_reports` / `delete_report` 签名和返回格式保持一致。

### 1.3 移除 outputs/*.json 日志文件

**问题**：`CustomLogsHandler` 每次事件触发读-改-写 `outputs/{research_id}.json`，I/O 密集且数据与 trace_store 重复。

**改动**：

| 文件 | 变更 |
|---|---|
| `backend/server/server_utils.py` | 删除 `_write_log_data()` 文件读写；`log_file` 属性移除；`file_paths["json"]` 不再返回 |

**效果**：事件数据通过 `report_store.upsert_report()` 直接入 SQL，`ordered_data` 保留在内存中构建响应。

---

## 2. 会话记忆 (SessionStore)

### 2.1 Redis Stream 消息存储

**设计**：

```
chat:session:{sid}:stream      Stream  MAXLEN ~500  消息流（XADD O(1)追加）
chat:session:{sid}:meta        Hash    TTL 30min    元信息
chat:sessions:user:{uid}:order ZSet                  侧边栏排序
```

**文件**：`backend/server/session_store.py`（新建）

**核心方法**：

| 方法 | 说明 |
|---|---|
| `create_session(user_id, title)` | PG + Redis 双写 |
| `get_sidebar_sessions(user_id)` | ZSet 排序 → 不足 10 条从 PG 补足 |
| `get_session(session_id)` | Redis 命中返回 → miss 查 PG 回填 |
| `append_message(session_id, msg)` | PG JSONB `||` 原子追加 → Redis XADD |
| `update_session_memory(session_id, msgs)` | PG 全量覆盖 → Redis stream_replace |
| `update_session_meta(session_id, title)` | 重命名 |
| `delete_session(session_id)` | PG 删除 → Redis Lua 清理多 key |

### 2.2 Lua 脚本原子性

**文件**：`backend/server/session_store.py`

| 脚本 | 原子操作 | 调用场景 |
|---|---|---|
| `cache_meta` | `HSET` meta + `EXPIRE` meta + `ZADD` order | 缓存写入 |
| `refresh_ttl` | `EXPIRE` stream + `EXPIRE` meta | 读取命中续期 |
| `append` | `XADD` stream + `HSET` updated_at + `EXPIRE` meta + `ZADD` order | 追加消息 |
| `delete_keys` | `DEL` stream + `DEL` meta + `ZREM` order | 删除清理 |

通过 `redis.register_script()` 预加载，运行时走 `EVALSHA`。

### 2.3 PG JSONB `||` 原子追加

**问题**：`append_message` 原来 SELECT-then-UPDATE，两个并发请求可能丢消息。

**修复**：

```sql
-- 原子追加，无竞态
UPDATE chat_sessions
SET memory = memory || '{"role":"user","content":"hi"}'::jsonb,
    updated_at = now()
WHERE session_id = $1;
```

写入顺序：**PG 先（真相源），Redis 后（best-effort 缓存）**。

### 2.4 REST API

| 方法 | 路径 | 功能 | 鉴权 |
|---|---|---|---|
| `GET` | `/api/sessions` | 侧边栏最近 10 条 | Bearer Token |
| `POST` | `/api/sessions` | 创建新会话 | Bearer Token |
| `GET` | `/api/sessions/{id}` | 获取会话含消息 | Bearer Token |
| `POST` | `/api/sessions/{id}/messages` | 追加单条消息 | Bearer Token |
| `PUT` | `/api/sessions/{id}/memory` | 全量覆盖消息 | Bearer Token |
| `PATCH` | `/api/sessions/{id}` | 重命名会话 | Bearer Token |
| `DELETE` | `/api/sessions/{id}` | 删除会话 | Bearer Token |

### 2.5 测试

**文件**：`tests/test_session_store.py` — 14 个单元测试

| 测试类 | 覆盖 |
|---|---|
| `SessionStorePgAtomicAppendTest` | JSONB `||` 原子追加，无 SELECT |
| `SessionStoreWriteOrderTest` | PG 先于 Redis |
| `SessionStoreSidebarPaddingTest` | ZSet 不足 10 条从 PG 补足 |
| `SessionStoreRedisUnavailableTest` | Redis 降级到纯 PG |
| `MessageSerializationTest` | 消息序列化/反序列化 |
| `EnvFlagTest` | 环境变量开关 |

### 2.6 前端 Hook

**文件**：`frontend/nextjs/hooks/useChatSessions.ts`（新建）

封装对后端 6 个端点的调用：`fetchSessions` / `createSession` / `deleteSession` / `renameSession` / `getSession` / `appendMessage`。

---

## 3. 并发控制

### 3.1 LLM 全局限流令牌桶

**问题**：deep research 用 `asyncio.gather` 并发 LLM 调用，无全局限流，可能打爆 API quota。

**文件**：`rivalens/research/utils/llm_rate_limiter.py`（新建）

- Redis Lua 脚本实现 token bucket，原子 check-and-consume
- 单例模式，多 worker 共享同一 Redis bucket
- Redis 不可用自动放行
- 集成到 `create_chat_completion()`：进入重试循环前先 `acquire(provider)`

**配置**：

```bash
RIVALENS_LLM_RPM_LIMIT=500          # 全局每分钟请求数，0 = 不限
RIVALENS_LLM_RPM_LIMIT_OPENAI=300   # 按 provider 覆盖
```

### 3.2 LLM 专用线程池

**问题**：非流式 LLM 调用全部走 Python 默认 `ThreadPoolExecutor`（~12 线程），高并发时成为瓶颈。

**文件**：`rivalens/research/llm_provider/generic/base.py`

```python
_llm_executor = ThreadPoolExecutor(
    max_workers=64,   # RIVALENS_LLM_THREAD_POOL_SIZE 控制
    thread_name_prefix="rivalens-llm",
)
```

`run_in_executor(None, ...)` → `run_in_executor(_get_llm_executor(), ...)`

### 3.3 MCP os.environ 竞态

**问题**：`websocket_manager.py` 中 MCP 代码写 `os.environ["RETRIEVER"]` 和 `os.environ["MCP_STRATEGY"]`，并发 WebSocket 互相覆盖。

**修复**：删除 `os.environ` 写入，MCP 配置通过函数参数传递给下游。

### 3.4 TraceStore 实例合并

**问题**：`app.py` 和 `rivalens_runner.py` 各自创建 `TraceStore()`，两个独立的 SQLAlchemy Engine 和连接池。

**修复**：

| 文件 | 变更 |
|---|---|
| `rivalens_runner.py` | `trace_store` → `_trace_store`，新增 `set_trace_store()` 注入函数 |
| `app.py` | 创建 `trace_store` 后调用 `set_trace_store(trace_store)` |

---

## 4. 前端修复

### 4.1 删除同步 bug

**问题**：`deleteResearch` 将 404 当成成功，API 失败时仍乐观删除本地数据，刷新后数据恢复。

**文件**：`frontend/nextjs/hooks/useResearchHistory.ts`

**修复**：API 返回任何非 2xx 都抛异常，catch 中不删除本地数据，弹 toast 提示错误。

---

## 5. 环境变量参考

```bash
# .env

# 会话持久化
RIVALENS_SESSION_PERSISTENCE_ENABLED=true   # 会话存储开关
REDIS_URL=redis://:123456@localhost:6380/0  # Redis 连接

# LLM 限流
RIVALENS_LLM_RPM_LIMIT=500                  # 全局每分钟请求数
RIVALENS_LLM_THREAD_POOL_SIZE=64            # LLM 专用线程池大小

# 溯源
RIVALENS_TRACE_PERSISTENCE_ENABLED=true     # 溯源写入 PG
RIVALENS_AUTO_CREATE_TABLES=true            # 启动时自动建表

# 数据库
DATABASE_URL=postgresql://rivalens:123456@localhost:5433/rivalens

# 旧报告 JSON 迁移
RIVALENS_MIGRATE_LEGACY_REPORTS=false        # 仅需要导入 data/reports.json 时临时打开
REPORT_STORE_MIGRATION_MARKER_PATH=          # 可选：自定义一次性迁移 marker 路径
```

---

## 6. 评估

| 维度 | 改前 | 改后 | 说明 |
|---|---|---|---|
| 会话记忆 | 6/10 | 8/10 | Redis Stream + Lua + PG 原子追加 + 14 测试 |
| 并发控制 | 4/10 | 7/10 | LLM 限流 + 独立线程池 + MCP 竞态修复 + TraceStore 合并 |
| 持久化数据 | 5/10 | 8/10 | 统一 MetaData + Alembic + ReportStore SQL + JSON 日志移除 |
| 可追溯性 | 7/10 | 7/10 | 表结构设计好，但需开启 `RIVALENS_TRACE_PERSISTENCE_ENABLED=true` |
