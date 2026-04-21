# zhipin-geek

BOSS 直聘求职端 CLI — 在终端搜索职位、查看消息、发送简历、交换联系方式。

> 基于逆向工程的 BOSS 直聘 API，仅供求职者（geek）使用。

## 安装

```bash
# 推荐：uv
uv tool install zhipin-geek

# 或 pipx
pipx install zhipin-geek

# 或 pip（安装到当前 Python 环境）
pip install zhipin-geek
pip install "zhipin-geek[yaml]"   # 需要 --yaml 时
```

从源码安装：

```bash
git clone https://github.com/DuanXiaoWen/zhipin-geek.git
cd zhipin-geek
uv sync
```

## 功能

- 🔐 **登录** — 自动提取浏览器 Cookie（Chrome/Firefox 等），或扫码登录
- 🔍 **搜索** — 按城市/薪资/经验/学历/行业等筛选职位
- ⭐ **推荐** — 查看个性化推荐职位
- 📋 **详情** — 查看职位详情、浏览历史、已投递、面试邀请
- 💬 **消息** — 查看所有会话、未回复消息，实时发送消息（MQTT）
- 📎 **交换** — 发送简历、请求/接受手机号和微信交换
- 🤝 **打招呼** — 单个或批量向 Boss 打招呼

## 快速上手

```bash
# 登录
geek login

# 搜索职位
geek search "AI工程师" --city 上海 --salary 20-30K

# 查看未回复消息
geek unread

# 回复消息
geek reply 605029326 "您好，感兴趣，可以详细聊聊吗？"

# 同意简历/微信/手机请求
geek accept 629683122

# 主动发送简历
geek send-resume 605029326
```

## 所有命令

```bash
# ─── 登录 ─────────────────────────────────────
geek login                              # 自动检测浏览器 Cookie，失败则扫码
geek login --cookie-source chrome       # 指定浏览器
geek login --qrcode                     # 仅扫码登录
geek status                             # 查看登录状态
geek logout                             # 清除登录凭证

# ─── 搜索 ─────────────────────────────────────
geek search "golang"
geek search "Python" --city 杭州
geek search "Java" --salary 20-30K
geek search "前端" --exp 3-5年
geek search "AI" --degree 硕士 --industry 互联网
geek recommend                          # 个性化推荐
geek detail <securityId>                # 查看职位详情
geek show 3                             # 按搜索结果编号查看
geek export "golang" --format csv       # 导出搜索结果
geek history                            # 浏览历史
geek cities                             # 支持的城市列表

# ─── 个人中心 ──────────────────────────────────
geek me                                 # 个人资料
geek applied                            # 已投递职位
geek interviews                         # 面试邀请

# ─── 消息 ─────────────────────────────────────
geek messages [-n 20]                   # 所有会话及最近一条消息
geek unread [-n 50]                     # 未回复的消息（Boss 发来但未回复）
geek reply <friendId> "消息内容"         # 发送消息
geek chat-history <friendId> [-n 20]    # 查看双向聊天记录

# ─── 交换 ─────────────────────────────────────
geek send-resume <friendId>             # 发送附件简历
geek request-phone <friendId>           # 请求交换手机号
geek request-wechat <friendId>          # 请求交换微信
geek accept <friendId>                  # 同意对方的交换请求（自动识别类型）
geek accept <friendId> --reject         # 拒绝

# ─── 打招呼 ────────────────────────────────────
geek greet <securityId>                 # 向 Boss 打招呼
geek batch-greet "golang" -n 10         # 批量打招呼
geek batch-greet "Python" --dry-run     # 预览，不实际发送
```

## 结构化输出

所有命令支持 `--json` / `--yaml` 输出，适合脚本和 AI Agent 使用：

```bash
geek unread --json | jq '.data.unread[].friend.name'
geek messages --json | jq '.data.messages[0].lastMsgInfo.showText'
```

输出格式：

```json
{
  "ok": true,
  "schema_version": "1",
  "data": { ... }
}
```

## 技术说明

BOSS 直聘使用 **MQTT over WSS** 实现实时聊天（非 HTTP REST）：

- 服务器：`wss://ws6.zhipin.com:443/chatws`
- 认证：`page_token`（来自 getUserInfo）+ `wt2`（来自 /get/wt）+ Cookie header
- 消息格式：手写 Protobuf 编码（`TechwolfChatProtocol`）
- 交换请求接受参数：`mid`（消息 ID，非 `msgId`）

## License

Apache-2.0
