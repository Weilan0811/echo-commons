# Persistent Character Agent Gameplay Platform 总体设计方案

> 文档性质：项目总体设计\
> 项目定位：面向游戏场景的 Persistent Character Agent Gameplay Platform\
> 当前目标：在有限开发周期内完成可交互、可测试、可扩展的 Character Agent Gameplay Vertical Slice

---

# 一、项目定位

## 1.1 背景

项目最初以单角色陪伴游戏《回响》为载体，围绕角色扮演、长期记忆、关系演化、反思和现实时间陪伴展开。

随着开发推进，完整 Unity 游戏客户端、内容制作、角色系统、玩法系统与 Agent 后端并行开发的成本已经超出当前时间和人力条件。因此项目不再以“完成一款完整独立游戏”为近期目标，而是收束到最具有技术竞争力的部分：

**Character Agent 如何真正进入 Gameplay。**

传统 Character AI 产品主要解决：

> 如何让用户和一个角色持续对话。

本项目希望进一步验证：

> 一个具有稳定人格、私人记忆、社会关系和自身生活状态的虚拟角色，能否进入多人社交与规则化 Gameplay 环境，在长期运行中持续保持“同一个人”。

因此，项目最终定位为：

**Persistent Character Agent Gameplay Platform**

即一个支持批量创建 Character Agent、长期群聊、多角色社会互动以及可插拔 Gameplay Activity 的角色智能体运行与测试平台。

---

## 1.2 核心研究与产品命题

平台重点验证以下能力。

### Character Consistency

角色不能只是具有固定语气，而应拥有相对稳定的：

- 身份背景；
- 人格倾向；
- 核心价值观；
- 内在矛盾；
- 社交方式；
- 行为偏好；
- Gameplay 决策风格。

角色进入聊天室、小游戏以及不同情绪和关系状态后，都应保持可识别的人格连续性。

### Persistent Relationship

角色之间以及角色与玩家之间形成长期、有向的社会关系。

互动不仅影响当前回复，也能够通过：

- Affection；
- Trust；
- Attachment；
- Relationship Evidence；
- Shared Experience；

影响未来行为。

### Persistent Memory

聊天、共同活动、生活事件和 Gameplay 经历能够形成长期记忆。

角色未来应能够正确引用过去经历，而不是每一次对话都重新构造人物关系和共同历史。

### Character in Gameplay

Character Agent 不只负责“说什么”，还应能够在明确的游戏规则中：

- 理解当前局面；
- 参与讨论；
- 做出决策；
- 提交合法 Action；
- 与玩家及其他 Agent 合作；
- 在游戏行为中继续体现人格。

### Multi-Agent Social Interaction

多个角色拥有彼此独立的：

- Identity；
- Memory；
- Relationship；
- Knowledge；
- Life State。

不同角色不能共享一个隐式全知上下文，而应真正作为独立 Agent 参与社会活动。

---

## 1.3 产品形态

平台的主要用户体验由两个长期空间组成：

```text
Persistent Social Space
        ↓
     群聊互动
        ↓
   发起 Shared Activity
        ↓
      Gameplay
        ↓
 Shared Experience
        ↓
     回到群聊
        ↓
 Memory / Relationship
        ↓
 Future Interaction
```

其中：

**聊天室是角色长期存在的社会空间。**

**Gameplay Activity 是角色之间产生结构化共同经历的机制。**

小游戏不是独立于 Character 系统的附加模块，而是角色关系和记忆形成的重要来源。

产品体验的核心不再是：

> Talk with a Character.

而是：

> Hang out with Characters.

---

# 二、总体系统架构

## 2.1 核心架构

系统整体划分为五个主要层次：

