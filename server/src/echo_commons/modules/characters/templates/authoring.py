from importlib.resources import files

import yaml

from echo_commons.modules.characters.domain.authoring import AuthoringContent, InterviewAnswer


def authoring_template() -> dict:
    resource = files("echo_commons").joinpath("resources/authoring/template.yaml")
    value = yaml.safe_load(resource.read_text(encoding="utf-8"))
    value["limits"] = {
        "display_name": 80,
        "description": 8000,
        "story": 24000,
        "interview_answers": 15,
        "interview_minimum": 10,
        "interview_batch": 5,
        "answer": 2000,
        "materials": 40000,
        "profile": 8000,
        "voice": 4000,
        "relational_dynamics": 4000,
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
