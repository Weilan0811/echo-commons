# Echo Commons 前端

本目录保存前端应用。前端负责页面展示、用户输入和非权威缓存；权威业务状态由后端维护，双方通过正式接口交换数据。

| 阅读目的 | 文档 |
|---|---|
| 框架、构建、数据层、样式、测试与部署的选择及理由 | [技术选型](docs/01-tech-selection.md) |
| 交给后端的接口缺口清单 | [接口缺口](docs/02-backend-interface-gaps.md) |
| 长期有效的架构取舍 | [架构决策](docs/adr/README.md) |
| 前端已交付内容与待办 | [状态](docs/status.md) |

整体阶段和前后端协作安排见 [项目推进计划](../docs/01-project-roadmap.md)。实际请求与响应以 [HTTP 参考](../server/docs/reference/http-api.md) 和 [OpenAPI 契约](../server/docs/reference/openapi.json) 为准，接入顺序见 [前端接入指南](../server/docs/guides/frontend-integration.md)。

`docs/01-tech-selection.md` 描述已确定的技术选择，`docs/02-backend-interface-gaps.md` 描述尚未实现的规划契约，两者不能混用：未实现的接口不写入选型的可用能力。