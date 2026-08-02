"""소재 한 건의 공통 모양."""

from dataclasses import dataclass, field

# 제목과 본문은 그대로 프롬프트로 흘러간다. 다른 입구와 같은 상한을 받아야 한다.
MAX_TITLE_LENGTH = 300
MAX_TEXT_LENGTH = 4000
MAX_URL_LENGTH = 2000
MAX_ID_LENGTH = 64
MAX_TAGS = 10
MAX_TAG_LENGTH = 40


@dataclass(frozen=True)
class SourceItem:
    """
    어디서 왔든 카드로 만들 수 있는 최소 단위.

    소스마다 필드 이름이 다르고 없는 값도 있다. 여기서 한 모양으로 맞춰 두면
    카드 생성 쪽이 소스를 몰라도 된다.
    """

    source: str
    item_id: str
    title: str
    url: str = ""
    discussion_url: str = ""
    points: int = 0
    comment_count: int = 0
    author: str = ""
    created_at: str = ""
    text: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        # frozen dataclass 라 object.__setattr__ 로 정규화한다. 외부에서 온 값이라
        # 길이와 타입을 여기서 한 번에 정리해, 이후 단계가 다시 검사하지 않게 한다.
        object.__setattr__(self, "title", _clip(self.title, MAX_TITLE_LENGTH))
        object.__setattr__(self, "text", _clip(self.text, MAX_TEXT_LENGTH))
        object.__setattr__(self, "url", _clip(self.url, MAX_URL_LENGTH))
        object.__setattr__(
            self, "discussion_url", _clip(self.discussion_url, MAX_URL_LENGTH)
        )
        object.__setattr__(self, "author", _clip(self.author, 100))
        object.__setattr__(self, "item_id", _clip(self.item_id, MAX_ID_LENGTH))
        object.__setattr__(self, "created_at", _clip(self.created_at, 40))
        # 태그는 소스가 몇 개든 붙여 보낼 수 있다. 개수와 길이를 여기서 묶는다.
        object.__setattr__(
            self,
            "tags",
            tuple(
                _clip(tag, MAX_TAG_LENGTH)
                for tag in tuple(self.tags)[:MAX_TAGS]
                if _clip(tag, MAX_TAG_LENGTH)
            ),
        )


def _clip(value, limit: int) -> str:
    """외부 값을 로그와 프롬프트에 실을 수 있는 문자열로 만든다."""
    text = str(value or "")
    # 제어문자가 섞이면 로그를 보는 화면이 조작되고 자막에도 그대로 들어간다.
    text = "".join(char for char in text if char.isprintable() or char == "\n")
    return " ".join(text.split())[:limit]
