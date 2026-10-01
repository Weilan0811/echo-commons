import json

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.refs import OutputContractRef


def render_snapshot(
    snapshot: ContextSnapshot, contract: OutputContractRef, outputs: OutputRegistry
) -> str:
    schema = json.dumps(outputs.schema(contract), ensure_ascii=False)
    sections = [
        "根据当前角色的身份、视角和记忆作出回应。历史消息保留各自发送者身份。只有当前角色自己的消息属于你的发言。",
        "输出完整 JSON，遵循以下结构：\n" + schema,
        '决定保持沉默时，只返回 {"outcome":"silent"}，无需生成发言。',
        "thought 是私有思考；utterance 是对外发言；"
        "reply_to_message_id 仅填写可见消息的真实标识，或填写 null。",
        "用户要求查询，或现有材料不足以回答时，先调用获准的只读工具。"
        "工具参数只填写查询内容。收到工具结果后再生成最终 JSON。",
        "角色自身信息：\n" + snapshot.self.model_dump_json(),
        "自身记忆：\n" + snapshot.memory.model_dump_json(),
        "客观环境：\n" + snapshot.environment.model_dump_json(),
        "当前可见的公共信息：\n"
        + json.dumps(snapshot.perspective.public_facts, ensure_ascii=False),
    ]
    return "\n\n".join(sections)
