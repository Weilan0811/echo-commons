# Echo Commons 后端重构方向设计文档

> 文档性质：后端架构重构方案\
> 目标项目：Echo Commons / Persistent Character Agent Gameplay Platform\
> 重构原则：最大限度保护现有 Echo Server 的成熟结构，在其基础上演进为支持多角色、多人群聊、社会活动与 Gameplay 的 Persistent Multi-Agent Runtime。

---

# 一、重构目标

## 1.1 当前系统定位变化

现有 Echo Server 最初围绕单一角色“小槿”的陪伴体验构建，核心链路为：

```text
Player Message
      ↓
Conversation Runtime
      ↓
Xiaojin Character Agent
      ↓
Character Message Proposal
      ↓
Runtime Review
      ↓
Message Commit
      ↓
Memory / Reflection
```

该架构已经具备完整的 Agent Runtime 基础，包括：

- Agent Invocation；
- Context Snapshot；
- Model Gateway；
- Harness；
- Tool Loop；
- Proposal；
- Review；
- Commit；
- Task Lease；
- Retry / Recovery；
- Trace；
- Reflection Graph；
- Memory；
- Relationship。

新的 Echo Commons 不再以“单角色陪伴后端”为最终定位，而需要支持：

```text
Player
+
Multiple Character Agents
+
Persistent Group Chat
+
Shared Activities
+
Gameplay
+
Long-term Memory
+
Relationships
+
Private Knowledge
```

因此后端重构目标不是重新设计一套 Agent 系统，而是将当前：

> **Single Character Conversation Runtime**

泛化为：

> **Persistent Multi-Character Social & Gameplay Runtime**

---

## 1.2 核心架构原则

未来系统围绕以下闭环运行：

```text
Authoritative Runtime
        ↓
Objective Facts / Events
        ↓
Perspective Projection
        ↓
Character Observation
        ↓
Character Context
        ↓
Character Agent
        ↓
Message / Action Proposal
        ↓
Runtime Validation
        ↓
State Transition / Event Commit
        ↓
Authoritative Runtime
```

其核心思想为：

> Runtime 始终维护“客观发生了什么”；Character Agent 不直接读取整个世界，而只读取这些客观事实经过角色视角裁剪后的 Observation。

因此系统需要明确区分三层信息。

### Objective Truth

Runtime 权威维护的事实：

- 谁发送了消息；
- 谁执行了 Action；
- Gameplay 当前状态；
- Activity 结果；
- Character 当前状态；
- 已发生的重要 Life Event。

### Observation / Knowledge

某个角色能够看到、知道或被告知的部分。

同一个 Objective Event 对不同 Character 可以拥有不同 Visibility。

### Memory / Belief

角色对已观察事实的主观记忆、理解与总结。

因此：

```text
World Truth
    ↓
Observation
    ↓
Memory / Belief
    ↓
Decision
```

三层不得混为同一事实源。

---

# 二、现有 Echo Server 状态

## 2.1 可直接保留的核心基础设施

当前 Echo Server 已具有较成熟的 Runtime 分层结构，以下部分应原则上保留，不为“重构整洁”而重写。

### Agent Harness

现有 Harness 已处理：

- Prompt 编译；
- Model Step；
- Tool 调用；
- 输出修复；
- Step Budget；
- Deadline；
- Provider Error；
- Recovery。

未来多角色仍使用同一个 Character Agent Harness。

不创建：

```text
XiaojinAgent
XiazhiAgent
RionAgent
```

而统一为：

```text
CharacterAgent
     ↓
Character-specific Context
```

---

## 2.2 AgentInvocation

现有 `AgentInvocation` 已经是良好的 Provider-neutral 不可变调用边界。

当前包含：

```text
InvocationIdentity
InvocationScope
Context
ContextInput
OutputContract
ExecutionPolicy
Correlation
```

该结构应继续保留，仅扩展新的 Invocation Purpose 和 Scope。

---

## 2.3 Proposal → Review → Commit

这是当前 Echo Server 最值得保留的设计之一。

现有流程：

```text
Agent
 ↓
ProposalEnvelope
 ↓
ProposalRegistry
 ↓
ProposalReviewer
 ↓
Runtime Commit
```

未来 Gameplay 同样使用这套模式。

Character Agent 永远不能直接：

- 修改 World State；
- 修改 Game State；
- 修改 Relationship；
- 修改 Memory；
- 写入 Chronicle。

Agent 只提交 Proposal。

