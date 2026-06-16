# Agent Session Workboard 🧠

*[English](README.md) · [中文](README.zh-CN.md)*

让机器一直开着,**人在任何地方**打开浏览器、用一把密钥解锁,就能接管它上面跑着的所有 agent 对话:看 Codex / Claude Code 在干什么、打字回复、随时打断、开新的。本地会话和远程(经 SSH 连过去的)会话都在同一个界面里。

> 一个会话,就是**一个跑着 agent CLI 的 tmux pane**。整个工具只靠三个简单可靠的原语撑起来——`list-panes`、`send-keys`、`capture-pane`——本地跑或经 SSH 跑都一样。不用数据库,远程机器上也不留任何常驻进程。

---

## 快速开始

```bash
uv sync
uv run agentboard init        # 生成 ~/.agentboard/config.yaml
uv run agentboard web         # 本地 hub:http://127.0.0.1:8765
```

tmux 里已经有 agent 在跑?它们会自动显示出来。没有的话,点 **＋ New**(在任意项目分组里,或 **＋ New project…**)起一个。

### 从任何地方访问

```bash
uv run agentboard web --remote
# 🔐 会打印一个 bearer token 和访问 URL,形如
#    http://0.0.0.0:8765/?token=ab_xxxxxxxx
```

它会打印出 token、访问 URL,**还有一个能扫的二维码**——用手机相机一扫就能立刻登录(token 会存成 cookie,保留 30 天,所以每台设备只用扫一次)。token 丢了?随时跑 `agentboard token` 重新打印一遍(连二维码),`agentboard token --rotate` 则换一个新的。

接着用你顺手的方式把端口暴露出去,在手机/笔记本上打开这个 URL:

```bash
tailscale funnel 8765                        # 最省事:自动 HTTPS
cloudflared tunnel --url http://localhost:8765
ssh -R 80:localhost:8765 serveo.net          # 简单粗暴
```

加上 `--remote` 后,**所有**路由都要带 token(页面会跳转到登录页,`/api` 和 WebSocket 直接返回 401)。token 只生成一次,之后写回到你的配置里。

> **延迟说明(跨网络实测):** 同一 WiFi/局域网下很跟手;**换到别的网络**(另一个 WiFi、蜂窝流量)明显会慢一些——如果流量还得走中继就更慢(比如 Tailscale 直连被挡、退回 DERP 中继时)。这只影响**控制通道**(发消息、刷新屏幕)的手感,**不影响 agent 在主机上干活的速度**——它该多快还是多快。聊天用了乐观本地回显,让卡顿感没那么明显。

---

## 能做什么

仪表盘分两层:

- **🟢 实时(Live now)** —— 此刻正跑在 tmux 里的 agent(本地或 SSH)。可以直接接管:阅读、发消息、打断。
- **💬 对话(Conversations)** —— 你完整的 Codex/Claude 历史,来自它们的 JSONL 日志,涵盖所有项目。**配了 LLM 的话标题由 LLM 自动生成**(自动、带缓存);没配的话就退回到用开场白的第一句话当标题。**直接打字就能接着聊**——发一条消息,就会把已经关掉的对话拉起来恢复成一个实时 tmux 会话,并把消息送进去;不用再单独点一下 "Resume"。如果对话本来就在跑,则直接链到它的操作页。

其它:

- **看到所有会话** —— 跨本地 + SSH 各台机器,agent 排在前面,每条带一行摘要,未处理的事项会有角标提示。
- **聊天(Chat)** —— 读解析好的对话记录(本地 Codex/Claude 走 JSONL 日志,内容完整;远程则退回到屏幕截取),也能发消息。
- **终端(Terminal)** —— 真正能交互的终端(xterm.js 接 pty / tmux attach),还配了移动端按键行(方向键 / Tab / Enter / Esc / Ctrl-C)。
- **总结(Summarize)** —— 可选的一道 LLM 处理,针对单个对话生成:一个一眼能认出来的标题、历史回顾、下一步动作,以及**可能被漏掉的事项**(没收尾的 TODO / 没回答的问题)。结果带缓存,只有对话又长了才会重新生成。
- **新建 / 关闭(New / Kill)** —— 在全新的 tmux 会话里起一个 agent(目录选择器在 SSH 上也能用),或者把它关掉。

---

## 命令行

| 命令 | 作用 |
|---|---|
| `agentboard init` | 创建 `~/.agentboard/config.yaml` |
| `agentboard sessions` | 列出各台机器上的 agent 会话 |
| `agentboard send <machine> <name> <msg…>` | 往一个会话里打字发消息 |
| `agentboard new <machine> <cwd> [--command codex] [--name x]` | 起一个会话 |
| `agentboard kill <machine> <name>` | 关掉一个会话 |
| `agentboard summarize [-m machine] [-n name]` | 生成 LLM 总结卡片 |
| `agentboard token [--rotate]` | 打印访问 token + URL + 二维码(或换一个新的) |
| `agentboard web [--port 8765] [--remote]` | 启动 web hub |

---

## 配置

`~/.agentboard/config.yaml`:

```yaml
workspace:
  data_dir: ~/.agentboard

machines:
  - name: local
    type: local
    codex_home: ~/.codex
    claude_home: ~/.claude
    tmux: true
  - name: h200
    type: ssh
    host: h200          # 必须能直接 `ssh h200` 连上(用 ~/.ssh/config)
    codex_home: ~/.codex
    claude_home: ~/.claude
    tmux: true

llm:                    # 可选 —— 只用于标题和总结
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  api_key_env: DEEPSEEK_API_KEY

remote:
  enabled: false        # `web --remote` 会把它打开
  bind_host: "0.0.0.0"

auth:
  enabled: true
  bearer_token: ""      # 首次以 remote 方式运行时自动生成
```

远程机器上什么都不用装——全程靠 `ssh <host> tmux …` 来驱动,所以只要能用 SSH 密钥登上去、上面有个跑着的 tmux server 就够了。

---

## 隐私

- 所有状态都只存在本地 `~/.agentboard/` 下。
- 只有你主动要总结时,对话才会发给 LLM;而且密钥(API key、token、私钥)会先被脱敏。
- 远程访问默认关闭,开启后由 token 把关。

---

## 架构

```
agentboard/
  core/
    tmux.py         # list-panes / send-keys / capture-pane —— 本地或经 SSH
    sessions.py     # 发现并定位会话 = (machine, tmux name)
    transcript.py   # 把 Codex/Claude JSONL 解析成聊天回合;不行就退回屏幕截取
  intelligence/
    llm.py          # OpenAI 兼容客户端
    summary.py      # 每个会话一张 SessionCard(标题/回顾/下一步/遗漏项)+ 缓存
  auth/middleware.py# 默认拒绝的 bearer-token 鉴权
  web/app.py        # 一个控制 API + 一个 WebSocket;Jinja 页面
  cli.py · config.py · voice/
```

## 开发

```bash
uv sync --extra dev
uv run --extra dev pytest      # core、transcript、summary、auth、web
uv run --extra dev ruff check
```

## 参与贡献

这本来是个自用的小工具,所以你在真实场景里踩到的坑、觉得别扭的地方,正是最值得反馈的。**欢迎 issue、PR,也欢迎点个 ⭐ star** —— 发现 bug 或有想法就开个 issue,或者直接提 PR。

## 许可

MIT
