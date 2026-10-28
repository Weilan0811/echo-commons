from importlib.resources import files

import yaml

from echo_commons.modules.characters.domain.authoring import (
    AuthoringContent,
    BasicOutput,
    InterviewAnswer,
)


def authoring_template() -> dict:
    resource = files("echo_commons").joinpath("resources/authoring/template.yaml")
    value = yaml.safe_load(resource.read_text(encoding="utf-8"))
    value["limits"] = {
        "display_name": 80,
        "description": 8000,
        "story": 24000,
        "relationships": 40,
        "relationship_content": 4000,
        "interview_answers": 15,
        "interview_minimum": 10,
        "interview_batch": 5,
        "answer": 2000,
        "materials": 40000,
        "profile": 9000,
        "voice": 4000,
        "relational_dynamics": 4000,
        "introduction": 8000,
    }
    return value


def default_content(
    display_name: str,
    description: str,
    story: str = "",
    interview: tuple[InterviewAnswer, ...] = (),
    avatar_url: str | None = None,
) -> AuthoringContent:
    template = authoring_template()
    description = description.strip() or f"名字是{display_name}。"
    parts = [f"你叫{display_name}。", "## 人物描述\n" + description]
    return AuthoringContent(
        display_name=display_name,
        description=description,
        story=story,
        interview=interview,
        profile="\n\n".join(parts),
        voice=template["default_voice"].strip(),
        relational_dynamics=template["default_relational_dynamics"].strip(),
        avatar_url=avatar_url,
    )


def introduction_documents(content: AuthoringContent) -> BasicOutput:
    template = authoring_template()
    profile = []
    voice = []
    relations = []
    for path, label, text in content.introduction.source_fields():
        if path.startswith("speech."):
            destination = voice
        elif path in {
            "personality.stranger_style",
            "personality.close_style",
            "personality.boundaries",
        }:
            destination = relations
        else:
            destination = profile
        destination.append(f"{label}：{text}")
    identity = content.introduction.identity
    description = (
        "，".join(
            item for item in (content.display_name, identity.occupation, identity.residence) if item
        )
        + "。"
    )
    return BasicOutput(
        operation="basic",
        description=description,
        profile=f"你叫{content.display_name}。"
        + ("\n\n" + "。".join(profile) + "。" if profile else ""),
        voice="\n\n".join(voice) or template["default_voice"].strip(),
        relational_dynamics="\n\n".join(relations)
        or template["default_relational_dynamics"].strip(),
        changes=("根据已保存的自介资料组织正文；空项省略，未添加过去经历。",),
    )