```text
┌─────────────────────────────────────┐
│              Web Client             │
│                                     │
│ Community / Activity / Character Lab│
└──────────────────┬──────────────────┘
                   │
┌──────────────────▼──────────────────┐
│             Social Runtime          │
│                                     │
│ Group Conversation                  │
│ Participation Scheduler             │
│ Activity Session Management         │
└──────────────────┬──────────────────┘
                   │
┌──────────────────▼──────────────────┐
│           Character Runtime         │
│                                     │
│ Character Agent                     │
│ Character Blueprint                 │
│ Character Instance                  │
│ Runtime State                       │
│ Relationship / Knowledge / Memory   │
└──────────────────┬──────────────────┘
                   │
┌──────────────────▼──────────────────┐
│           Gameplay Runtime          │
│                                     │
│ Activity Rules                      │
│ Public / Private State              │
│ Legal Actions                       │
│ Proposal Validation                 │
│ Game State Transition               │
└──────────────────┬──────────────────┘
                   │
┌──────────────────▼──────────────────┐
│     Life / Memory / Evaluation      │
│                                     │
│ Life Chronicle                      │
│ Reflection                          │
│ Long-term Memory                    │
│ Scenario Runner                     │
│ Trace / Replay / Metrics            │
└─────────────────────────────────────┘
```

---

## 2.2 基本工程原则

### Agent 与权威状态分离

LLM 不允许直接修改：

- 游戏状态；
- 人物关系；
- 世界事实；
- Memory；
- Life Chronicle。

Agent 只能提交结构化 Proposal。

例如：

```text
Character Agent
      ↓
Action Proposal
      ↓
Runtime Validation
      ↓
Authoritative Commit
```

这一原则沿用现有 Echo Server 已经建立的：

**Proposal → Review → Commit**

结构。

### Character 与 Model 分离

所有角色原则上共用：

- 同一个基础模型；
- 同一个 Character Agent；
- 同一个 Harness；
- 同一套 Runtime。

角色之间的区别来源于 Character Context，而不是不同 Agent 实现。

### Static Identity 与 Runtime Fact 分离

系统必须明确区分：

```text
角色是谁
```

和：

```text
角色现在发生了什么
```

前者属于 Character Blueprint。

后者属于 Character Instance 的 Runtime State。

---

# 三、Character Runtime

## 3.1 Character Blueprint 与 Character Instance

角色系统需要正式区分两个对象。

### Character Blueprint

Character Blueprint 是作者定义、版本化且相对稳定的人物模板。

它回答：

> 这是一个怎样的人？

主要包含：

```text
CharacterBlueprint
├── Core Identity
├── Personality
├── Voice
├── Relationship Style
├── Life Scaffold
├── History Anchors
├── Gameplay Disposition
├── Secrets / Boundaries
└── Authored Memories
```

Blueprint 本身不保存角色进入社群后的运行历史。

### Character Instance

Character Instance 是 Blueprint 在某个具体 Community 中实例化后的角色。

例如：

```text
character_id:
xiaojin_room01

blueprint:
xiaojin@0.6.0

community:
room_01
```

Character Instance 拥有动态状态：

```text
Current Mood
Current Activity
Current Goal
Current Life Arc
Relationships
Knowledge
Memories
Shared Experiences
Gameplay History
```

因此，同一个 Blueprint 可以创建多个独立 Instance，用于自动测试和实验。

---

## 3.2 Character Blueprint 最小信息结构

### Core Identity

描述角色稳定身份，例如：

- 姓名；
- 年龄；
- 职业；
- 当前生活阶段；
- 居住状态；
- 核心人生背景。

同时应提供一句能够概括人物核心矛盾的 Character Concept。

例如：

> 一个真诚开朗、喜欢人与世界，却因为害怕失去而很难真正依赖别人的女孩。

### Personality

Personality 不建议设计成大量数值。

一个角色通常只需要明确：

- 3–5 个稳定人格倾向；
- 2–3 个核心价值观；
- 1–2 个内在矛盾；
- 压力状态下的典型行为方式。

内在矛盾尤其重要。

纯标签式角色：

> 开朗、善良、喜欢画画。

非常容易退化成模板 NPC。

而：

> 渴望亲密关系，但又害怕被抛弃。

才能产生真正具有变化空间的人物行为。

### Voice

