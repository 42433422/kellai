# 客来来渠道代码审计与 Chatwoot 复用说明

审计基线：`cbe783af897a746320f220a8fe4bbea7f66d5976`。范围为 `backend/app/channels` 全部原有适配器、渠道配置与注册中心，以及对应回调/授权/存储调用链。本轮逐个检查实际发送方法、接收方法和连接测试；不能把渠道名称、配置字段、注释或本地签名生成当成外部收发已验证。

## 1. 渠道能力矩阵

代码能力由 `backend/app/channels/capabilities.py` 定义，经 `ChannelRegistry.list_channels()` 返回；短信的 `message_types` 由当前租户实际保存的 provider 动态收窄。`live_verified=false` 表示本轮没有使用真实平台账号向外部客户发信；`connected` 的远端凭据鉴权也不能等同于客户已经收到消息。

| 渠道 | 仓库实际发送协议/入口 | 实际接收路径 | 本轮代码结论与剩余条件 |
|---|---|---|---|
| 企业微信 `wework` | `/cgi-bin/message/send` 内部应用消息；固定群机器人 webhook；新增复用 `wework_suite.get_corp_access_token(team)` 的第三方授权成员回发 | 已验签解密的企业回调 → tenant inbox | 可实现内部成员收发。单独 `kf_url` 只是接待链接；不是微信客服发信凭据，更不等于个人微信好友聊天。需要企业授权、agent 可见范围与真实成员验收。 |
| 微信 `wechat` | 公众号 `/cgi-bin/message/custom/send`；显式 `@chat` 才可使用固定群机器人 | 公众号明文模式校验回调 → tenant inbox | 当前 AES 安全模式回调明确拒绝，尚未接入。公众号客服接口需要对应权限与平台回复窗口。开放平台扫码 OAuth 仅证明身份授权。删除了任意个人 contact_id 自动落到固定群的错误兜底。 |
| 抖音 `douyin` | 企业号 `/enterprise/im/message/send/`；小程序经营私信 `/im/send/msg/`；既有远端桥接；既有原生桌面路径 | 官方回调、远端 inbox 或网页捕获，按已有模式处理 | 混合传输。官方路径需相应 scope、企业号 token，以及正确的 owner/conversation/server_message 上下文；网页联系人需要原生运行时。`resolve_send_capability` 在创建发送账本前识别 desktop 目标。不能将整个抖音渠道一概视为云端 API 或一概视为桌面。 |
| 微信小程序 `miniprogram` | `/cgi-bin/message/subscribe/send` | 原适配器仅消费本地 inbox；所称云函数桥未形成内置入站实现 | 已有的是用户订阅的模板通知，需 template_id、订阅许可与正确模板字段，不支持通用自由文本会话。目录标为 outbound_only / template，自动回复关闭。 |
| 短信 `phone` | Twilio Programmable SMS 文本短信 / 阿里云 SendSms 显式模板短信 | 原适配器仅消费本地 inbox | UI 已用真实服务商凭据替代虚构的外呼线路，支持按 provider 切换字段和必填项。Twilio 文本可走统一发送入口；阿里云仅保留底层显式 `template_param`，模板发送 UI 尚未实现，通用文本入口阻断。仅保存凭据不能标已连接，不提供语音通话。上行短信及送达回调可复用 Chatwoot 对应短信收件箱，原生适配器尚无此能力。 |
| Telegram | Bot API `sendMessage`；`getMe` 鉴权 | 原代码仅 `list_inbox`，并没有注释所称的 `getUpdates` 或内置 webhook | 直连发信代码保留，native receive=false。双向收发复用 Chatwoot Telegram inbox，仍需 BotFather token、机器人触达权限和真实 chat。 |
| LINE | Messaging API `/v2/bot/message/push` | 原代码仅 `list_inbox`，无内置签名入站处理 | 直连推送代码保留，native receive=false。双向收发复用 Chatwoot LINE inbox，仍需 LINE Official Account 与平台允许的目标。 |
| WhatsApp | Cloud API `/{phone_number_id}/messages` | 原代码仅 `list_inbox`，无内置订阅校验、签名消息回调和状态回调 | 直连文本发送保留，native receive=false。双向收发复用 Chatwoot WhatsApp inbox；需要商业账号、号码、Meta 授权，窗口外发信另需获批模板。 |
| 淘宝 | 旧方法为 `taobao.tmc.message.produce` | 原代码仅本地 inbox | TMC 事件生产不是买家私聊；旧连接测试只生成本地签名。本轮 send=false / blocked，直接调用也明确拒绝且不外发。不能靠换一个 SDK 获得平台未授权的聊天权限。 |
| 京东 | 旧实现构造 `jingdong.message.send` 请求，但缺完整 OAuth/授权链，空响应也可能返回 success | 原代码仅本地 inbox | send=false / blocked。旧本地签名测试不能证明鉴权。需有实际平台批准的聊天协议、身份授权和真实收发证据后重新开放。 |
| 拼多多 | 旧 `/routerjson` 发送请求缺完整开放平台方法/授权；错误体检查不足 | 原代码仅本地 inbox | send=false / blocked。保留已有配置和历史消费，不把不完整协议当作可用客服消息通道。 |
| 1688 | 旧 openapi 请求与消息目标未形成可验证聊天协议；只检查 errorMessage 就可能判成功 | 原代码仅本地 inbox | send=false / blocked。旧连接测试仅生成本地签名。需要完整官方授权协议及验证。 |
| 新增 Chatwoot | 官方 Application API：读取固定 account/inbox 的会话，然后 POST outgoing text message | 官方签名 `message_created` / `message_updated` webhook → 持久 inbox → 统一 ingest/AI 队列；状态事件持久化后认证读回 | 本轮实现的成熟渠道网关桥。Chatwoot 处理 Telegram、LINE、WhatsApp、Email、SMS 等已配置平台的认证和协议。客来来复用自己的客户、消息、AI、outbox 和界面，不引入 Chatwoot 的 AI runtime。每个团队当前固定绑定一个 account/inbox。 |

