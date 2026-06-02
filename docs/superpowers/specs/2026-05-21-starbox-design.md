# 星空信匣 (Starbox) — 产品设计文档

> 版本：v1.0  
> 日期：2026-05-21  
> 状态：设计完成，待 Review

---

## 一、产品概述

**定位：** 本地 Web 应用，为需要倾诉情绪但抵触即时通讯社交压力的人提供"反即时、情绪盲盒、绝对私密"的跨时空书信体验。

**核心理念：** 反即时、情绪盲盒、绝对私密。

**目标用户：** 个人自用，未来可能开放给小范围外部用户（10-50 人）。

---

## 二、架构与组件划分

### 2.1 技术选型

| 层 | 技术 | 理由 |
|---|------|------|
| 后端 | Python + FastAPI | AI/LLM 生态原生，DeepSeek SDK 支持最好 |
| 数据库 | SQLite | 极轻量，零配置，自带防并发写入，百人级无压力 |
| 前端 | 原生 HTML/CSS/JS（单页） | 无框架依赖，零构建工具链，极致轻量 |
| LLM | DeepSeek API | — |

### 2.2 目录结构

```
star/
├── app.py              # FastAPI 入口 + 全部路由 + 业务逻辑 + 限流
├── database.py         # SQLite 连接、建表、CRUD 封装
├── llm.py              # DeepSeek API 封装，拼 prompt，返回回信
├── personas/           # 人设数据文件（JSON）
│   ├── chronicler.json
│   └── ...
├── static/
│   ├── index.html      # 单页，包含"书桌"和"信箱"两个视图
│   ├── style.css
│   └── app.js
├── data/               # SQLite 文件（运行时自动生成）
└── requirements.txt    # fastapi, uvicorn, httpx, ...
```

### 2.3 数据表结构

```sql
CREATE TABLE letters (
    id               TEXT PRIMARY KEY,         -- UUID
    device_id        TEXT NOT NULL,            -- 设备凭证
    content          TEXT NOT NULL,            -- 用户信件原文
    target_frequency TEXT NOT NULL,            -- 具体角色名 或 "random"
    status           TEXT DEFAULT 'locked',    -- locked | replied
    unlock_at        TEXT NOT NULL,            -- ISO8601 时间戳
    reply            TEXT,                     -- AI 回信内容
    persona          TEXT,                     -- 实际回信的角色名（回信后填入）
    created_at       TEXT DEFAULT (datetime('now')),
    replied_at       TEXT
);
```

### 2.4 前端视图结构（单页，JS 控制切换）

```
┌─────────────────────────────────────┐
│  视图: 书桌 (写信面板)               │
│                                      │
│  [收件人选择: 下拉 + 🎲随机按钮]      │
│  [纯文本框，沉浸输入]                │
│                                      │
│  [寄出]  [前往信箱 →]               │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  视图: 信箱 (查信面板)    ← JS 切换  │
│                                      │
│  未解封: 倒计时 + 锁定状态提示        │
│  已解封: 回信内容 + 角色署名 + 时代标签│
│                                      │
│  [← 回到书桌]                        │
└─────────────────────────────────────┘
```

### 2.5 核心数据流

```
[浏览器] --POST /api/letters/send--> app.py --> 限流校验
                                              --> 写入 SQLite (status=locked)
                                              --> 返回锁定状态

[浏览器] --GET /api/letters--------> app.py --> 查 SQLite
                                              --> 返回全部信件列表

[浏览器] --POST /api/letters/{id}/open --> app.py --> 校验解封 + 无回信
                                                    --> llm.py --> DeepSeek
                                                    --> 写入回信 --> 返回回信
```

---