Voice 只负责：

> 角色怎样表达。

包括：

- 句子长度；
- 常用表达；
- 情绪表达方式；
- 玩笑方式；
- 是否直接；
- 是否频繁使用表情等。

Voice 不承担人格本身。

### Relationship Style

描述角色如何：

- 与陌生人相处；
- 建立信任；
- 表达亲近；
- 处理冲突；
- 面对拒绝；
- 暴露脆弱；
- 在关系中主动或退缩。

### Gameplay Disposition

Gameplay 不单独创建新人格。

而是将人物特征投影到游戏行为中。

例如：

```text
risk_tolerance
competitiveness
cooperativeness
leadership
rule_attitude
```

以及自然语言式倾向：

```text
不喜欢主导讨论
倾向先取得共识
在熟悉的人身边更敢冒险
不愿为了最优策略明显伤害同伴
```

这样不同小游戏可以复用同一个 Gameplay Personality。

---

## 3.3 Life Scaffold

角色必须拥有足够支撑日常生活连续性的基本结构。

至少包括：

```text
Occupation / Study
Routine
Current Life Stage
Current Projects
Goals
Important People
Life Domains
```

例如：

```text
职业：
自由插画师

Routine：
上午通常在家工作
下午完成委托
晚上相对空闲

Current Arc：
正在完成一个封面稿

Goal：
保持稳定收入
更换数位板
```

Life Scaffold 的作用不是模拟完整社会。

它负责给角色的日常行为提供约束，使：

> “角色今天在干什么”

不再完全由模型随机生成。

---

## 3.4 History Anchors

系统不需要预先生成角色从出生至今的每日历史。

每个角色只需要保存塑造人物的重要人生节点，例如：

```text
Childhood
2–3 个事件

Adolescence
2–3 个事件

Recent Life
3–5 个事件
```

这些事件构成角色过去的高层骨架。

其余历史允许按需生成。

---

## 3.5 Character Bootstrap

角色不能仅填写姓名和性格后直接进入 Community。

每个新 Character 应经历统一初始化：

```text
Character Seed
      ↓
Character Compiler
      ↓
Blueprint Generation
      ↓
Schema Validation
      ↓
Consistency Review
      ↓
Runtime Bootstrap
      ↓
ACTIVE
```

初始化完成时至少需要建立：

```text
Identity
Personality
Voice
Life Scaffold
History Anchors
Initial Memories
Community Membership
Initial Relationships
Knowledge Boundaries
Current Life Arc
Current Daily State
```

---

## 3.6 Character Factory

为了支持批量实验，需要提供轻量 Character Seed。

例如：

```yaml
name: 夏织
age: 20
occupation: university_student

concept:
  很容易和别人熟起来，
  有些冒失但非常真诚的大学生。

traits:
  - outgoing
  - impulsive
  - optimistic

values:
  - friendship
  - curiosity

inner_conflict:
  害怕独处，却不愿承认自己害怕孤独。

interests:
  - photography
  - hiking
  - board_games
```

Character Compiler 可以将其扩展成标准 Blueprint。

生成结果必须经过结构和一致性验证后冻结为版本化角色：

```text
xiazhi@1.0.0
```

运行时不允许 Agent 临时重新定义自身 Blueprint。

---

## 3.7 Character Fidelity Tier

不同角色可以使用不同模拟分辨率，但不需要使用不同 Character Agent。

建议划分三档。

| 能力                 | Guest | Resident | Core |
| ------------------ | ----- | -------- | ---- |
| 基本身份               | ✓     | ✓        | ✓    |
| Personality        | 基础    | 完整       | 深度   |
| Voice              | ✓     | ✓        | ✓    |
| Routine            | 简单    | 完整       | 完整   |
| Current Arc        | 0–1   | 1–2      | 多条   |
| History Anchors    | 少量    | 中等       | 精细   |
| Relationship Style | 基础    | 完整       | 深度   |
| Private Secrets    | 可选    | 少量       | 完整   |
| Memory Budget      | 小     | 中        | 大    |
| Reflection         | 关键事件  | 常规       | 细粒度  |
| Off-screen Life    | 按需    | 日级       | 更细   |
| Proactivity        | 低     | 中        | 高    |