`email`、`sms` 曾出现在配置/UI 文案中，但不是原有十二个已注册适配器。短信实现对应 `phone`；电子邮件可经已配置的 Chatwoot Email inbox 接入。不能根据菜单名称推断存在独立收发实现。

## 2. 已确认并修复的公共缺口

1. **租户间复用 HTTP 客户端。** 旧 registry 只按 channel_type 缓存实例，Telegram URL token、LINE/WhatsApp Authorization header 等可能固定为第一个租户。现在按 tenant + 渠道 + 有效配置指纹缓存。保存配置淘汰缓存；关闭时统一释放客户端。在途请求使用其原配置，不把旧 token 与新网关标识混用。
2. **服务端环境凭据被新租户继承。** `KELLAI_CHANNEL_ENV_TEAM_ID` 明确指定归属；否则只在可证明单租户的旧数据迁移场景允许兜底。多租户或未知归属不继承服务器 bot token。抖音的服务级 OAuth App 与租户账号 token 分开：已启用的 bridge 可使用公共平台 App，但具体用户/企业 token 仍按团队保存。
3. **UI 与执行配置优先级不一致。** 原 `get_field` 是 env 优先，`get_all` 又是 JSON 优先。现在都是已保存值优先，显式空值表示撤销，不再回退到旧 env；同义字段同时更新，避免 app_secret/client_secret 互相复活。
4. **原始密钥返回前端。** 提供 `public_config` / `redact_config`；`********` 是保留原值的显示占位符，不能写成真实 token。特殊业务在调用远端验证前也必须解析该占位符。
5. **保存失败伪成功。** 文件写入使用独立临时文件、fsync、原子替换；磁盘写入异常不再只记录日志后返回成功。原有进程内锁仍负责同进程读改写。该 JSON 层不是分布式并发配置数据库。
6. **消息 POST 盲目重试。** 共享 HTTP 客户端仅对 GET/HEAD/OPTIONS 保留网络/5xx 重试。发送的超时、5xx、无有效成功凭据的响应标为 unknown，不自动重发。发送前校验失败与平台明确拒绝标为 failed / definitely_not_sent。
7. **异常 JSON 或空成功体被当成成功。** HTTP 状态和 JSON 对象结构先验证；Telegram、WhatsApp、Chatwoot、抖音等要求真实消息标识。协议仅提供 errcode=0 受理确认的通道不编造消息 ID，也不声称最终送达。
8. **企业微信取 token 自锁。** 旧 `_auth_headers` 再次获取 token，递归进入 `/gettoken` 并等待同一个刷新锁。移除该多余预取；query 参数携带 token，真实 MockTransport 用例验证取 token 与发信均可完成。
9. **连接测试参数不兼容。** routes 给全部适配器传 team_id，原来多数 test_connection 不接受此参数。统一接受参数；鉴权成功标 authenticated；机器人 URL/客服链接/本地签名只算 configured。
10. **企业第三方授权入站与发信凭据脱节。** 复用既有 suite 授权表、tenant 绑定 agent_id 和 corp token 交换。手动 CorpID 与第三方授权 CorpID 不一致时拒绝发送。此链路仍限定企业内部成员。
11. **接收注释代替真实实现。** 原生 Telegram/LINE/WhatsApp/SMS/小程序没有接收协议的地方明确标为缺失；由 Chatwoot 已有平台实现提供一条可部署的双向路径，不再重复手写五套入口。
12. **错误的收件人兜底。** 微信个人目标不能落到固定群 webhook；企微单成员接口拒绝 `@all` 和多个成员列表，避免部分成功却报告全部失败。
13. **远端抖音桥接绕过发送账本。** 同一 idempotency_key 从桌面/服务端发送入口透传为桥接 client_request_id；云端以独立 tenant outbox 受理。客户端只使用 provider_message_id，不把云端本地消息 ID 当平台回执。HTTP 200 中的失败/unknown 回执不会被丢弃或改成成功；桥接内部执行标志防止远端配置造成回环，并禁止云端进入原生桌面发送。
14. **短信配置 UI 与真实适配器脱节。** 原 `phone` UI 只有 `line1/line2/line3` 外呼线路，且认证方式为 `select`，不会打开只接受 form/both 的独立配置弹窗。现在注册中心提供服务商 schema，前端读取枚举、默认值、条件字段和条件必填项，真正保存 Twilio/阿里云凭据；provider 切换不会把已保存掩码写成密钥。阿里云不再把任意文本猜成 `content` 模板变量，未显式提供合法 JSON 参数在外发前拒绝。

