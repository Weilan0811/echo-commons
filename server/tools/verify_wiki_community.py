import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.modules.characters.domain.authoring import CalibrateRequest
from echo_commons.modules.characters.domain.people import PersonBinding, PersonRegistration
from echo_commons.modules.characters.services.wiki_authoring import WikiPreparation


async def verify(arguments):
    root = arguments.output
    root.mkdir(parents=True, exist_ok=True)
    settings = load_settings(arguments.settings).model_copy(
        update={
            "database_path": str(root / "community.sqlite3"),
            "asset_directory": str(root / "assets"),
            "worker_enabled": False,
            "log_path": str(root / "verification.log"),
        }
    )
    records = [json.loads(path.read_text(encoding="utf-8")) for path in arguments.material]
    if any(not item.get("author_review") for item in records):
        raise ValueError("Supply author-reviewed material with explicit person selections")
    player, community = "wiki-author", "wiki-community"
    report = dict(
        community_name=arguments.community,
        community_id=community,
        database=settings.database_path,
        characters=[],
        checks=[],
    )
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else dict(people={}, characters={})
    )

    def checkpoint():
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    async with application_lifecycle(settings) as app:
        app.communities.register_player("老师", player_id=player)
        current = app.communities.create(
            arguments.community, "Asia/Shanghai", community_id=community, player_id=player
        )
        if current.status.value != "active":
            app.communities.update(
                community, expected_version=current.state_version, status="active", player_id=player
            )
        people = manifest["people"]
        for record in records:
            proposal = WikiPreparation.model_validate(record["proposal"])
            for name, description in [
                (proposal.display_name, "作者确认的测试角色"),
                *[(item.name, item.identity_hint) for item in proposal.relationship_suggestions],
            ]:
                if name not in people:
                    person = app.people.register(
                        PersonRegistration(
                            player_id=player,
                            person_id=uuid4(),
                            display_name=name,
                            description=description,
                        )
                    )
                    people[name] = person["person_id"]
                    checkpoint()
        for index, record in enumerate(records):
            proposal = WikiPreparation.model_validate(record["proposal"])
            progress = manifest["characters"].setdefault(proposal.display_name, {})
            relationships = [
                dict(
                    relationship_id=str(uuid4()),
                    target_person_id=people[item.name],
                    target_name=item.name,
                    content=item.content,
                )
                for item in proposal.relationship_suggestions
            ]
            content = proposal.content(
                person_id=people[proposal.display_name], relationships=relationships
            )
            if progress.get("blueprint_id"):
                blueprint = app.authoring.blueprint(player, progress["blueprint_id"])
            else:
                if progress.get("draft_id"):
                    draft = app.authoring.get(player, progress["draft_id"])
                    draft = app.authoring.update(
                        player, draft["draft_id"], draft["revision"], content
                    )
                else:
                    draft, _ = app.authoring.create(player, str(uuid4()), content)
                    progress["draft_id"] = draft["draft_id"]
                    checkpoint()
                for stage in ("basic", "story"):
                    draft = app.authoring.confirm_stage(
                        player, draft["draft_id"], draft["revision"], stage
                    )
                candidate, status = await app.authoring.generate(
                    player,
                    draft["draft_id"],
                    CalibrateRequest(
                        candidate_id=uuid4(),
                        expected_revision=draft["revision"],
                        operation="calibrate",
                    ),
                )
                if status != 201 or candidate["output"]["conflicts"]:
                    raise RuntimeError(
                        dict(status=status, conflicts=candidate.get("output", {}).get("conflicts"))
                    )
                draft = app.authoring.accept(
                    player, draft["draft_id"], draft["revision"], candidate["candidate_id"]
                )
                blueprint, _ = app.authoring.confirm(player, draft["draft_id"], draft["revision"])
                progress["blueprint_id"] = blueprint["blueprint_id"]
                checkpoint()
            created = not progress.get("character_id")
            character = app.characters.create(
                community,
                blueprint["blueprint_id"],
                character_id=f"wiki-character-{index}",
                player_id=player,
                memory_mode="full",
            )
            progress["character_id"] = character.character_id
            checkpoint()
            if character.memory_status.value == "failed":
                app.characters.retry_memory(community, character.character_id, player_id=player)
            await app.supervisor.workers["character-relationship-initialization"].run_once()
            with app.database.read() as connection:
                row = connection.execute(
                    "SELECT * FROM memory_initializations WHERE character_id=?",
                    (character.character_id,),
                ).fetchone()
                assert row["relationship_output_json"] is not None, dict(row)
                if index == 0 and (created or len(app.characters.list(community)) == 1):
                    assert (
                        connection.execute(
                            "SELECT count(*) FROM relationship_state WHERE observer_character_id=?",
                            (character.character_id,),
                        ).fetchone()[0]
                        == 0
                    )
                    report["checks"].append("对方未加入时，保存关系分析结果，未创建虚假成员")
                elif index > 0:
                    count = connection.execute(
                        "SELECT count(*) FROM relationship_state "
                        "WHERE observer_character_id=? AND target_id=?",
                        ("wiki-character-0", character.character_id),
                    ).fetchone()[0]
                    assert count == 1, (
                        "Late character binding must activate the waiting relationship"
                    )
                    report["checks"].append("后加入角色自动关联并应用等待中的单向关系")
            report["characters"].append(
                dict(
                    name=proposal.display_name,
                    character_id=character.character_id,
                    blueprint_id=blueprint["blueprint_id"],
                    person_id=people[proposal.display_name],
                    relationship_count=len(relationships),
                    source_url=record["source_url"],
                )
            )
        teacher = PersonBinding(
            player_id=player, person_id=people["老师"], actor_kind="player", actor_id=player
        )
        app.people.bind(community, teacher)
        with app.database.read() as connection:
            before = [
                tuple(row)
                for row in connection.execute(
                    "SELECT * FROM relationship_state ORDER BY observer_character_id,target_id"
                )
            ]
            evidence_count = connection.execute(
                "SELECT count(*) FROM relation_evidence"
            ).fetchone()[0]
        app.people.bind(community, teacher)
        with app.database.read() as connection:
            assert before == [
                tuple(row)
                for row in connection.execute(
                    "SELECT * FROM relationship_state ORDER BY observer_character_id,target_id"
                )
            ]
            assert (
                evidence_count
                == connection.execute("SELECT count(*) FROM relation_evidence").fetchone()[0]
            )
        report["checks"].append("玩家身份关联成功，重复关联不重复写入证据或改变分数")
        await app.supervisor.start()
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            characters = app.characters.list(community)
            if any(item.memory_status.value == "failed" for item in characters):
                raise RuntimeError(
                    [
                        (item.character_id, item.memory_error_code, item.memory_phase)
                        for item in characters
                    ]
                )
            if all(item.memory_status.value == "ready" for item in characters):
                break
            await asyncio.sleep(1)
        else:
            raise TimeoutError("Real memory initialization did not finish")
        with app.database.read() as connection:
            report["relationships"] = [
                dict(row) for row in connection.execute("SELECT * FROM relationship_state")
            ]
            report["memory_fact_count"] = connection.execute(
                "SELECT count(*) FROM memory_facts"
            ).fetchone()[0]
            report["checks"].append("两位角色完成真实模型人设校准、关系分析和完整记忆初始化")
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="根据已审核百科材料创建真实测试社群")
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--material", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--community", required=True)
    asyncio.run(verify(parser.parse_args()))


if __name__ == "__main__":
    main()
