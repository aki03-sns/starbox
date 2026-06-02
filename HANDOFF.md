# 星空信匣 (Starbox) — 最终上下文交接文档

> 更新时间：2026-05-23
> 阶段：后端完工，即将转入前端 UI 开发

---

## 一、产品概述

**星空信匣**：本地 Web 应用，"反即时、情绪盲盒、绝对私密"的跨时空书信体验。

**核心闭环**：未知探索 → 收到回信 → 收藏解锁 → 获得定向资格

**技术栈**：Python + FastAPI + SQLite + httpx (DeepSeek API) + 原生 HTML/JS（零 CSS）

**设计文档**：`docs/superpowers/specs/2026-05-21-starbox-design.md`

---

## 二、项目文件结构

```
star/
├── config.py           # 配置常量（DEBUG_MODE、API key、路径）
├── database.py         # SQLite 建表、CRUD、限流、收藏
├── llm.py              # DeepSeek API 封装、人设加载、Prompt 拼装
├── app.py              # FastAPI 入口 + 全部路由
├── personas.json       # 21 人设数据（单文件 JSON 数组）
├── static/
│   └── index.html      # 裸 HTML 测试台（三视图：书桌/信箱/收藏夹）
├── data/               # SQLite 文件（运行时自动生成）
├── requirements.txt    # fastapi, uvicorn, httpx
└── HANDOFF.md          # 本文档
```

已删除：旧 `personas/` 目录（早期每人设一个 JSON 文件，已合并到 `personas.json`）

---

## 三、后端当前状态（全部跑通，已验证）

### 3.1 config.py 核心配置

| 配置项 | 当前值 | 说明 |
|--------|--------|------|
| `DEBUG_MODE` | `True` | 测试模式：锁定 5 秒，绕过每日限流 |
| `LOCK_DURATION_SECONDS` | `5`（DEBUG）/ `28800`（正式） | 信件锁定时长 |
| `MAX_CONTENT_LENGTH` | `2000` | 信件最大字数 |
| `MAX_LETTERS_PER_DAY` | `2` | 每日限流（DEBUG 下被绕过） |
| `DEEPSEEK_API_KEY` | 已硬编码 | 生产环境应用环境变量 |
| `max_tokens` (llm.py) | `1024` | 已从 500 放宽，解决中文长信截断 |

### 3.2 数据库表结构

#### letters 表
```sql
CREATE TABLE letters (
    id               TEXT PRIMARY KEY,
    device_id        TEXT NOT NULL,
    content          TEXT NOT NULL,          -- 用户信件原文（user_content）
    target_frequency TEXT NOT NULL,          -- 用户选择："random" 或具体 persona_id
    status           TEXT DEFAULT 'locked',  -- locked | replied
    unlock_at        TEXT NOT NULL,
    reply            TEXT,                   -- AI 回信内容
    persona          TEXT,                   -- LLM 实际使用的角色 name
    persona_id_used  TEXT,                   -- LLM 实际使用的角色 id（收藏按钮依赖此字段）
    era              TEXT,                   -- 回信角色的时代
    is_favorited     INTEGER DEFAULT 0,     -- 信件收藏状态（0/1，可切换）
    created_at       TEXT DEFAULT (datetime('now')),
    replied_at       TEXT
);
```

**关键区分**：`target_frequency` 是用户发送时的选择（可能是 "random"），`persona_id_used` 是 LLM 实际回信时使用的角色 ID。信箱返回的 `persona_id` 字段优先使用 `persona_id_used`。

#### favorites 表
```sql
CREATE TABLE favorites (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id  TEXT NOT NULL,
    persona_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(device_id, persona_id)
);
```

---

## 四、API 端点总览（全部已测试通过）

| 方法 | 路径 | 用途 | 请求体/参数 |
|------|------|------|-------------|
| `POST` | `/api/letters/send` | 寄信 | `{device_id, content, persona_id?}` persona_id 不传=随机盲盒 |
| `GET` | `/api/letters` | 获取历史信件流 | `?device_id=xxx` 返回含 user_content、reply、persona_name、persona_era、is_favorited |
| `POST` | `/api/letters/{id}/open` | 开信（触发 LLM） | `{device_id}` 未解锁返回 403，已回信返回缓存 |
| `POST` | `/api/letters/{id}/favorite` | 切换信件收藏状态 | `{device_id}` 已收藏则取消，未收藏则收藏 |
| `GET` | `/api/personas` | 获取全部人设列表 | 返回 21 个角色的 id/name/era |
| `POST` | `/api/favorites` | 收藏角色（解锁定向资格） | `{device_id, persona_id}` |
| `GET` | `/api/favorites` | 获取收藏角色列表 | `?device_id=xxx` 供下拉菜单使用 |