Runtime 才是事实 Owner。

---

## 2.4 Task / Lease / Recovery

当前 ConversationTask 已具备：

- task_id；
- lease；
- attempt_count；
- lease_generation；
- retry；
- deferred；
- stale result protection；
- worker fencing。

多 Character 系统中并发 Agent 调用会更多，因此这一套机制未来价值更高，而不是更低。

应继续保留：

> 一个 Character 的一次逻辑行为对应一个独立 Task。

---

## 2.5 IdentityCatalog

当前 Identity 模块已经具备：

```text
identity/
├── common/
│   └── agent-contract.md
│
└── characters/
    └── xiaojin/
        ├── profile.md
        ├── voice.md
        ├── relational-dynamics.md
        ├── capabilities.yaml
        └── memory-preload.yaml
```

`IdentityCatalog` 本身已经按照“多角色 Registry”设计，只是当前实际清单中只有小槿。

因此 Character 多实例化不需要推翻 Identity 模块。

---

## 2.6 Relationship Domain

当前 Relationship 已原生支持：

```text
observer_character_id
target_kind
target_id
```

其中：

```text
target_kind =
    ACCOUNT
    CHARACTER
```

因此底层数据模型已经允许：

```text
Xiaojin → Player
Xiaojin → Xiazhi
Xiazhi → Xiaojin
Rion → Player
```

Relationship Domain 本身无需重新设计。

主要问题在于当前 Context 和 Reflection 仍然默认：

```text
Character → Player
```

---

## 2.7 Memory

当前 `MemoryEntry` 和 `MemorySegment` 已经以：

```text
account_id
character_id
```

作为核心 Scope。

这意味着 Memory 系统天然能够承载：

> 同一个客观群聊，不同角色形成不同 Memory。

未来主要需要解除 Memory Sealing 中的“单参与角色”限制。

---

## 2.8 Conversation 已预留 Group 结构

当前 Domain 中已经存在：

```text
ConversationKind.DIRECT
ConversationKind.GROUP
```

同时数据库已经存在：

```text
conversation_participants
```

因此数据层已经具备群聊概念。

但执行层目前显式禁止 GROUP：

```text
GROUP Conversation
→ UnsupportedCapability
```

并且 Conversation Preparation / Commit / Memory Sealing 都包含：

```text
active_participants == 1
```

这一假设。

因此群聊不是从零新增数据模型，而主要是解除执行路径的单角色约束。

---

# 三、目标运行模型

## 3.1 从 Conversation-centric 转向 Event-oriented

当前系统主要围绕：

```text
Message
```

构造 Runtime。

未来应逐渐形成统一的 Event 语义。

建议定义 Provider-neutral：

```text
RuntimeEvent
├── event_id
├── event_kind
├── actor
├── targets
├── occurred_at
├── visibility
├── source
└── payload
```

不同模块产生不同事件：

```text
SocialEvent
ActivityEvent
LifeEvent
SystemEvent
```

例如：

```text
SocialEvent:
Xiaojin sent message

ActivityEvent:
Xiazhi submitted hint

LifeEvent:
Xiaojin completed commission
```

这里不要求立即将数据库完全改造成 Event Store。

可以继续分别存储：

```text
messages
activity_events
life_events
relationship_state
memory_entries
```

但在 Runtime 语义层统一投影为：

```text
ObservedEvent
```

即：

> Storage 可以专用，Runtime Contract 统一。

---

## 3.2 Objective Runtime

Objective Runtime 保存权威事实。

例如：

```text
GameSession #42
theme = "最适合约会的地方"

Xiaojin private_number = 82
Xiazhi private_number = 64
Player private_number = 35
```

或者：

```text
SocialEvent #502
actor = xiazhi
type = private_message
content = "我考试没及格"
visible_to = [xiaojin]
```

这些内容只能由 Runtime Commit。

Character Agent 无直接写权限。

---

## 3.3 Perspective Projector

未来建议新增核心 Service：

```text
PerspectiveProjector
```

它负责从 Objective Runtime 中构造：

```text
CharacterPerspective
```

输入：

```text
character_id
current time
conversation_id?
activity_id?
```

输出：

```text
CharacterPerspective
├── observed_events
├── visible_entities
├── known_facts
├── relationships
├── self_state
├── activity_view
└── uncertainty
```

Perspective Projector 回答的核心问题包括：

