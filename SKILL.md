---
name: zhipin-geek
description: Use the geek CLI (zhipin-geek) for BOSS 直聘 job search, recommendations, applications, chat, resume exchange, and MQTT messaging. Invoke when the user needs any BOSS 直聘 geek-side automation in terminal or scripts.
author: duanxiaowen
version: "1.0.0"
tags:
  - boss
  - zhipin
  - boss直聘
  - zhipin-geek
  - geek
  - job-search
  - recruitment
  - cli
---

# zhipin-geek — BOSS 直聘求职端 CLI

**命令名：** `geek`  
**PyPI / 包名：** `zhipin-geek`  
**凭证：** 浏览器 Cookie 自动提取，或扫码登录（`--qrcode`）。凭证默认在 `~/.config/boss-cli/`（与实现一致）。

## 安装

```bash
# 推荐：全局工具
uv tool install zhipin-geek
# 或
pipx install zhipin-geek

# 从本仓库开发
git clone https://github.com/DuanXiaoWen/zhipin-geek.git && cd zhipin-geek
uv sync
uv run geek --help
```

升级：`uv tool upgrade zhipin-geek` 或 `pipx upgrade zhipin-geek`。

## 鉴权（Agent 必读）

在执行任何需登录的子命令前，先确认已登录。**不要默认已有 Cookie。**

### 是否已登录

```bash
geek status --json | jq -r '.authenticated'
```

`geek status --json` 输出**扁平 JSON**（无 `ok` / `schema_version` 信封），顶层字段含 `authenticated`、`credential_present` 等。其它多数子命令的 `--json` 遵循 [SCHEMA.md](./SCHEMA.md) 信封，数据在 `.data`。

### 登录

```bash
geek login                              # 自动检测浏览器 Cookie，失败可走扫码
geek login --cookie-source chrome      # 指定浏览器
geek login --qrcode                     # 仅终端扫码
geek refresh --cookie-source chrome     # 仅刷新 Cookie（可选）
```

验证：

```bash
geek status
geek me --json
```

### 常见问题

| 现象 | 处理 |
|------|------|
| `__zp_stoken__` 缺失/过期、环境异常 | `geek logout && geek login`（优先浏览器会话；纯扫码可能缺部分 Cookie） |
| 未登录 / `not_authenticated` | `geek login` 或 `--qrcode` |
| 限流 (code=9) | 客户端内置退避，稍后重试 |
| 非 TTY 下输出成 YAML | 加 `--json` 明确要 JSON |

## 结构化输出与管道

机器可读输出使用统一信封，见仓库内 [SCHEMA.md](./SCHEMA.md)，业务数据在 **`data`** 下。

- Rich 表格、提示在 **stderr**，`--json` / `--yaml` 在 **stdout**，便于 `geek … --json | jq`。
- 非 TTY 时可能默认 YAML；脚本里务必加 **`--json`** 或 **`--yaml`**。
- YAML 可选依赖：`uv sync --extra yaml`（或安装带 `[yaml]` 的发行方式）。

## 命令速查

### 搜索与浏览

| 命令 | 说明 |
|------|------|
| `geek search <keyword>` | 职位搜索（`--city` `--salary` `--exp` `--degree` 等） |
| `geek show <index>` | 查看上次搜索结果中的第 N 条 |
| `geek detail <securityId>` | 职位详情 |
| `geek export <keyword>` | 导出搜索结果 |
| `geek recommend` | 个性化推荐（`-p` 分页） |
| `geek history` | 浏览历史 |
| `geek cities` | 城市列表 |

### 个人中心

| 命令 | 说明 |
|------|------|
| `geek me` | 个人信息 |
| `geek applied` | 已投递（`-p` 页码） |
| `geek interviews` | 面试邀请 |

### 沟通与聊天（MQTT）

| 命令 | 说明 |
|------|------|
| `geek chat` | 沟通过的 Boss 列表（`--json`） |
| `geek messages [-n N]` | 各会话最近一条消息 |
| `geek unread [-n N]` | Boss 发来尚未回复的会话（`--json` 里取 `friend.friendId`） |
| `geek chat-history <friendId> [-n N]` | 双向聊天记录 |
| `geek reply <friendId> "正文"` | **发送**文本消息（需有效登录与 MQTT） |
| `geek send-resume <friendId>` | 发送附件简历 |
| `geek request-phone <friendId>` / `request-wechat <friendId>` | 请求交换手机/微信 |
| `geek accept <friendId>` | 同意对方交换请求（`--reject` 拒绝） |

`friendId` 为整数，来自 `unread` / `messages` / `chat` 的 JSON，**不要**用加密 ID 或列表序号冒充。

### 打招呼

| 命令 | 说明 |
|------|------|
| `geek greet <securityId>` | 单个打招呼/投递 |
| `geek batch-greet <keyword>` | 批量（`-n` `--city` `--dry-run` `-y` 等） |

### 账号

| 命令 | 说明 |
|------|------|
| `geek login` / `logout` / `refresh` / `status` | 见上文 |

## 搜索筛选项（与实现一致）

常用：`--city` `--salary` `--exp` `--degree` `--industry` `--scale` `--stage` `--job-type`。具体可选值可用 `geek search --help` 或 `geek cities`。

## Agent 工作流示例

### 未读 → 上下文 → 回复

```bash
cd /path/to/zhipin-geek
uv run geek unread -n 10 --json | jq '.data.unread | length'
uv run geek chat-history 605029326 -n 25 --json
uv run geek reply 605029326 "您好，我对该职位很感兴趣，方便进一步沟通吗？"
```

### 搜索 → 详情

```bash
geek search "golang" --city 杭州 --json | jq -r '.data.jobList[0].securityId'
geek detail "<securityId>" --json | jq '.data.jobInfo | {jobName, salaryDesc}'
```

### 批量打招呼（先预览）

```bash
geek batch-greet "Python" --city 杭州 --dry-run
geek batch-greet "Python" --city 杭州 -n 5 -y
```

## 错误码

结构化失败时见 `error.code`（与 [SCHEMA.md](./SCHEMA.md) 一致），例如：`not_authenticated`、`rate_limited`、`invalid_params`、`api_error`、`unknown_error`。

## 能力与边界（相对本仓库）

- **支持**：实时发消息（MQTT）、发简历、交换联系方式、接受/拒绝交换、搜索、推荐、导出、浏览与投递相关查询。
- **不支持 / 未提供**：在 CLI 内编辑在线简历正文；公司主页 HTML 抓取；多账号并行配置。
- **账号安全**：避免对 BOSS 接口做无节制并发；`batch-greet` 内置间隔，单会话批量打招呼建议控制数量。

## Agent 安全提示

- 不要把原始 Cookie 贴进聊天日志。
- 优先本机浏览器提取；失败再扫码。
- 需要机器解析时统一使用 `geek … --json` 与 `jq`，并读 `.data`。
