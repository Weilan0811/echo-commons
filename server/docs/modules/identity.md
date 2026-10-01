# Identity 模块

## 职责和边界

Identity 模块加载和校验角色使用的版本化静态内容，提供 Agent Contract、角色档案、关系动态、能力声明和作者预置记忆。它负责回答“角色是谁、允许使用哪些静态能力、模型应遵守哪些基础规则”。

Identity 不保存玩家运行事实，不保存当前关系分数，不决定回复资格，也不生成 Agent Proposal。消息、角色状态、关系、记忆和情境数据由各自模块维护，Runtime 在构造快照时读取并组合。

## 资源和对象

资源根目录是 `server/config/identity/`，全局清单提供默认 baseline 和角色清单，角色目录提供独立资源。当前支持的资源类型包括：

- `agent_contract`（旧 schema 也接受 `chat_baseline`）：公共 Agent Contract，提供稳定的身份、事实、记忆和能力前提；本次调用的输出格式由 Agent Harness 另行加入；
- `character_profile`：角色档案和表达基础；
- `relational_dynamics`：角色关系表现方式；
- `character_capabilities`：静态能力名称、说明、参数和 `action_kind`；
- `character_memory_preload`：作者预置的角色记忆；
- `character_identity`（旧 schema）或 `character_bundle`（当前角色清单）：角色资源组合元数据。

核心对象如下：

| 对象 | 作用 |
|---|---|
| `IdentityResource` | 一份带 YAML 元数据和 Markdown 正文的版本化资源 |
| `IdentityCapability` | 一项静态能力声明 |
| `CapabilitiesResource` | 能力资源及其版本信息 |
| `AuthoredMemory` | 角色资源包中的预置记忆页 |
| `MemoryPreloadResource` | 预置记忆资源及其版本信息 |
| `CharacterIdentity` | 一个角色的档案、关系动态、能力和预置记忆组合 |
| `IdentityCatalog` | 已校验的默认 baseline 和角色索引 |

每份资源具有 `schema_version`、`resource_type`、`resource_id`、`content_version`、`status`、`locale`、`updated_at` 和 `source_ref` 等元数据。`status` 当前支持 `draft`、`active` 和 `retired`。

## 加载和校验

`load_identity_catalog` 通过一条路径读取资源，先校验清单，再校验默认 baseline 和角色资源，最后构造不可变 `IdentityCatalog`。校验包括：

1. 文件路径、资源类型和资源标识是否符合清单；
2. schema 版本和 semver（语义版本）格式是否支持；
3. 必需元数据是否齐全，资源状态和更新时间是否合法；
4. 角色引用的档案、关系动态、能力和预置记忆是否存在且类型正确；
5. 能力参数、记忆类型、可见性和内容是否符合资源规则；
6. 同一清单中是否出现重复资源或无法解析的额外字段。

启动加载或运行中按角色构建失败时抛出 `IdentityConfigurationError`。调用方必须报告稳定配置错误，不能用空角色、伪造能力或隐式默认内容继续调用 Agent。

## 对外投影

Identity 对外提供两种主要投影：

```text
IdentityCatalog
  → ContextSnapshotBuilder
  → ContextSnapshotV2.identity / CapabilityView
  → Conversation AgentInvocation

IdentityCatalog
  → GraphSnapshotAssembler / Reflection context
  → GraphContextSnapshot.identity
  → Reflection NodeInput
```

Conversation 快照把公共 baseline、角色档案、关系动态和能力定义投影为 `IdentityContext` 与 `CapabilityView`，Harness 再把公共 Contract 和三份角色资源分别写入 Prompt 区块。Reflection 使用同一组静态资源，但通过图快照和 `NodeInputProjector` 只暴露当前节点需要的字段。

资源版本写入快照的 `source_versions`，参与调用指纹和审核时的来源检查。`CharacterIdentity.content` 只是角色档案和关系动态的聚合视图；Prompt 组装会保留各资源的独立边界。它不创建新的事实版本，也不替代各资源自己的 `content_version`。

## 能力边界

Identity 只声明能力，Runtime 决定本次 Invocation 可以使用哪些能力。Conversation 当前只允许 Runtime 明确组合的 `memory_search` 工具；Reflection 节点根据节点 Contract 读取静态能力和相关输入。模型不能因为看到能力声明就自行写数据库或改变世界事实。

`CapabilityDefinition.action_kind` 描述能力的静态类别：`read`、`proposal` 或 `external`。它不等于一次实际执行结果，实际执行仍由对应 Runtime 端口负责。

## 版本和运行事实的分工

| 内容 | 版本 owner（所有者） | 是否进入 Identity 投影 |
|---|---|---|
| Agent Contract、角色档案和关系动态 | Identity 资源 `content_version` | 是，作为静态输入 |
| 会话上下文 | Conversation `context_version` | 否 |
| 世界和回复资格 | World / `CharacterState` 版本 | 否 |
| 角色叙事状态 | `CharacterStateEntry.state_version` | 否 |
| 玩家关系 | `RelationshipState.state_version` | 否 |
| 消息、段摘要和记忆 | 各自来源版本 | 否 |

这样可以在审核时分别判断静态内容和运行事实是否仍然有效，避免把多个版本字段复制进 Identity 对象。

## Trace 和日志

Identity 记录资源加载成功、配置错误、角色查找和快照投影失败的安全事件。Trace 只保存资源标识、版本、角色标识和错误码，不保存完整 Markdown、Prompt、密钥或预置记忆正文。需要查看内容时直接读取版本化资源文件。

## 测试入口

- `server/tests/test_identity_loader.py`：清单、资源版本、状态和错误处理。
- `server/tests/test_identity_content_layout.py`：角色资源目录和内容布局。
- `server/tests/test_xiaojin_character_agent.py`、`server/tests/test_xiaojin_regression_fixture.py`：Conversation 快照和 Prompt 投影。
- `server/tests/test_reflection_snapshot.py`：Reflection 快照投影。