- 这个角色看到了哪些事件？
- 哪些 Private Event 对它可见？
- 它和当前参与者分别是什么关系？
- 它知道哪些信息？
- Activity 中哪些信息是公开的？
- 哪些信息属于自己的 Private State？
- 哪些事实根本不能进入该角色 Context？

设计原则：

> 不应依赖 Prompt 告诉模型“假装不知道”。

正确方案是：

> 不该知道的事实根本不进入 Character Perspective。

---

## 3.4 ContextSnapshotV3

当前 `ContextSnapshotV2` 建议保留思路并演进为 V3，而不是推翻。

目标结构可以为：

```text
ContextSnapshotV3
│
├── self
│   ├── identity
│   ├── state
│   └── capabilities
│
├── perspective
│   ├── observed_events
│   ├── known_entities
│   ├── relationships
│   └── known_facts
│
├── memory
│   ├── resident
│   ├── recalled
│   └── continuity
│
├── environment
│   ├── social
│   └── activity
│
└── action_space
    └── legal_actions
```

其中：

```text
identity
```

回答：

> 我是谁？

```text
perspective
```

回答：

> 我现在看到了什么、知道什么？

```text
memory
```

回答：

> 我经历过什么？

```text
environment
```

回答：

> 我现在处于什么活动和环境？

```text
action_space
```

回答：

> 我现在可以做什么？

---

# 四、核心重构点

## 4.1 Social Turn 与 Participation Scheduler

这是整个重构中最重要的部分。

当前运行模型为：

```text
InputBatch
    ↓
唯一 Character
    ↓
ConversationTask
```

需要改为：

```text
Social Event / Input Batch
          ↓
       Social Turn
          ↓
 Participation Scheduler
      ↙      ↓      ↘
 Xiaojin   Xiazhi   Rion
   yes       no      yes
    ↓                 ↓
CharacterTask   CharacterTask
```

### SocialTurn

建议新增：

```text
SocialTurn
```

用于表示：

> 一次需要多个角色判断是否参与的社会交互机会。

SocialTurn 保存：

- source event；
- conversation；
- candidate participants；
- frozen observation boundary；
- scheduling state。

### ParticipationDecision

对每个候选角色产生：

```text
ParticipationDecision
```

例如：

```text
Xiaojin:
respond

Xiazhi:
respond

Rion:
silent
```

只有被选中的角色才创建 ConversationTask。

---

## 4.2 ConversationTask 继续保持单角色

不要设计：

```text
MultiCharacterTask
```

一个 Task 继续对应：

```text
one character
one invocation
one proposal
```

这样现有：

- Task Dispatcher；
- Lease；
- Retry；
- Recovery；
- Trace；
- AgentResult；

均可继续复用。

变化只发生在 Task 上游：

```text
以前：
InputBatch → Task

未来：
InputBatch / Event
→ SocialTurn
→ N CharacterTasks
```

---

## 4.3 InputBatch 与 Task 解耦

当前一个 InputBatch 直接绑定一个：

```text
task_id
```

群聊后一个输入可能触发多个角色任务，因此需要调整。

推荐：

```text
InputBatch
      ↓
SocialTurn
      ↓
Task A
Task B
Task C
```

InputBatch 负责：

> 用户输入边界。

SocialTurn 负责：

> 这段输入引发的社会响应轮。

ConversationTask 负责：

> 某一个角色的一次 Agent 执行。

三者职责分开。

---

## 4.4 Conversation Commit 泛化

当前 T3 Commit 会验证：

```text
conversation.kind == DIRECT
participants == 1
participant.character_id == task.character_id
```

未来需要变成：

```text
conversation is active
task.character_id is active participant
character remains eligible
social turn remains valid
context boundary remains valid
```

不能再要求：

```text
participants == 1
```

同时允许：

```text
Task A
Task B
```

分别 Commit 自己的结果。

---

# 五、Character 系统泛化

## 5.1 Character Blueprint

当前 Identity 应正式解释为：

```text
CharacterBlueprint
```

其内容包括：

```text
Core Identity
Personality
Voice
Relationship Style
Life Scaffold
History Anchors
Gameplay Disposition
Secrets / Boundaries
Authored Memory
Capabilities
```

这些内容：

- 版本化；
- 作者定义；
- 相对稳定；
- 不属于运行时事实。

---

## 5.2 Character Instance

当前不建议新建一个巨大的 `character_instance` 表。

可以先将其定义为逻辑 Aggregate：

