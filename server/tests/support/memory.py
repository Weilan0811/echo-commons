from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.domain.sources import SourceKind
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.sealing import MemorySealing


def sealing(system):
    return MemorySealing(
        system.database,
        InstanceRepository(),
        ConversationRepository(),
        system.world,
        SegmentRepository(),
        ThoughtRepository(),
    )


def message_ids(segment):
    return tuple(
        source.source_id for source in segment.sources if source.kind is SourceKind.MESSAGE
    )
