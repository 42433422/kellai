# 客来来抖音小程序客服入口

这是一个可直接导入抖音开发者工具的原生小程序项目。首页通过
`button(open-type="im")` 拉起抖音 IM 客服会话。

## 导入

1. 打开抖音开发者工具。
2. 选择「小程序」→「导入项目」。
3. 项目目录选择本目录：`douyin-miniapp`。
4. 确认 AppID 为 `tt7e7708cae012a78501`。
5. 编译后使用真机预览测试客服入口。

## 客服主管抖音号

客服入口要求 `data-im-id` 必须是「能力 → 互动能力 → 消息管理 →
客服管理」中绑定的客服主管抖音号，普通客服成员账号不能代替。

配置文件：

`config/customer-service.js`

当前候选值来自已经开通的抖音客服工作台账号。如果真机调试出现
`params invalid` 或错误码 `14013`，请将 `supervisorDouyinId` 替换为
开放平台客服管理页面中绑定的客服主管实际抖音号。

## 测试前提

- 小程序为已上线企业主体应用。
- 已在开放平台启用「抖音 IM 客服」。
- 已绑定客服主管抖音号。
- 客服已登录抖音客服服务平台并切换为「在线」。
- 必须使用抖音 App 真机测试；模拟器不一定能完整拉起客服会话。

## 官方文档

- [抖音 IM 客服](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/open-capacity/operation/private-account/customer-service/douyin-im-customer-service)
- [button 组件 IM 客服能力](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/component/open-capacity/button-im-customer-service)