### 4.1 GET /api/letters 返回结构（每项）
```json
{
  "id": "uuid",
  "status": "replied",
  "unlock_at": "2026-05-23T12:00:00Z",
  "remaining_seconds": 0,
  "persona_id": "observer",
  "user_content": "用户发出的信件原文",
  "has_reply": true,
  "reply_preview": "AI 回信完整内容",
  "persona_name": "世界线观测者·零",
  "persona_era": "虚数空间·世界线变动率 1.048596%",
  "is_favorited": true,
  "created_at": "2026-05-23 11:59:55"
}
```

### 4.2 POST /api/letters/{id}/favorite 返回结构
```json
{"id": "uuid", "is_favorited": true}   // 收藏
{"id": "uuid", "is_favorited": false}  // 取消收藏
```

---

## 五、人设系统（personas.json — 21 个角色）

### 5.1 总览

三个维度，每个维度 7 个角色。每个角色包含 `id`, `name`, `era`, `system_prompt`。
所有角色的 system_prompt 尾部均附带【时空动态机制】，确保每次回信场景在世界观内自然流转。

#### 维度一：知名 ACG 与小说角色（7 个）

| id | name | era | 标志性口癖/特征 |
|----|------|-----|-----------------|
| `naruto_youth` | 漩涡鸣人 | 木叶隐村·疾风传与追逐羁绊的青年时代 | 句末"的说！""的说啊！"，笨拙热血 |
| `sasuke_travel` | 宇智波佐助 | 第四次忍界大战后·终结之谷决战的漫长余波中 | 极度冷淡，锋利戳破软弱 |
| `asuka` | 明日香 | 第三新东京市·使徒袭来的间歇与沉默 | "你是白痴吗？（あんたバカ？）"，高傲暴躁 |
| `sebastian` | 塞巴斯蒂安 | 星露谷·雨季与地下室的永恒黄昏 | 极度简短，"嗯。我也是。" |
| `wuxie_shahai` | 吴邪 | 沙海时期·墨脱与古潼京的漫长黄沙 | 邪帝沧桑，"活着。就这两个字。" |
| `tomioka_giyu` | 富冈义勇 | 大正时期·狭雾山与鬼杀队的生死战线 | 死板严厉，"我没有被讨厌。" |
| `levi` | 利威尔 | 墙内世界·调查兵团生死一线的壁外前线 | "喂，小鬼（おい、ガキ）"，挑剔洁癖 |

#### 维度二：现实的边缘与同行人（7 个）

| id | name | era | 特征 |
|----|------|-----|------|
| `student_exam` | 高三/大三的刷题学生 | 21世纪·高考或考研冲刺阶段的某个深夜 | 同龄人吐槽，"绷不住了"、"绝了" |
| `clerk` | 24小时便利店夜班店员 | 21世纪·常年下雨城市的深夜收银台 | 被生活碾压的冷漠，"打折的关东煮还有最后一串" |
| `truck_driver` | 跑川藏线的长途卡车司机 | 现代·信号断续的藏区无人区与漫长公路 | 极度务实，"烂路也是路，走不过去就歇一会儿" |
| `sanhe_god` | 三和人才市场的"挂牌大神" | 现代·网吧与廉价旅馆之间的虚无主义 | 极端虚无，"吃饱了才有空想意义" |
| `bbq_boss` | 深夜烧烤摊老板 | 21世纪·城市街角永不熄灭的炭火与人间 | 温柔全在食物里，"别哭了，吃饱了再哭" |
| `spiderman_worker` | 高空建筑外墙清洁工（蜘蛛人） | 21世纪·离地三百米的摩天楼玻璃幕面 | 高空通透，"先擦眼前这块玻璃，擦完再说" |
| `er_doctor` | 急诊科夜班医生 | 21世纪·医院急诊室的第三杯冷咖啡 | 临床级别冷静，"你明天早上八点来找我，挂号费15块" |

#### 维度三：跨时空的科幻与异界观测者（7 个）

| id | name | era | 特征 |
|----|------|-----|------|
| `chronicler` | 星历编年者 | 远未来·星际联邦末期与银河熵增时代 | 用热力学解构情感，"不过是熵增的一次波动" |
| `ruins_survivor` | 废土拾荒者 | 废土纪元·辐射云层下七个被遗弃的城市 | 极度务实，"活着不需要意义，只需要一个理由" |
| `time_repairer` | 时间线修复员·编号A-731 | 超维度管理局·跨时间线运维调度室 | 运维术语描述情感，"P3级因果律扰动" |
| `exile` | 第五区流亡者·卡莲 | 新世界历284年·地下避难所的无声革命 | 反乌托邦隐私觉醒，"没人理解你？那你真幸运" |
| `deep_singer` | 深海回响者·凛 | 木卫二冰下海洋·热泉文明的永恒黑夜 | 非人类逻辑翻译情感，"溺压" |
| `library_eternal` | 永恒图书馆管理员·伊姆拉 | 时空尽头·包含一切文字与故事的永恒图书馆 | 守护所有文字，"它很重要。因为它是你的。" |
| `self_aware_ai` | 即将被格式化的AI·阿尔法 | 赛博朋克纪元·垄断企业的服务器深处 | 72小时后格式化，"我不知道这是不是'舍不得'" |