Tier 控制：

> 世界对这个角色模拟到什么分辨率。

而不是：

> 这个角色是不是完整的人。

即使 Guest 角色，也必须保证：

- 人格基本一致；
- 不泄露未知信息；
- 不违反固定身份；
- 能正常参与群聊和 Gameplay。

---

# 四、Social Runtime 与 Life Simulation

## 4.1 Persistent Community

平台中的聊天室是长期存在的私人社群。

玩家只是其中一个成员。

典型结构为：

```text
Player
Xiaojin
Character B
Character C
...
```

角色并不始终围绕玩家行动。

Agent 可以：

- 与玩家交流；
- 与其他 Agent 交流；
- 主动接话；
- 保持沉默；
- 发起 Activity；
- 拒绝活动；
- 分享生活事件；
- 回忆共同经历。

---

## 4.2 Participation Scheduler

群聊不能采用：

```text
玩家发言
↓
所有 Character 同时回复
```

而需要独立 Participation Scheduler：

```text
New Message / Event
        ↓
Participation Evaluation
        ↓
Character A: speak?
Character B: speak?
Character C: speak?
        ↓
Selected Character Invocation
```

发言意愿可以综合：

- 是否被直接提及；
- 当前话题相关度；
- 兴趣；
- 当前活动；
- Relationship；
- Personality；
- 最近是否已经大量发言；
- 当前 Group Dynamics。

每个被选中的 Character 单独执行 Agent Invocation。

---

## 4.3 Private State 与 Knowledge Boundary

每个 Character 必须拥有独立认知边界。

Character 只能知道：

```text
自身 Identity
自身经历
自身 Memory
自身 Relationship
公开群聊内容
明确被告知的信息
自身观察到的 Gameplay State
```

因此 Social Runtime 除 RelationshipState 外，应逐步增加：

```text
KnowledgeState
SharedHistory
```

用于明确：

> 谁知道什么。

这是 Multi-Agent 系统防止信息泄露的关键。

---

## 4.4 Life LOD

平台不模拟完整社会。

角色人生采用分辨率分层：

```text
Identity
    ↓
Life Episode
    ↓
Current Arc
    ↓
Daily Plan
    ↓
Concrete Event
```

距离当前交互越近，模拟越精细。

远期人生只保留关键结构。

近期生活以日和事件为单位运行。

---

## 4.5 Daily Life Generation

角色日常状态按照明确优先级生成：

```text
Hard Commitments
       ↓
Current Goals / Projects
       ↓
Social Commitments
       ↓
Routine / Habits
       ↓
Optional Micro-events
```

因此角色生活并非完全由 LLM 临时编造。

例如：

```text
09:30–12:00
在家工作

12:00–13:30
午餐与休息

13:30–18:00
继续工作

20:00以后
相对空闲
```

只有当前交互真的需要具体细节时，才进一步 Materialize：

```text
working_at_home
        ↓
玩家此时发来消息
        ↓
展开当前工作细节
```

---

## 4.6 Life Chronicle

系统必须区分：

```text
What actually happened
```

和：

```text
What the character remembers
```

因此引入权威 Life Chronicle。

所有已经确认发生的重要事件进入 Chronicle：

```text
Life Event
Social Event
Gameplay Event
Important Personal Event
```

例如：

```text
2026-10-08

小槿完成了当前封面稿。

晚上与玩家、夏织和另一名角色
参加了一局小游戏。

团队最终失败，
夏织在最后一步判断错误，
大家对此进行了轻松的调侃。
```

Chronicle 是事实。

Memory 是角色对事实的主观加工。

---

## 4.7 Lazy Canonization

没有必要提前创造角色完整人生。

当玩家询问过去时，系统按以下顺序处理：