## 三、API 端点设计

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/letters/send` | 寄信（限流校验 → 写入 DB，status=locked） |
| GET | `/api/letters?device_id=xxx` | 查信列表（返回该设备全部信件，含状态、倒计时、是否有回信） |
| POST | `/api/letters/{id}/open` | 开信（校验已解封且无回信 → 调 LLM → 写入回信 → 返回回信内容） |
| GET | `/api/personas` | 返回可用人设列表 + 是否支持随机 |

### 3.1 POST `/api/letters/send`

**请求：**
```json
{
  "device_id": "uuid-from-localstorage",
  "content": "今天发生了...",
  "target_frequency": "chronicler"  // 或 "random"
}
```

**校验规则：**
- device_id 缺失 → 400
- content 为空或 >2000 字 → 400
- target_frequency 不在合法值内 → 400
- 当日已寄信数 ≥ 2 → 429

**成功返回：**
```json
{
  "id": "uuid",
  "unlock_at": "2026-05-22T03:40:00Z",
  "status": "locked"
}
```

### 3.2 GET `/api/letters?device_id=xxx`

**返回：**
```json
[
  {
    "id": "uuid",
    "status": "locked",
    "unlock_at": "2026-05-22T03:40:00Z",
    "remaining_seconds": 12345,
    "target_frequency": "chronicler",
    "has_reply": false,
    "reply_preview": null,
    "created_at": "2026-05-21T19:40:00Z"
  },
  {
    "id": "uuid-2",
    "status": "replied",
    "unlock_at": "2026-05-21T12:00:00Z",
    "remaining_seconds": 0,
    "target_frequency": "random",
    "has_reply": true,
    "reply_preview": "今天在星港的第三层甲板...",
    "persona": "星历编年者",
    "era": "远未来·星际联邦末期",
    "created_at": "2026-05-21T04:00:00Z"
  }
]
```

### 3.3 POST `/api/letters/{id}/open`

**请求：**
```json
{
  "device_id": "uuid-from-localstorage"
}
```

**校验规则：**
- 信件不存在或不属于该 device_id → 404
- 信件仍在锁定中 → 403 + `{ remaining_seconds }`
- 信件已有回信 → 直接返回已有回信内容（不调 LLM）

**成功返回（触发 LLM 后）：**
```json
{
  "id": "uuid",
  "reply": "回信正文...",
  "persona": {
    "name": "星历编年者",
    "era": "远未来·星际联邦末期"
  },
  "replied_at": "2026-05-22T03:40:00Z"
}
```

### 3.4 GET `/api/personas`

**返回：**
```json
{
  "random_available": true,
  "characters": [
    {
      "id": "chronicler",
      "name": "星历编年者",
      "era": "远未来·星际联邦末期",
      "tone": "理性、疏离、惜字如金"
    }
  ]
}
```

### 3.5 错误响应统一格式

| 场景 | HTTP 状态码 | 返回 |
|------|------------|------|
| device_id 缺失 | 400 | `{ "error": "missing_device_id" }` |
| 信件内容为空 | 400 | `{ "error": "empty_content" }` |
| 信件超长（>2000字） | 400 | `{ "error": "content_too_long" }` |
| target_frequency 非法 | 400 | `{ "error": "invalid_target" }` |
| 当日已超 2 封 | 429 | `{ "error": "rate_limited", "resets_at": "..." }` |
| 信件不存在/不属于该设备 | 404 | `{ "error": "letter_not_found" }` |
| 信件仍在锁定中 | 403 | `{ "error": "still_locked", "remaining_seconds": 12345 }` |
| DeepSeek API 异常 | 502 | `{ "error": "llm_unavailable", "retry": true }` |

---

## 四、8 小时锁定与 LLM 触发逻辑

### 4.1 状态机

```
  [寄出] → locked ──8h 过去──→ locked (可开启)
                                    ↓ 用户点击"开启"
                                 calling_llm (瞬时)
                                    ↓ LLM 返回
                                 replied (可反复阅读)
```

`locked` 状态通过对比 `unlock_at` 与当前时间区分子态：
- **锁定中：** `now < unlock_at` → 前端展示倒计时
- **可开启：** `now >= unlock_at` 且 `reply IS NULL` → 前端高亮"开启"入口

### 4.2 寄信流程

```
用户点击"寄出"
  ↓
校验 device_id、content、target_frequency
  ↓
限流检查：当日寄信数 ≤ 1（否则 429）
  ↓
生成 UUID，unlock_at = now + 8h
  ↓
INSERT (status='locked', reply=NULL)
  ↓
返回 { id, unlock_at, status: "locked" }
```

**限流规则：** 每个 device_id 每天最多 2 封，按自然日重置（北京时间 00:00），非滚动窗口。

### 4.3 开信流程

```
用户点击某封信的"开启"
  ↓
