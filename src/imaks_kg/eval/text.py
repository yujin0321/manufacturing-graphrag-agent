"""유사도 문장 만들기. 정의서 2장: condition + 공백 + action. 소문자화하지 않는다."""


def similarity_text(condition: str, action: str) -> str:
    return f"{condition or ''} {action or ''}".strip()