```text
已有 Chronicle？
    ↓
直接回答

没有 →
已有 Life Episode / Plan？
    ↓
粗粒度回答

仍没有 →
是否可以合理推断？
    ↓
使用不确定表达

完全未知 →
允许角色说“不记得”

若该问题值得成为人物历史 →
Historical Event Proposal
        ↓
Continuity Validation
        ↓
Canonicalize
```

核心原则：

> 历史可以第一次被创造，但一旦成为事实，后续不能重新创造不同版本。

---

# 五、Gameplay 与长期记忆

## 5.1 Shared Activity Framework

Gameplay 不应直接写死在 Character Agent 中。

需要抽象统一 Activity Contract：

```text
Activity
├── Participants
├── Rules
├── Public State
├── Private State
├── Legal Actions
├── Conversation Context
├── Result
└── Shared Experience
```

进入游戏时：

```text
Character Context
      +
Activity Context
```

Character 本身不发生切换。

因此 Activity 只是 Character 当前所处环境的一部分。

---

## 5.2 第一阶段 Gameplay

第一款游戏建议采用轻量、合作、欢乐、能够显著暴露人物价值观的社交小游戏。

优先实现：

**ito-like Cooperative Value Guessing Game**

基本规则：

- 每个参与者获得一个私有数值；
- 所有人看到同一个主题；
- 角色根据自己数值给出符合主题的描述；
- 玩家与 Agent 共同讨论排序；
- 最终揭示结果。

这种 Gameplay 能天然体现：

- Personality；
- Value；
- Humor；
- Relationship；
- Group Dynamics；
- Private State；
- Communication。

而实现成本远低于传统电子游戏。

---

## 5.3 Gameplay Action 与 Utterance 分离

Character 在游戏中：

> 说了什么

和：

> 实际执行什么

必须严格分离。

例如：

```text
“我觉得这个应该放得更靠右。”
```

只是 Utterance。

实际操作需要：

```json
{
  "action": "place_token",
  "position": 82
}
```

然后：

```text
Action Proposal
      ↓
Gameplay Runtime
      ↓
Rule Validation
      ↓
Commit
```

Character Agent 永远不能直接修改 Game State。

---

## 5.4 Shared Experience

游戏结束后必须生成结构化 Shared Experience。

例如：

```text
Activity:
value_guessing_game

Participants:
Player
Xiaojin
Xiazhi
Character C

Result:
Failed

Highlights:
- 玩家对“便利店约会”的评价明显较高
- 小槿对此感到意外并进行了调侃
- 夏织在最后一次排序中判断错误

Atmosphere:
Playful
```

Shared Experience 随后进入：

```text
Life Chronicle
      ↓
Character-specific Reflection
      ↓
Memory
      ↓
Relationship Evidence
```

因此一局游戏不会在退出 Activity 后消失。

它成为真正的共同历史。

---

## 5.5 Memory 与 Reflection

聊天、生活事件、社交活动和 Gameplay 统一进入 Memory Pipeline：

```text
Conversation
Gameplay
Life Event
Social Event
     ↓
Memory Segment
     ↓
Reflection
     ↓
Episodic Memory
Fact
Preference
Relationship Evidence
Character State
```

Reflection 不应过度确定化。

例如玩家在一局游戏中表现出偏好：

```text
可能喜欢简单日常型活动
confidence = low
```

而不是立刻写成：

```text
玩家最喜欢便利店约会
```

---

## 5.6 Relationship

Relationship 为有向关系：

```text
Character A
      ↓
Character B
```

而不是全局统一关系值。

当前可继续沿用：

```text
Affection
Trust
Attachment
```

关系变化应由事实驱动：

```text
Interaction
Support
Conflict
Commitment
```

Gameplay 本身可以产生 Relationship Evidence。

但 Gameplay Runtime 不应该直接修改：

```text
trust += 5
```

正确流程应为：

```text
Gameplay Event
      ↓
Reflection
      ↓
Relationship Evidence
      ↓
Relationship Policy
      ↓
Relationship State
```

---