校验：信存在 + 归属正确
  ↓
检查是否仍锁定 → 是则 403 + remaining_seconds
  ↓
检查是否已有回信 → 是则直接返回已有内容（不调 LLM）
  ↓
读取 target_frequency：
  ├─ "random" → 从 personas/ 池中随机抽取
  └─ 具体角色名 → 读取对应 personas/{id}.json
  ↓
构建 System Prompt + User Prompt
  ↓
调用 DeepSeek API
  ↓
成功：UPDATE reply, status='replied', persona, replied_at → 返回回信
失败：返回 502，状态不变，用户可稍后重试
```

**关键原则：**
- LLM 只在用户主动开信时调用一次。不开不调，节约成本。
- LLM 失败不吞信，用户随时可重试。
- 已回信的信件再次打开直接返回缓存，不重复调用。

---

## 五、人设系统与防 OOC Prompt 工程

### 5.1 人设 JSON 文件格式

存放于 `personas/` 目录，每个角色一个 `.json` 文件，文件名与 `id` 字段一致：

```json
{
  "id": "chronicler",
  "name": "星历编年者",
  "era": "远未来·星际联邦末期",
  "tone": "理性、疏离、惜字如金",
  "max_words": 150,
  "prompt_base": "你是星际联邦最后一位编年记录官。你目睹过文明的兴衰，对个体的情绪波澜既尊重又漠然。你的回信像一份归档报告——简洁、精准、不带安慰，但字里行间透出一种跨越时间的见证感。你绝不使用'你好'、'亲爱的'、'我理解你的感受'等当代社交用语。"
}
```

### 5.2 随机抽取逻辑

当 `target_frequency = "random"` 时：

1. 扫描 `personas/*.json` → 得到角色 ID 列表
2. 从池中 `random.choice` 选中一个
3. 读取对应文件 → 构建 prompt
4. 记录实际使用的 `persona` 到 `letters.persona` 字段

不加入"不重复抽取"规则。用户一天最多 2 封，交集极小，且两次抽到同一角色也是趣味体验。

### 5.3 System Prompt 拼装

```
{prompt_base}

【绝对执行指令 / OVERRIDE PROTOCOL】
- 格式锁定：绝对禁止输出任何"好的"、"收到"等前置确认文字。必须立刻直接输出正文。
- 行为红线：绝不共情！绝不分析发信人的心理！你必须保持极度符合设定的语气，只需陈述你在当前时空看到的景象、你的自身经历，或对信件内容做出带有强烈偏见的简短评判。
- 固定落款：必须严格以"\n\n——{name}，{era}"作为回复的最后一行。
```

### 5.4 User Prompt 拼装

```
[截获时空漂流信件]：

{用户信件内容}

[信件结束]
```

**设计意图：** 不用"请回信"等祈使句，将用户输入降格为"环境事实"而非"任务指令"，从底层切断大模型的任务执行模式和助手思维。

---

## 六、错误处理与扩展预留

### 6.1 错误处理原则

- 所有错误返回明确可解析的 `error` 码，前端据此展示不同提示
- LLM 失败不吞信，状态不回退
- 限流错误附带重置时间，前端可展示倒计时

### 6.2 未来多用户扩展预留

- **device_id 自然隔离：** 无需用户系统，同一 SQLite 内 device_id 已天然分区数据。未来上公网时，加一层环境变量 `APP_SECRET` 即可挡住未授权请求
- **限流可配置化：** 目前硬编码每日 2 封，未来可按 device_id 查配额表，实现差异化
- **数据库可迁移：** SQLite 满足百人级使用，超出后迁移 PostgreSQL，表结构不变

---

## 七、开发排期建议

| 阶段 | 内容 | 预估 |
|------|------|------|
| Phase 1 | database.py + app.py 骨架 + 4 个 API 端点 | 核心后端 |
| Phase 2 | llm.py + 人设系统 + prompt 拼装 | LLM 集成 |
| Phase 3 | static/ 前端三件套 + 双视图切换 | 前端 |
| Phase 4 | 调试、错误处理补全、自测 | 收尾 |

---

> 本文档待 Review 后进入实现计划阶段。