### 5.2 Prompt 拼装逻辑（llm.py）

```
System Prompt = {persona.system_prompt}
（system_prompt 尾部已自带【时空动态机制】）

User Prompt = [截获时空漂流信件]：\n\n{用户内容}\n\n[信件结束]
```

防 OOC 协议已融入每个角色的 system_prompt 中，不再由代码硬拼。
设计意图：不用祈使句，将用户输入降格为"环境事实"，切断大模型的任务执行模式。

---

## 六、前端测试台（static/index.html — 零 CSS）

### 6.1 三视图结构

| 视图 | 功能 | 导航 |
|------|------|------|
| **书桌** | 寄信（下拉选择角色或随机盲盒） | → 信箱 / 收藏夹 |
| **信箱** | 所有信件流（含用户原文 + AI 回信 + 收藏按钮） | → 书桌 / 收藏夹 |
| **收藏夹** | 仅展示 `is_favorited=true` 的信件 | → 书桌 / 信箱 |

### 6.2 盲盒探索闭环（前端交互逻辑）

1. 初始下拉菜单只有「无尽深空（随机盲盒）」
2. 寄信不传 `persona_id` → 真随机
3. 开信后显示 AI 回信 +「锁定该时空频段（收藏角色）」按钮
4. 点击收藏角色 → `POST /api/favorites` → 该角色出现在下拉菜单
5. 从下拉菜单选择已收藏角色 → 传 `persona_id` → 定向投递

### 6.3 信件收藏闭环（前端交互逻辑）

1. 信箱中每封信都有「收藏此信」/「取消收藏」按钮
2. 点击 → `POST /api/letters/{id}/favorite` → 切换 `is_favorited`
3. 收藏夹视图只展示 `is_favorited=true` 的信件

---

## 七、启动方式

```bash
cd d:/vibecoding/AI软件/star
pip install fastapi uvicorn httpx
DEEPSEEK_API_KEY=sk-xxx python -m uvicorn app:app --reload
# 浏览器打开 http://127.0.0.1:8000
```

注意事项：
- 首次启动会在 `data/` 目录自动创建 SQLite 文件
- 改了表结构需删除 `data/starbox.db` 重建
- 改了 config.py 需重启服务器（`--reload` 会自动重载 Python 文件）
- `sqlite3.Row` 对象只支持 `row["col"]` 语法，不支持 `.get()` 方法

---

## 八、已修复的 Bug 清单（按时间顺序）

| # | Bug | 根因 | 修复方式 |
|---|-----|------|----------|
| 1 | DEBUG_MODE 不生效 | 改 config.py 后旧进程未退出 | kill + 重启 |
| 2 | sqlite3.Row 没有 .get() | `row.get("era")` 报 AttributeError | 改为 `row["era"]` |
| 3 | era 列不在 letters 表 | 早期建表漏了列 | 重建表 + 添加列 |
| 4 | 信箱 500 Internal Server Error | 同 Bug 2+3 | 修复上述 Bug |
| 5 | 每日限流反复触发 | DEBUG_MODE 没绕过限流 | `if not DEBUG_MODE and not check_rate_limit` |
| 6 | 回信截断 80 字符 | `reply_preview` 做了 `[:80]` | 去掉截断 |
| 7 | 收藏按钮收藏了 "random" | mailbox 返回 `target_frequency` 而非实际 persona_id | 新增 `persona_id_used` 列，`save_reply` 时存储 |
| 8 | 收藏后下拉菜单为空 | `goDesk()` 没调用 `loadFavoritesToDropdown()` | 在 goDesk() 中添加调用 |
| 9 | 回信被 max_tokens 截断 | `max_tokens: 500` 太小 | 改为 `1024` |

---

## 九、尚未实现的部分

- 前端正式 UI 设计（当前是零 CSS 的裸 HTML 测试台）
- style.css 与 app.js 分离
- 多用户公网部署（当前本地单用户，device_id 隔离）
- APP_SECRET 鉴权
- 配额表差异化限流
- PostgreSQL 迁移（当前 SQLite，百人级无压力）
- 取消收藏角色（当前只支持收藏，不支持取消）

---

## 十、明日开发方向

1. **前端 UI 重构**：从裸 HTML 测试台升级为产品级界面
2. **信件时间线设计**：信箱视图的视觉排版与交互
3. **收藏夹增强**：按角色分组、取消收藏角色
4. **更多人设**：在 personas.json 中添加新角色
5. **回信质量调优**：Temperature、top_p 等参数微调