## 3. Chatwoot 复用选择和协议依据

选定上游：[`chatwoot/chatwoot`](https://github.com/chatwoot/chatwoot)，版本 **v4.20.1**，提交 **`b2f94636d325a126a67c6c4c808303d8aa8cbeea`**。

许可证：根 LICENSE 明确指出，`enterprise/` 和第三方组件以外的代码为 MIT/Expat；enterprise 目录采用其单独许可证。这里通过部署实例的官方 API 复用渠道能力，没有复制整个 CRM 或引入额外 Agent runtime。

沿用仓库已有 HTTPX、Pydantic、FastAPI、SQLite 与消息处理服务，桥接代码只负责规范化、校验和调用。额外引入另一套 Agent SDK 不会增加平台授权能力，还会带来第二份会话/任务状态，因此本轮没有这样做。

官方依据（同时核对了选定 tag 的源码，不能只看滚动文档）：

- [v4.20.1 release](https://github.com/chatwoot/chatwoot/releases/tag/v4.20.1)
- [精确提交](https://github.com/chatwoot/chatwoot/commit/b2f94636d325a126a67c6c4c808303d8aa8cbeea)
- [许可证边界](https://github.com/chatwoot/chatwoot/blob/v4.20.1/LICENSE)
- [官方渠道及 inbox 配置](https://www.chatwoot.com/hc/user-guide/articles/1677492191-adding-inboxes)
- [Webhook 创建及签名说明](https://app.chatwoot.com/hc/user-guide/articles/1677693021-how-to-use-webhooks)
- [选定版本实际签名实现](https://github.com/chatwoot/chatwoot/blob/v4.20.1/lib/webhooks/trigger.rb)
- [Webhook listener 传递 secret 和 delivery ID](https://github.com/chatwoot/chatwoot/blob/v4.20.1/app/listeners/webhook_listener.rb)
- [发送消息 API](https://developers.chatwoot.com/api-reference/messages/create-new-message)
- [读取 inbox API](https://developers.chatwoot.com/api-reference/inboxes/get-an-inbox)
- [message_builder 接受 content_attributes / echo_id](https://github.com/chatwoot/chatwoot/blob/v4.20.1/app/builders/messages/message_builder.rb)
- [Message webhook_data 实际字段](https://github.com/chatwoot/chatwoot/blob/v4.20.1/app/models/message.rb)
- [认证消息读取返回 status](https://github.com/chatwoot/chatwoot/blob/v4.20.1/app/views/api/v1/models/_message.json.jbuilder)
- [before/after 精确消息查询](https://github.com/chatwoot/chatwoot/blob/v4.20.1/app/finders/message_finder.rb)

### 不应被 SDK 包装掩盖的两个事实

`echo_id` 在这个版本是临时 accessor，不是持久化的幂等键，也不是平台承诺的去重机制。本实现额外保存 `content_attributes.kellai_request_id` 便于追踪，真正的外发去重仍在客来来的 SQLite outbox。

标准 `message_updated` 顶层 webhook payload 没有 message status。不能默认认为这个事件代表 delivered。本实现读取认证后的会话消息 API，精确筛选 message_id、inbox_id、conversation_id、outgoing/private 标志，只有真实 status 才推进回执。查询失败保持待处理；未找到原出站账本或缺少匹配上下文不能创造成功。

## 4. 配置与闭环行为

客来来 `chatwoot` 渠道保存五个必要字段：`base_url`、`account_id`、`inbox_id`、`api_access_token`、`webhook_secret`。需要启用该渠道。服务地址使用 HTTPS；本机开发可使用 loopback HTTP。

在 Chatwoot 设置 Webhook：

`POST https://<kellai-host>/api/kellai/webhook/chatwoot/<team_id>`

订阅 `message_created` 和 `message_updated`，把该 webhook 自己的 secret 填入客来来；不是拿 API token 代替 webhook secret。官方签名为：

`X-Chatwoot-Signature = sha256=HMAC-SHA256(secret, timestamp + "." + raw_body)`

同时验证 `X-Chatwoot-Timestamp`，时间偏差不超过五分钟，严格使用原始请求字节。签名通过后还校验 account、inbox、conversation inbox；错误团队配置、错 inbox、私有备注和外发 echo 不进入自动回复。

收件人使用不透明标识：

`chatwoot:<gateway_id>:<account_id>:<inbox_id>:<conversation_id>`

其中 gateway_id 是规范服务地址的 SHA256 前十六位，与 token 无关。更换服务实例不能把旧会话地址错误映射到新实例相同数字 ID 的会话。入站去重键和待处理状态事件也按网关命名空间隔离。回执匹配同时冻结 gateway、account、inbox、conversation 四项。

入站先落已有 SQLite inbox，再调用统一 `channel_ingest.sync_inbox` 完成客户归属、消息保存和 AI 任务入队；入队失败不消费原 inbox。重复 webhook 不创建第二份消息/回复任务。附件保留来源元数据；当前文本回复 runtime 不对未解析附件生成回复。

出站先由既有统一发送服务保留 outbox 幂等请求，再执行一次 Chatwoot POST。HTTP 受理只报告 accepted。状态回调独立持久化，认证读回后推进 sent/delivered/read/failed。失去 ACK 的 unknown 请求不能自动重发；同一请求 ID 的重试只读取原账本。

### 短信配置与实际产品边界

历史渠道类型继续使用 `phone`，设置页显示为“短信（Twilio / 阿里云）”，不改变已有客户渠道归属。选择 Twilio 后填写 `account_sid`、`auth_token`、`from_number`；发送号码需有短信能力，使用 E.164 格式。连接测试只做真实账号鉴权，普通文本短信走统一发送入口和既有 outbox。API 返回 SID 只证明平台受理，不能当成手机已收到。

选择阿里云后填写 `access_key_id`、`access_key_secret`、`sign_name`、`template_code`。签名和模板须经过平台审核。底层适配器只接受显式的 `template_param` 字符串值 JSON 对象，无变量模板也须显式传 `{}`；不会把自由文本自动装进猜测的变量名。**模板发送界面尚未实现**，当前通用文本发送入口因动态 `message_types=["template"]` 拒绝外发，没有另开绕过账本的模板 API。阿里云凭据的保存只算 configured，不声称已鉴权或送达。

两个原生短信适配方式都没有上行接收和送达回调入口，设置页不会显示“同步成功即双向接通”；原生同步按钮改为“需网关接收”。如需客户回复进入统一会话，可使用 Chatwoot 已接通的短信 inbox，其账号和平台支持范围仍需实际部署验收。

协议依据：[Twilio Message Resource](https://www.twilio.com/docs/messaging/api/message-resource)、[Twilio Auth Token](https://www.twilio.com/docs/iam/api/authtoken)、[阿里云 SendSms 官方快速接入](https://help.aliyun.com/en/sms/developer-reference/how-to-use-api-quickly)、[2017-05-25 SendSmsRequest 官方模型](https://aliyunsdk-pages.alicdn.com/apidocs/Dysmsapi/2017-05-25/java-tea/4.5.1/com/aliyun/dysmsapi20170525/models/SendSmsRequest.html)。

## 5. 仍需真实部署与账号验收的项目

- 本轮测试没有安装或登录真实 Chatwoot 平台账号，也没有替用户创建 Meta/LINE/Telegram 等商户授权。
- 先部署选定版本或已有兼容实例，在 Chatwoot 建立一个真实平台 inbox，再设置上述五项及公网 HTTPS 回调。平台本身的注册、OAuth、号码/机器人/官方账号资格、商户审批和平台窗口约束仍然有效。
- 当前每个 Kellai team 的 `chatwoot` 配置绑定一个 inbox。一个 team 同时接多个 Chatwoot inbox 需要把 channel connection 由单对象扩展为有独立 ID 的多实例配置；本轮不冒充已支持该产品能力。
- 当前桥接只发文本。新建客户/会话、发模板、媒体附件发送、群聊策略和更多会话协作能力不在此薄适配器的已实现目录中。
- 不能将官方公众号、企微内部成员、企微客服链接或扫码登录解释为“给任意个人微信好友发消息”。
- 四个电商渠道仍为明确阻断状态。本轮发现的是仓库协议缺口；这不等于断言平台不存在任何商业接口。必须取得对应授权和可验证协议，不能用未验证仓库绕过权限边界。
- JSON 配置层只提供进程内串行和磁盘原子替换；多进程同时改同一配置的协调仍应迁移到已有 SQLite/受控单写服务。此限制不影响采用 SQLite 唯一键与事务的消息和 outbox 去重。

## 6. 验证范围

`backend/tests/test_channel_gateway.py` 使用真实 HTTPX 请求构造/MockTransport 与真实 SQLite。覆盖多租户缓存和环境凭据隔离、配置优先级/清空/掩码/写失败、POST 超时不重发与安全 GET 重试、WeCom 取 token 无死锁、suite 授权回发、Chatwoot URL/header/body、目标绑定、回调 HMAC/时效/跨租户/跨 inbox 拒绝、重复事件、入队故障恢复、真实状态读取、回执账本推进，以及电商适配器禁止伪成功。

`backend/tests/test_phone_configuration.py` 从产品配置保存函数开始，验证两个租户的真实 Twilio HTTP 认证和号码映射、服务商切换时密钥掩码保留、动态能力阻断阿里云自由文本、动态接入必填项，以及模板参数拒绝/JSON 编码与缺少真实 BizId 时保持 unknown。

这些测试证明代码在受控协议下的行为，不替代真实账号的端到端验收。最终真实验收应保存一次入站 provider ID、一次出站 provider ID 和平台实际回执，并检查用户实际收到消息。
