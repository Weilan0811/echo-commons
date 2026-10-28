def compact_memory_text(text: str) -> str:
    lines = text.split("\n", 2)
    if len(lines) == 3 and lines[0] == "记忆类型：fact" and lines[1].startswith("主题："):
        topic = lines[1].removeprefix("主题：")
        if topic and lines[2].startswith(topic):
            return lines[0] + "\n" + lines[2]
    return text
