# 客来来

**XCMAX 的本地账号连接与收发工具。**保存外部账号授权，接收通道消息，执行宿主已批准的发送，保留可查询的原始回执。

界面保留 **账号连接、统一聊天、XCMAX 授权**。统一聊天汇总多个账号的会话，支持按账号筛选、添加明确账号的通道联系人、同步已接入的收件箱、查看消息和查询原发送请求；业务处理、员工权限、审批及对外发送入口统一放在 XCMAX。

## 产品边界

- 一个本地工具实例绑定一个明确工作区；同平台可配置多个账号，每个账号拥有稳定的 `connection_id`。
- 账号连接、适配器、入站、联系人、出站幂等及回执全部携带连接 ID，不自动选择“第一个账号”。
- 复用现有持久发送账本。结果不确定时查询原请求，不自动再次发送。
- 独立注册、密码登录、订阅、CRM、销售、财务、业务 AI、自动回复、工作流市场及原生坐标发送入口已移除。
- 历史业务数据留在原数据目录；删除账号清除其凭据，保留用于读取历史消息的连接归属记录。
- 客来来不运行第二个 Agent，也不建立另一套企业审批。

## 成熟组件与版本

| 能力 | 组件 | 锁定版本 | 许可证 |
| --- | --- | --- | --- |
| 系统凭据库 | [keyring](https://github.com/jaraco/keyring) | 25.7.0 | MIT |
| 凭据认证加密 | [cryptography](https://github.com/pyca/cryptography) / Fernet | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| 标准 OAuth / PKCE / token 刷新 | [Authlib](https://github.com/authlib/authlib) | 1.9.10 | BSD-3-Clause |
| Authlib 异步 HTTP 传输 | [HTTPX2](https://github.com/pydantic/httpx2) | 2.16.2 | BSD-3-Clause |
| 账号配置表单与校验 | [react-jsonschema-form](https://github.com/rjsf-team/react-jsonschema-form) / AJV8 | 6.11.1 | Apache-2.0 / MIT |
| 桌面运行时 | [Tauri](https://github.com/tauri-apps/tauri) | 2.12.7 | Apache-2.0 OR MIT |
| 桌面协议唤起 | [Tauri deep-link / single-instance](https://github.com/tauri-apps/plugins-workspace) | 2.6.3 / 2.5.5 | Apache-2.0 OR MIT |
| 自包含 Python 服务打包 | [PyInstaller](https://github.com/pyinstaller/pyinstaller) | 6.22.3 | GPL-2.0-or-later，附发行例外 |
| 浏览器流程回归 | [Playwright](https://github.com/microsoft/playwright-python) | 1.62.0 | Apache-2.0，仅测试环境 |
| 外部渠道网关 | [Chatwoot](https://github.com/chatwoot/chatwoot/tree/v4.20.1) 官方账号 API | 4.20.1 / b2f94636 | MIT（企业版目录另有许可，未引入） |

React、TanStack Query、FastAPI、SQLite 与既有 HTTP 渠道适配器继续复用。产品代码只负责工作区/账号归属、宿主授权、平台协议适配、原子迁移和发送账本。以上核心组件均在本地进程中使用，不要求注册外部托管连接平台。

Python 依赖真相源为 `backend/pyproject.toml`，解析锁为 `backend/uv.lock`；容器使用从该锁导出的 `backend/requirements.lock`。前端与原生依赖分别锁在 `desktop/package-lock.json` 和 `desktop/src-tauri/Cargo.lock`。

## 账号如何保存

系统原生 keyring 保存凭据库主密钥，账号配置以 Fernet 密文保存于对应工作区的 `connections.sqlite3`。密文同时绑定工作区、连接 ID 和用途，其他账号不能复用复制过来的密文。

凭据 API 只返回元数据和掩码。没有可用的原生安全 keyring 时拒绝明文降级；无桌面环境必须显式注入持久的 `KELLAI_VAULT_KEY`。主密钥需单独妥善保管，遗失后不能用新密钥恢复旧密文。凭据库暂不可用时仍可停用账号。

Authlib 管理标准 OAuth 授权与 PKCE。授权事务有有效期、归属、配置版本和一次性消费检查；刷新按连接获得数据库 lease，更新采用版本检查。撤销时先本地停用，再尝试供应商撤销，分别报告结果。GitHub、Google、Microsoft 的标准授权连接支持账号鉴权；可发送哪些消息以渠道能力目录为准。

浏览器和桌面自动化由 XCMAX 执行器负责。未绑定真实执行器的浏览器连接不能标为可用，也不能回退到旧原生坐标发送。

## 从 XCMAX 使用

1. 启动 XCMAX，在客来来工具中发起连接。
2. 打开客来来，选择“接收连接请求”。双方通过本机一次性交接建立短期操作者会话。
3. 在“XCMAX 授权”中选择并确认访问范围：`channels.read`、`messages.read`、`messages.send`。
4. 添加外部账号，完成平台授权或填写凭据，并验证连接。
5. 在统一聊天中查看会话；在 XCMAX 中选择明确账号和联系人，发起受控发送并核对回执。

旧协议的客户资料权限不会自动转换为新权限，升级后需要重新配对。普通网页不能依靠跨站请求创建本机操作者会话。此边界不隔离同一操作系统用户下的恶意本地程序。

`xcagi://data-sources` 唤起宿主已有客来来入口；`kellai://` 只用于唤起本工具，不承载密码、token 或免审批命令。

工具撤销先使本机授权立即失效。XCMAX 用绑定凭据检查专用授权状态，明确撤销才标记 `revoked`；离线和超时不会冒充撤销。宿主清理连接须由原操作者完成，历史请求号仍保留供原回执核验。

## 当前渠道能力

下表说明已实现的协议范围；账号是否获得平台权限、消息是否实际送达，分别由鉴权和原始回执确认。

| 渠道 | 当前可用范围 | 明确限制 |
| --- | --- | --- |
| 企业微信自建应用 | 内部成员应用消息、固定群机器人、验签入站 | 不等于外部联系人任意私聊 |
| 微信公众号 | 客服文本消息、明文验签回调 | 受公众号权限和回复窗口限制；AES 回调未接入 |
| 抖音 | 官方账号 OAuth 与企业号私信适配 | 需要 `enterprise.im` 等平台许可和真实会话，尚无实号验收 |
| Chatwoot | 文本发送、本机 API 分页收件、可选验签入站、原请求状态回读 | 上游平台能力取决于实际配置的收件箱 |
| Telegram / LINE / WhatsApp / Twilio | 原生发送适配 | 原生接收尚未实现；双向可通过 Chatwoot 收件箱接入 |
| 阿里云短信 / 小程序 | 模板通知适配 | 通用聊天文字发送会被阻止 |
| 淘宝 / 京东 / 拼多多 / 1688 | 保留旧配置及历史 | 缺少可验证的官方客服协议，发送保持阻止 |
| GitHub / Google / Microsoft OAuth | 账号授权、加密存储、刷新与撤销 | 不表示具备聊天发送能力 |
| 浏览器账号 | 预留明确连接身份 | 未绑定宿主真实执行器时为 `executor_required` |

Chatwoot 本机连接只需填写服务地址、Account ID、Inbox ID 和 API Access Token；无需公网桌面地址或回调密钥。后台和“同步收件箱”共用官方会话/消息 API，将收件与分页进度按工作区、连接和远端账号持久保存。每轮工作有界、不同会话轮转，消息先落入原 inbox 再推进游标；断网、落库中断或重启后只读续传。上游消息按创建时间排序，满页时会按消息 ID 区间补齐，避免回填旧日期的大编号跳过较小编号。

Chatwoot 已受理但 POST 响应丢失时，通过签名回调或 API 拉取发现原消息，再以认证 API 核对原请求号、账号、会话和内容，恢复同一账本；已知消息持续只读核对送达/已读状态。无法核对的请求继续保持未知，不重新 POST。供应商送达/已读与本地受理状态分别显示。其他仅提供回调的渠道仍需要供应商可达、经过验签的回调地址；本机监听不等于公网回调已经接通。

## 本地开发

需要 Python 3.11+、Node.js 22 和 uv。原生构建还需要 Rust 与 Tauri 对应系统开发依赖。

```bash
uv sync --locked --project backend --group test
KELLAI_PORT=8793 uv run --project backend kellai
```

另开终端：

```bash
cd desktop
npm ci --ignore-scripts --no-audit --no-fund
npm run dev
```

API 默认连接 `127.0.0.1:8793`。桌面开发页使用同源 Vite 代理；公开站点地址不能作为工具 API 地址。Linux 无桌面的单实例环境可使用 `docker compose up --build`，该模式保留 host loopback 网络，需显式注入主密钥。

## 升级与历史数据

先备份原数据目录及对应主密钥。历史只有一个工作区时可识别归属；检测到多个工作区时必须设置 `KELLAI_WORKSPACE_ID`，不会合并或猜测账号归属。

旧渠道 JSON 仅用于一次性迁移，完成加密持久化与校验后移除旧凭据来源；运行时不再合并环境变量与旧 JSON。既有消息、请求号和出站账本沿用原数据库。历史记录只能在账号归属明确时绑定到迁移连接；无法判定的记录不会被自动重新发送。

企业微信集中 Suite、抖音云桥接及独立 SaaS 业务运行入口已退出工具链。旧数据文件保留，账号需按当前支持的官方接入方式重新连接。

## 验证与打包

```bash
uv run --project backend --group test python -m pytest backend/tests -q
cd desktop
node --test tests/*.test.mjs
npm run build
```

后端测试覆盖账号与密文隔离、迁移回滚、OAuth 单次回调/刷新/撤销、入站归属、出站幂等和未知结果恢复；前端测试覆盖操作者切换、旧响应拒绝和禁止自动重放写操作。发布前还必须通过宿主联合回归。

### 宿主协议联合检查

`backend/tests/integration/check_host_protocol.py` 是显式运行的跨仓库检查，不由默认 pytest 收集，也不会自动克隆宿主、跟随远程 `main` 或安装依赖。先准备一个与当前工具配套的 XCMAX checkout，以及已按宿主依赖要求安装完成的 Python 环境（包括 FastAPI、SQLAlchemy、HTTPX、keyring、filelock 和 Uvicorn）。使用这个**宿主 Python**启动脚本；工具子进程另用本仓库的后端 Python。

从客来来仓库根目录运行，替换下面三个宿主参数；发布验证应使用明确的完整 commit SHA 和干净 checkout：

```bash
uv sync --locked --project backend --group test
KELLAI_TEST_HOST_CHECKOUT=/absolute/path/to/xcmax
KELLAI_TEST_HOST_PYTHON=/absolute/path/to/host-venv/bin/python
KELLAI_TEST_HOST_REVISION=replace_with_the_exact_40_character_host_commit
"$KELLAI_TEST_HOST_PYTHON" backend/tests/integration/check_host_protocol.py \
  --host-checkout "$KELLAI_TEST_HOST_CHECKOUT" \
  --expected-host-revision "$KELLAI_TEST_HOST_REVISION" \
  --tool-python backend/.venv/bin/python
```

`--host-checkout`、`--tool-python`、`--expected-host-revision` 也分别支持环境变量 `KELLAI_TEST_HOST_CHECKOUT`、`KELLAI_TEST_TOOL_PYTHON`、`KELLAI_TEST_HOST_REVISION`。Windows 可显式传入相应环境的 `Scripts/python.exe`。开发中需要检查未提交的宿主改动时，可追加 `--allow-dirty-host`；输出会明确记录 `host_dirty=true`，不能把它当成指定 commit 的发布证据。

脚本在隔离临时目录启动真实 loopback HTTP/ASGI 服务，使用真实 SQLite 用户会话、生产身份解析器与隔离 Chatwoot 协议服务，检查单次交接、最小权限、账号隔离、API 拉取入站、原请求幂等、发送响应丢失后的只读恢复、真实 SQL 审批消耗和 Agent 重载后的原回执核验。成功时输出实际检查列表，并在输出的 `runtime` 目录保存 `result.json` 和服务日志。服务会在结束时退出，临时证据目录保留供复查。

测试只替换系统钥匙串的 I/O，仍执行生产安全后端选择逻辑；它不能证明真实操作系统钥匙串可用。测试不会使用真实平台凭据或发送外部消息，也不能替代平台账号与安装包验收。需要在 CI 使用时，应由调用方显式准备和固定两个 checkout，不依赖浮动的宿主分支。

浏览器回归使用真实本机后端、隔离的宿主传输与测试账号，不接触真实平台：

```bash
uv sync --locked --project backend --group browser
uv run --project backend --group browser playwright install chromium
uv run --project backend --group browser python desktop/tests/smoke_tool_ui.py
```

CI 从干净的已提交源码构建 Windows NSIS 与 macOS DMG 候选包，将完整 commit SHA、源码树与版本同时嵌入原生壳和冻结后端；安装或挂载后核对包内文件，并启动包内后端验证 `/health` 返回相同身份及父进程监测。候选包通过独立 CI 配置明确使用未签名模式，仅保存为内部 artifact，正式签名配置保持不变，不能作为正式发布证据。当前验证尚未覆盖安装后的 GUI 操作、真实系统钥匙串、协议唤起和平台账号验收。

```bash
uv sync --locked --project backend --group build
cd backend
uv run --group build pyinstaller --clean --noconfirm kellai-backend.spec
cd ../desktop
npm run tauri build
```

资源目录同时支持 Windows 的 `kellai-backend.exe` 与 macOS/Linux 的 `kellai-backend`。编译通过、模拟服务回归与真实账号验收是不同证据。真实平台接收、发送、失效重连、Windows/macOS 安装及协议唤起需用实际授权账号和安装包验证；未取得这些证据时，不标记为真实送达或已发布。
