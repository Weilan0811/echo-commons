# Echo Commons 前端

本目录保存前端应用。前端负责页面展示、用户输入和非权威缓存；权威业务状态由后端维护，双方通过正式接口交换数据。

完整安装与前后端连接步骤见根目录的[本地运行说明](../README.md#本地运行)。后端配置好并启动后，在本目录执行 `npm ci`、`npm run dev`，打开开发服务输出的页面地址。后端地址由 `VITE_API_BASE_URL` 指定；跨域来源配置在后端 `settings.toml` 的 `[server].cors_origins` 中。

| 阅读目的 | 文档 |
|---|---|
| 框架、构建、数据层、样式、测试与部署的选择及理由 | [技术选型](docs/01-tech-selection.md) |
| 页面结构、视觉语言与关键交互 | [页面与交互设计](docs/03-page-design.md) |
| 交给后端的接口缺口清单 | [接口缺口](docs/02-backend-interface-gaps.md) |
| 长期有效的架构取舍 | [架构决策](docs/adr/README.md) |
| 前端已交付内容与待办 | [状态](docs/status.md) |

整体阶段和前后端协作安排见 [项目推进计划](../docs/archive/implementation/01-project-roadmap.md)。实际请求与响应以 [HTTP 参考](../server/docs/reference/http-api.md) 和 [OpenAPI 契约](../server/docs/reference/openapi.json) 为准，接入顺序见 [前端接入指南](../server/docs/guides/frontend-integration.md)。

`docs/01-tech-selection.md` 描述已确定的技术选择，`docs/02-backend-interface-gaps.md` 描述尚未实现的规划契约，两者不能混用：未实现的接口不写入选型的可用能力。
