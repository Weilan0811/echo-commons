class ResponseDispatcher:
    def __init__(self, conversations, activities):
        self.conversations, self.activities = conversations, activities

    def _target(self, connection, turn):
        kind = connection.execute(
            "SELECT kind FROM conversations WHERE conversation_id=?", (turn.conversation_id,)
        ).fetchone()[0]
        return self.activities if kind == "game" else self.conversations

    def reserve(self, connection, turn, member, at):
        return self._target(connection, turn).reserve(connection, turn, member, at)

    def reservation(self, connection, turn_id):
        return self.conversations.reservation(connection, turn_id) or self.activities.reservation(
            connection, turn_id
        )

    def create(self, connection, request, *, task_id=None):
        # 已经保存的旧任务沿用原入口完成，新的局内请求交给 Activity。
        legacy = self.conversations.reservation(connection, request.turn.social_turn_id)
        target = self.conversations if legacy else self._target(connection, request.turn)
        return target.create(connection, request, task_id=task_id)

    def cancel_turn(self, connection, turn_id, reason, at):
        self.conversations.cancel_turn(connection, turn_id, reason, at)
        self.activities.cancel_turn(connection, turn_id, reason, at)
