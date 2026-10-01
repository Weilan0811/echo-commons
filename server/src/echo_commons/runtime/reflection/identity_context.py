from echo_commons.agents.contracts.context import IdentityContext
from echo_commons.services.identity import IdentityCatalog


def build_identity_context(catalog: IdentityCatalog, character_id: str) -> IdentityContext:
    baseline = catalog.default_baseline
    identity = catalog.character(character_id)
    return IdentityContext(
        contract_resource_id=baseline.resource_id,
        contract_content=baseline.content,
        contract_version=baseline.content_version,
        character_id=identity.resource_id,
        bundle_version=identity.content_version,
        profile_resource_id=identity.profile.resource_id,
        profile_content=identity.profile.content,
        profile_version=identity.profile.content_version,
        voice_resource_id=identity.voice.resource_id if identity.voice is not None else None,
        voice_content=identity.voice.content if identity.voice is not None else "",
        voice_version=identity.voice.content_version if identity.voice is not None else None,
        relational_dynamics_resource_id=(
            identity.relational_dynamics.resource_id
            if identity.relational_dynamics is not None
            else None
        ),
        relational_dynamics_content=(
            identity.relational_dynamics.content if identity.relational_dynamics is not None else ""
        ),
        relational_dynamics_version=(
            identity.relational_dynamics.content_version
            if identity.relational_dynamics is not None
            else None
        ),
    )


__all__ = ["build_identity_context"]