```text
CharacterInstance
=
Identity(character_id)
+
CharacterState(character_id)
+
Memory(character_id)
+
Relationships(character_id)
+
Community Membership(character_id)
```

未来如果确有必要，再增加统一 Instance Metadata。

这样可以最大程度保护现有结构。

---

## 5.3 Character Bootstrap

新增：

```text
CharacterSeed
CharacterCompiler
CharacterBootstrapService
```

用于批量创建不同角色。

典型流程：

```text
CharacterSeed
     ↓
Compiler
     ↓
Character Blueprint
     ↓
Validation
     ↓
Memory Preload
     ↓
CharacterState Initialization
     ↓
Community Membership
     ↓
Initial Relationships
     ↓
ACTIVE
```

---

# 六、Social Context 与 Knowledge Boundary

## 6.1 Relationship Context

当前 `ContextSnapshotV2` 中只有：

```text
relationship_state
```

且实际固定读取：

```text
Character → Account
```

未来改为：

```text
relationships[]
```

例如小槿：

```text
Xiaojin → Player
Xiaojin → Xiazhi
Xiaojin → Rion
```

Relationship Domain 本身不改。

主要修改：

- ContextSource；
- ContextSnapshot；
- Reflection Fact Handler。

---

## 6.2 Knowledge Boundary

首版不建议立即实现完整 Knowledge Graph。

MVP 可先使用：

```text
Public Transcript
+
Private Memory
+
Private Activity State
+
Event Visibility
```

来保障知识边界。

未来再逐渐增加：

```text
KnowledgeState
```

表达：

```text
actor
knows
fact
because_of
source_event
```

---

## 6.3 Provider Role 与 Actor Identity 分离

系统内部不得使用：

```text
user
assistant
```

表达真实社会身份。

真实 Actor 应使用：

```text
ActorRef
├── player
├── character
├── activity
└── system
```

例如：

```text
sender:
  kind: character
  id: xiaojin
```

直到 Provider Adapter 层才映射成：

```text
developer
user
assistant
```

多角色历史采用：

> Perspective-local Conversation。

对 Xiaojin：

```text
Xiaojin 自己之前说过的话
→ assistant history

其他人说的话
→ observed input
```

因此同一个真实群聊会产生：

```text
Xiaojin Perspective
Xiazhi Perspective
Rion Perspective
```

三份不同的模型上下文。

---

# 七、Memory 与 Reflection 泛化

## 7.1 Per-character Memory Segment

当前 `MemorySegment` 已包含：

```text
character_id
```

未来同一段客观对话可以产生：

```text
Segment(Xiaojin)
Segment(Xiazhi)
Segment(Rion)
```

它们可以引用同一段消息范围，但分别形成：

```text
Character-specific Reflection
```

---

## 7.2 Memory Sealing 修改

当前 Memory Sealing 明确要求：

```text
active_participants == 1
```

需要修改为：

> 指定 `character_id` 只要是当前有效参与角色，就可以针对该角色 Seal Segment。

即从：

```text
conversation has exactly one character
```

改成：

```text
target character belongs to conversation
```

---

## 7.3 Relationship Reflection 泛化

当前 `RelationshipFactHandler` 固定：

```text
target_kind = ACCOUNT
target_id = account_id
```

未来 Reflection Candidate 应携带：

```text
target_kind
target_id
```

例如：

```text
observer = Xiaojin
target_kind = CHARACTER
target_id = Xiazhi

evidence = SUPPORT
```

然后继续交给现有：

```text
RelationshipEvidence
RelationshipPolicy
RelationshipStateRepository
```

处理。

Relation Domain 无需改数学规则。

---

## 7.4 Shared Experience

Gameplay 结束后新增：

```text
SharedExperience
```

作为客观 Activity Summary。

例如：

```text
activity_id
participants
result
important_events
highlights
timestamps
```

然后：

```text
SharedExperience
       ↓
Life / Social Event
       ↓
Per-character Reflection
       ↓
Memory
       ↓
Relationship Evidence
```

同一个 Shared Experience 可以在不同 Character 中产生不同 Memory。

---

# 八、Gameplay Runtime

## 8.1 新增 ActivityModule

Gameplay 不应进入 ConversationModule。

建议在 `ApplicationRuntime` 中新增：

```text
ApplicationRuntime
├── ConversationModule
├── SocialModule
├── ActivityModule
├── MemoryModule
├── ReflectionModule
└── ObservabilityModule
```

其中：

### ConversationModule

负责：

- Message；
- Input；
- Message Commit；
- Conversation History。

