# 持久任务执行

execution 保存共享 Dispatcher、TaskRegistry、ModelBudget、租约心跳、恢复政策和 Supervisor。对话与反思分别实现自己的队列、TaskHandler、审核及提交；后台执行器通过正式注册入口分派工作。

领取租约保存 owner、截止时间、attempt 和 generation。续期与提交检查当前代次、任务状态和业务资格；旧代次或过期租约不能提交新事实。模型执行期间持续心跳，数据库写事务只覆盖领取或提交的短操作。

临时失败进入 retry_wait，终态失败结束参与决定；取消、社群暂停、角色不可用和成员离开通过正式生命周期与租约检查生效。启动恢复到期租约，原任务使用原快照继续执行。

Supervisor 管理社交规划、多个对话执行器、多个反思执行器和追踪投递。工作状态供就绪检查与诊断读取。未来 ActivityTask 可以登记独立处理器和队列，当前没有活动执行实现。

事务规则见 [持久化](persistence-and-transactions.md)，业务完成规则见 [social](../modules/social.md)。
