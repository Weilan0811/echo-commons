# 人物资源格式与作者示例

## 1. 资源层次与版本

根 manifest.yaml 登记 bundle_version、共同 agent_contract 和 blueprints。每个模板 manifest 再引用 profile、voice、relational_dynamics、capabilities、memory_preload 五份资源。路径相对各自 manifest 所在目录，最终须在资源根目录内，资源标识、引用和类型必须相符。默认从包内读取，外部根由 identity.root 指定。

schema_version 为 1。content_version、bundle_version 使用三段版本，可附预发布后缀，基线为 0.1.0。status 为 draft、active、retired；locale 非空，updated_at 使用合法 ISO 日期，source_ref 可选。加载器拒绝未知字段、重复标识、重复路径和类型不符；当前 draft 模板也可被显式实例化，status 不能被当成已经实现的发布权限系统。

Markdown 资源在 `---` 分隔的 YAML 元数据后写正文。共同字段为 schema_version、resource_type、resource_id、content_version、status、locale、updated_at、可选 source_ref。资源类型分别为 agent_contract、character_profile、character_voice、relational_dynamics。模板清单类型为 character_blueprint，能力 YAML 为 character_capabilities，预置记忆 YAML 为 character_memory_preload。

profile 描述身份和个人历史；voice 描述表达方式；relational_dynamics 描述关系倾向，不写入实际玩家关系分数。共同 agent_contract 提供回应规则。资源内容与当前会话、玩家及实例历史分别提供，作者不能通过模板为任意玩家编造共同经历。

## 2. 能力与预置记忆字段

模板 YAML 清单支持可选 `avatar_url`，缺失或 null 表示没有图片；非空字符串表示浏览器可读取的图片地址。模板与实例公开视图提供该字段，实例按实际绑定版本取得。服务不增加图片上传或文件代理入口；正文资源、能力和预置记忆不重复保存头像。

能力每项有 name、description、action_kind、parameters。name 唯一；action_kind 为 read、proposal、external，parameters 为字段 schema 对象。登记一种动作类别不会自动授权执行。能力最终与真实实现及本任务策略取交集。当前正式只读工具为 memory_search。

预置记忆每项必填 memory_id、memory_kind、content、visibility；类别为 fact、event、preference、promise、thread、other；可见性为 resident、recallable、private。confidence 默认 1，salience 默认 0.5，均 0—1。subject_kind、subject_id 默认 self，初始化解析为实际实例。memory_id 在资源内唯一；副本身份、归属和版本由初始化服务确定。

## 3. 一套完整合法作者示例

以下各段按标明的相对路径保存，可组成独立资源根。示例用简短作者内容说明格式。正式小槿完整资源见 [内置 manifest](../../src/echo_commons/resources/identity/manifest.yaml)。

根 `manifest.yaml`：

```yaml
schema_version: 1
bundle_version: 0.1.0
agent_contract:
  resource_id: default-chat
  path: common/agent-contract.md
blueprints:
  lin:
    resource_id: lin
    path: blueprints/lin/manifest.yaml
```

`common/agent-contract.md`：

```markdown
---
schema_version: 1
resource_type: agent_contract
resource_id: default-chat
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
---
按本次行动契约回应，引用实际可见材料，允许明确沉默。
```

`blueprints/lin/manifest.yaml`：

```yaml
schema_version: 1
resource_type: character_blueprint
resource_id: lin
display_name: 林
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
profile: {resource_id: lin.profile, path: profile.md}
voice: {resource_id: lin.voice, path: voice.md}
relational_dynamics: {resource_id: lin.relations, path: relational-dynamics.md}
capabilities: {resource_id: lin.capabilities, path: capabilities.yaml}
memory_preload: {resource_id: lin.memory, path: memory-preload.yaml}
```

`blueprints/lin/profile.md`：

```markdown
---
schema_version: 1
resource_type: character_profile
resource_id: lin.profile
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
---
你叫林，喜欢画画，也喜欢和朋友一起玩棋盘游戏。
```

`blueprints/lin/voice.md`：

```markdown
---
schema_version: 1
resource_type: character_voice
resource_id: lin.voice
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
---
说话简短自然，遇到不确定的信息会直接说出来。
```

`blueprints/lin/relational-dynamics.md`：

```markdown
---
schema_version: 1
resource_type: relational_dynamics
resource_id: lin.relations
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
---
你愿意倾听，但对具体人物的认识要来自实际交往。
```

`blueprints/lin/capabilities.yaml`：

```yaml
schema_version: 1
resource_type: character_capabilities
resource_id: lin.capabilities
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
capabilities:
  - name: memory_search
    description: 查询自己获准的记忆材料
    action_kind: read
    parameters:
      type: object
      properties:
        query: {type: string}
        limit: {type: integer, minimum: 1, maximum: 5}
      required: [query]
      additionalProperties: false
```

`blueprints/lin/memory-preload.yaml`：

```yaml
schema_version: 1
resource_type: character_memory_preload
resource_id: lin.memory
content_version: 0.1.0
status: draft
locale: zh-CN
updated_at: "2026-10-02"
memories:
  - memory_id: lin.likes-painting
    memory_kind: preference
    content: 你从小喜欢画画。
    visibility: resident
    confidence: 1.0
    salience: 0.8
    subject_kind: self
    subject_id: self
```

## 4. 实例化与维护

以上格式供预置文件资源使用。玩家自定义人物采用 [创作接口](http-api.md#6-自定义人物创作)，后端生成相同 CharacterBlueprint 资源结构并保存到数据库，无需玩家填写 YAML 元数据。三个正文及原始故事、采访可编辑至确认；确认后固定，当前只能复制为新草稿继续创作。材料与运行正文的关系见 [人物创作设计](../design/custom-character-authoring.md#2-作者操作与三份运行正文)。

加载成功后 catalog 提供模板；CharacterBootstrap 在正式事务中绑定模板版本、创建独立状态及记忆，并加入社群。同一模板产生两个实例时，self 分别解析，历史与关系不共享。资源读取或初始化失败不能留下半个实例。

修改作者资源不会自动修改已存在实例的绑定版本或过去任务快照。需要明确的实例更新设计，不能用重启偷偷替换已准备输入。增添模板的具体检查步骤见 [扩展指南](../guides/extending-the-platform.md)。