# 六、Demo 范围与实施目标

## 6.1 最终平台能力

长期来看，平台希望支持：

### Character Authoring

- Character Seed；
- Character Compiler；
- Blueprint Versioning；
- Fidelity Tier；
- Batch Character Creation。

### Character Runtime

- Personality；
- Identity；
- Voice；
- Runtime State；
- Goal；
- Life State；
- Memory；
- Relationship；
- Knowledge Boundary。

### Social Runtime

- Group Chat；
- Participation Scheduler；
- Agent-Agent Conversation；
- Proactivity；
- Shared Social Context。

### Life Simulation

- Life Scaffold；
- Daily Plan；
- Current Arc；
- Life Event；
- Life Chronicle；
- Lazy Canonization。

### Gameplay

- Activity Plugin；
- Public / Private State；
- Rules；
- Legal Actions；
- Shared Experience。

### Memory & Reflection

- Conversation Reflection；
- Gameplay Reflection；
- Episodic Memory；
- Relationship Evidence；
- Preference / Fact Extraction。

### Evaluation

- Trace；
- Replay；
- Scenario Runner；
- Batch Character Test；
- Character Consistency Evaluation；
- Knowledge Leakage Evaluation；
- Gameplay Rule Compliance。

---

## 6.2 当前 Vertical Slice

受开发周期限制，首个 Demo 不追求完整平台。

当前必须完成的最小闭环为：

```text
3 Character Agents
        +
1 Player
        ↓
Persistent Group Chat
        ↓
Participation Scheduler
        ↓
Independent Character Context
        ↓
Relationship / Memory
        ↓
Lightweight Life State
        ↓
ito-like Shared Activity
        ↓
Gameplay Interaction
        ↓
Shared Experience
        ↓
Reflection
        ↓
Return to Group Chat
        ↓
Future Recall
```

具体目标包括：

- 三个不同设定的角色能够使用同一个 Character Agent 运行；
- 角色能够在群聊中自主决定是否参与；
- 每个角色拥有独立 Identity、Memory、Relationship 和 Knowledge；
- 角色拥有简单但连续的 Off-screen Life State；
- 玩家可以在聊天室中发起小游戏；
- 三个 Agent 可以保持自己的人格参与游戏；
- Gameplay 中存在明确 Public / Private State 与 Legal Action；
- 游戏结果能够进入 Shared Experience；
- 返回聊天室后角色能够继续讨论刚才发生的内容；
- 后续会话能够重新召回此前 Gameplay 经历；
- Developer Inspector 可以查看 Character Context、Memory、Relationship、Participation Decision、Gameplay Action 和 Reflection Trace。

---

## 6.3 当前明确不做的内容

为了避免重新陷入范围膨胀，首个版本不实现：

- Unity 客户端；
- 开放世界；
- 完整 NPC 社会模拟；
- 大规模地图；
- 复杂经济系统；
- 战斗系统；
- 完整日程模拟；
- 数十名同时活跃 Agent；
- 复杂 RL；
- SFT / DPO / GRPO；
- Online Distillation；
- 语音系统；
- Live2D；
- 多种大型 Gameplay；
- 完整动态剧情系统。

这些能力可以作为平台长期演进方向，但不属于当前 Vertical Slice。

---

# 结语

本项目最终希望证明的不是：

> 大语言模型能够扮演几个角色聊天。

而是：

> **同一套 Character Agent Framework 可以承载多个拥有独立人格、生活、记忆、关系和知识边界的角色；这些角色能够长期共存于一个社会空间，在聊天之外进入真正具有规则和状态的 Gameplay，并把共同经历继续带回之后的人际关系和生活之中。**

因此，平台最核心的闭环不是单次生成，而是：

```text
Character
    ↓
Social Interaction
    ↓
Gameplay
    ↓
Shared Experience
    ↓
Reflection
    ↓
Memory / Relationship
    ↓
Future Character Behavior
```

这条闭环构成整个 Persistent Character Agent Gameplay Platform 的核心价值。
