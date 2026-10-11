-- 自介卡是已有人物正文的编辑资料，旧正文保持原样，不建立额外记忆来源。
UPDATE character_authoring_drafts SET content_json=json_set(content_json,'$.introduction',json('{}'))
WHERE json_type(content_json,'$.introduction') IS NULL;
UPDATE custom_character_blueprints SET materials_json=json_set(materials_json,'$.introduction',json('{}'))
WHERE json_type(materials_json,'$.introduction') IS NULL;