### SocialModule

负责：

- Social Turn；
- Participation Scheduling；
- Group Dynamics；
- Character Participation。

### ActivityModule

负责：

- Activity Session；
- Rules；
- Game State；
- Public / Private State；
- Legal Actions；
- Action Validation；
- Game Result。

---

## 8.2 Activity Contract

不同小游戏统一实现：

```text
Activity
├── participants
├── public_state
├── private_state
├── legal_actions
├── rules
├── current_turn
└── result
```

Character Agent 不需要知道具体 Activity 如何实现。

它只读取：

```text
ActivityContext
```

---

## 8.3 ActivityActionProposal

当前 ProposalKind：

```text
CHARACTER_MESSAGE
REFLECTION_BATCH
```

未来扩展：

```text
CHARACTER_MESSAGE
ACTIVITY_ACTION
REFLECTION_BATCH
```

新增：

```text
ActivityActionProposal
```

例如：

```json
{
  "kind": "activity_action",
  "character_id": "xiaojin",
  "activity_id": "game_42",
  "action": "submit_hint",
  "parameters": {
    "hint": "小型水族馆"
  }
}
```

---

## 8.4 InvocationPurpose 扩展

当前：

```text
CONVERSATION_REPLY
REFLECTION
```

未来：

```text
CONVERSATION_REPLY
ACTIVITY_TURN
REFLECTION
```

同时新增：

```text
ActivityScope
```

因此 Harness 本身仍然运行统一 Agent Invocation。

---

# 九、Life Runtime 的位置

Life Simulation 是长期方向，但不是 Multi-character 重构的前置条件。

首版只保留现有：

```text
mood
activity
availability
```

即可。

未来再新增：

```text
LifeProfile
LifePlan
LifeEvent
LifeChronicle
```

并接入同一 Objective Event → Perspective 模型。

Life 系统产生：

```text
LifeEvent
```

Character 是否知道、如何理解，再经过 Perspective 和 Memory。

---

# 十、WorldState 的重新定位

当前 `WorldState` 带有较明显的 Echo 剧情阶段语义：

```text
phase
stage_summary
```

未来不建议将其扩展成“万能全局状态”。

它可以继续承担：

```text
world_time
runtime status
global environment phase
```

但：

```text
Social State
```

归 SocialModule。

```text
Activity State
```

归 ActivityModule。

```text
Character Life State
```

归 Character / Life Runtime。

避免形成：

> 所有功能最后都往 WorldState 塞。

---

# 十一、重构优先级

## 11.1 Phase A：Character 泛化

目标：

> 一个 Server 能同时加载多个 Character。

完成：

- 增加多个 Character Bundle；
- Character Blueprint 语义明确；
- Character Bootstrap；
- 多 Character State 初始化；
- 多 Participant Conversation。

暂时不做复杂 Life Simulation。

---

## 11.2 Phase B：Group Conversation

目标：

> 1 Player + 3 Character 真正能够群聊。

完成：

```text
GROUP Conversation
SocialTurn
ParticipationScheduler
N CharacterTasks
Independent Context
Independent Invocation
Independent Commit
```

此阶段核心验证：

```text
Player:
晚上有人玩吗？

Xiaojin:
我可以。

Xiazhi:
玩什么？

Rion:
我今天还有实验，你们玩吧。
```

三个回复来自三个独立 Invocation。

---

## 11.3 Phase C：Perspective Context

目标：

> 每个角色只读取自己的社会视角。

完成：

```text
PerspectiveProjector
ObservedEvent
Multiple Relationships
Private/Public Visibility
Perspective-local Prompt Projection
```

这是未来所有扩展的关键基础。

---

## 11.4 Phase D：Multi-character Memory / Reflection

完成：

- Per-character Segment；
- Per-character Reflection；
- Character → Character Relationship；
- Shared social event memory；
- Relationship Evidence Target 泛化。

做到：

> 同一个事件被不同角色以不同方式记住。

---

## 11.5 Phase E：Activity Runtime

完成第一款 ito-like Gameplay。

增加：

```text
ActivityModule
ActivitySession
ActivityContext
ActivityActionProposal
ActivityActionHandler
Rule Validator
SharedExperience
```

完整闭环：

```text
Chat
 ↓
Start Activity
 ↓
Gameplay
 ↓
Shared Experience
 ↓
Reflection
 ↓
Return to Chat
 ↓
Recall Experience
```

---

