# 四种反思图

反思把角色真正收到的材料整理成自身认识和长期记忆。每次运行属于一个社群、一个独立角色；群聊中的角色分别反思，各自材料由观察权限决定。

| 图 | 解决的问题 | 来源 | 审核后保存 | 当前消费者 |
|---|---|---|---|---|
| [segment_reflect](segment-reflect.md) | 这一段发生什么，是否改变自身状态和关系 | 精确消息、自身 Thought | 段摘要、状态、关系证据 | 已接入 |
| [continuity_compress](continuity-compress.md) | 长会话如何保留连贯历史 | 前一 digest、新段摘要 | 新 digest、连续性消费 | 已接入，NoOp 有设计差异 |
| [memory_organize](memory-organize.md) | 哪些经历值得独立检索 | 段摘要及允许补充材料 | 长期页、实体、边、整理消费 | 已接入 |
| [view_refresh](view-refresh.md) | 如何把已保存事实包装成易读认识 | 已提交 ChangeSet | 态度、状态摘要、核心记忆视图 | 已接入 |

```mermaid
flowchart LR
  M[可见消息与自身 Thought] --> S[segment_reflect]
  S --> SS[段摘要]
  S --> F[状态与关系事实]
  SS --> C[continuity_compress]
  SS --> O[memory_organize]
  C --> D[会话 digest]
  O --> L[长期页及记忆图]
  F -. 已提交变化 .-> V[view_refresh]
  L -. 已提交变化 .-> V
```

前三种图的正式后台工作流选择未归段材料、准备段反思，再为两个摘要消费者分别冻结批次。图之间通过正式事实和消费身份联系，不能把一个节点的未审核候选当成另一图的既成事实。

简单模式仅安排段摘要与连续性压缩，段图的状态和关系分支不激活；完整模式使用四种图。作者材料通过专属来源进入长期整理，不伪装成聊天段。模式与材料契约见 [记忆](../memory.md)。

view_refresh 跟随正式事实变化运行，由代码选择受影响的分支。diary 暂缓，保留历史定义和存储，不进入运行注册，也不参与 Thought 保留和清理条件；旧设计保留于 [diary_compose](diary-compose.md)。

阅读各图前先看 [共同执行模型](execution-model.md)，材料选择见 [记忆](../memory.md)，状态和关系算法见 [角色事实](../character-state-and-relationships.md)。独立节点完成、图完成与事实提交是三个不同阶段。
