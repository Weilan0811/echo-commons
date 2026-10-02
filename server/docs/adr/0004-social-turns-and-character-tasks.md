# 社交轮次与角色任务

状态：生效。基线版本：`0.1.0`。

## 决定

输入批次、SocialTurn、ParticipationDecision 和 ConversationTask 分别保存输入聚合、多人回应安排、个体参与原因及实际执行。任务在规划时冻结原快照。

## 实际影响

角色可并发或重试，其他角色先提交不会改变已冻结输入。玩家窗口与角色零窗口使用共同批次结构，连续接话保持未实现。

实现依赖见 [架构](../architecture.md)，字段约束见 [数据库](../database-design.md)。