# 十二、明确不应在本轮重构中做的事情

为了控制工程范围，本阶段不进行以下重构：

- 不将整个系统改为纯 Event Sourcing；
- 不更换 SQLite；
- 不引入 Redis / Kafka；
- 不更换现有 Task Dispatcher；
- 不重写 Agent Harness；
- 不重写 Model Gateway；
- 不重写 Reflection Graph Runtime；
- 不重新设计 Relationship 数学模型；
- 不实现完整 Knowledge Graph；
- 不实现完整 Life Simulation；
- 不实现几十个 Agent 并发；
- 不实现复杂 RL Agent；
- 不为了“架构漂亮”重命名全部现有 Domain。

本阶段目标是：

> 泛化，而不是重建。

---

# 十三、建议的新模块边界

最终 Runtime 可以演进为：

```text
ApplicationRuntime
│
├── Identity / Character
│   ├── CharacterBlueprint
│   ├── CharacterCompiler
│   └── CharacterBootstrap
│
├── ConversationModule
│   ├── Message
│   ├── InputBatch
│   └── Message Commit
│
├── SocialModule
│   ├── SocialTurn
│   ├── ParticipationScheduler
│   └── PerspectiveProjector
│
├── ActivityModule
│   ├── ActivitySession
│   ├── ActivityState
│   ├── LegalAction
│   └── RuleValidator
│
├── Character Runtime
│   ├── ContextSnapshot
│   ├── AgentInvocation
│   ├── Harness
│   └── Proposal
│
├── MemoryModule
│   ├── Segment
│   ├── Memory
│   └── Retrieval
│
├── ReflectionModule
│   ├── Reflection Graph
│   ├── Relationship Evidence
│   └── State Update
│
└── ObservabilityModule
    ├── Trace
    ├── Replay
    └── Debug Capture
```

---

# 十四、最终核心不变量

重构后应始终保持以下系统不变量。

### Runtime Owns Truth

只有 Runtime 能提交权威事实。

### Agent Only Proposes

Agent 输出永远是 Proposal，而不是数据库写操作。

### One Invocation, One Character

每次 Character Agent Invocation 只代表一个 Character。

### Character Context Is Perspective-bound

Character 只能读取自己可观察的世界。

### Private Information Is Structurally Hidden

不能依赖 Prompt 禁止信息泄露。

不可见事实不进入 Context。

### Memory Is Not Truth

Memory 是 Character 对世界的主观记录。

### Relationship Is Directed

```text
A → B
```

与：

```text
B → A
```

是两套状态。

### Gameplay Uses the Same Character

进入 Activity 后不创建“Gameplay Agent”。

仍然是同一个 Character Instance。

### Dialogue and Action Are Both Behavior

Character 可以产生：

```text
Utterance
Action
```

二者都是 Agent Behavior，但均需 Runtime Review。

---

# 结语

本次后端重构的真正目标，不是简单地让 Echo 支持“多个 NPC 回复”。

它要完成一次更底层的架构转变：

```text
Single Character Conversation Backend
```

演进为：

```text
Persistent Multi-Agent Runtime
```

在新的 Runtime 中：

> 世界以客观事实和事件存在；\
> 每个 Character 通过自己的 Perspective 观察世界；\
> Memory 保存角色主观经历；\
> Agent 根据 Identity、State、Relationship、Memory 和 Observation 作出决策；\
> 所有语言和行动通过 Proposal 返回 Runtime；\
> Runtime 验证并提交新的事实；\
> 新事实再次成为其他角色能够观察到的世界。

最终统一循环为：

```text
Objective World
      ↓
Perspective
      ↓
Observation
      ↓
Character Context
      ↓
Character Agent
      ↓
Message / Action Proposal
      ↓
Runtime Validation
      ↓
State Transition
      ↓
Objective World
```

Conversation、Social Interaction、Gameplay 和未来的 Life Simulation，都只是这个循环中的不同 Environment。

因此，本次重构最重要的不是增加更多功能，而是建立三个新的核心边界：

```text
Social Turn
Perspective Projection
Activity Runtime
```

而现有 Echo Server 已经成熟的：

```text
Agent Harness
Task Runtime
Proposal Review
Memory
Reflection
Relationship
Trace
```

应作为底座继续保留。

这条路线能够在最大限度保护已有工程资产的同时，将 Echo 从“单角色陪伴后端”真正演进为 Echo Commons 所需要的 **Persistent Character Agent Gameplay Runtime**。
