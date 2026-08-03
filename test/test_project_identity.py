"""프로젝트 이름."""

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD_NAME = re.compile(r"MoneyPrinterTurbo", re.IGNORECASE)
# 바꾸면 안 되는 것들.
#  - harry0703/ : 갈라져 나온 원본. 출처 표기다.
#  - aff=, utm_term= : 원본의 제휴 코드. 우리 것으로 바꾸면 없는 코드를 쓰게 된다.
#  - raidostar/ : GitHub 저장소 주소. 저장소 이름을 바꾸면 기존 클론과 링크가
#    끊기므로 코드에서 결정할 일이 아니다. 저장소를 옮기면 이 예외를 지운다.
UPSTREAM = ("harry0703/", "raidostar/", "aff=", "utm_term=")
SEARCH_SUFFIXES = {".py", ".toml", ".yml", ".yaml", ".json", ".html", ".lock", ".ipynb", ".md"}
SKIP_DIRS = {".git", ".venv", "storage", ".redteam", "__pycache__", "node_modules"}


def _tracked_files():
    """
    커밋된 파일만 본다.

    `rglob` 으로 훑으면 영상 작업이 남긴 산출물과 로컬 메모까지 들어온다. 그런
    파일에 옛 이름이 들어 있다는 이유로 검사가 실패하면, 정작 저장소는 멀쩡한데
    아무도 못 고치는 실패가 된다.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for name in listing.split("\0"):
        if not name:
            continue
        path = ROOT / name
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in SEARCH_SUFFIXES or path.name.startswith("Dockerfile"):
            yield path


class TestTheOldNameIsGone(unittest.TestCase):
    def test_no_identity_string_still_says_the_old_name(self):
        """
        이름을 바꾸다 만 자리가 남으면, 화면·로그·컨테이너 경로가 서로 다른 이름을
        말한다. 업스트림을 가리키는 링크와 제휴 코드는 그대로 두어야 한다.
        """
        offenders = []
        for path in _tracked_files():
            if path.name == Path(__file__).name:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            # 줄 단위로 본다. 좁은 창으로 보면 `[MoneyPrinterTurbo](https://...)`
            # 처럼 이름 뒤에 주소가 오는 링크를 놓친다.
            for number, line in enumerate(text.splitlines(), start=1):
                if OLD_NAME.search(line) and not any(m in line for m in UPSTREAM):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}")

        self.assertEqual(offenders, [], f"옛 이름이 남아 있다: {offenders}")

    def test_the_readme_says_where_this_came_from(self):
        """
        이름을 바꾸면서 출처를 지우면 안 된다. 영상 파이프라인 대부분이 그쪽 코드다.
        """
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("## 만든 것에 대해", readme)
        credit = readme.split("## 만든 것에 대해", 1)[1]
        self.assertIn("harry0703/MoneyPrinterTurbo", credit)


class TestOneIdentity(unittest.TestCase):
    """이름을 바꾸다 보면 설치 안내와 배포 대상이 서로 다른 곳을 가리키게 된다."""

    def _read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_the_clone_url_points_at_a_repository_that_exists(self):
        """
        저장소 이름은 GitHub 에서 바꾸지 않았다. 안내문만 새 이름으로 바꾸면
        따라 하는 사람이 없는 주소를 클론한다.
        """
        for name in ("README.md", "README-en.md"):
            for line in self._read(name).splitlines():
                if "git clone" in line and "github.com" in line:
                    with self.subTest(readme=name, line=line.strip()):
                        self.assertIn("raidostar/MoneyPrinterTurbo", line)

    def test_the_container_image_is_published_under_our_owner(self):
        """
        워크플로는 이 저장소의 토큰으로 올린다. 다른 소유자 이름으로 두면 올릴 수도
        없고, 받는 쪽은 없는 이미지를 가리킨다.
        """
        # 문서도 같이 본다. 안내문만 예전 소유자를 가리키면, 따라 하는 사람은
        # 워크플로가 올리지도 않는 이미지를 받으려 한다.
        for name in (
            ".github/workflows/docker-ghcr.yml",
            "docker-compose.release.yml",
            "README.md",
            "README-en.md",
        ):
            text = self._read(name)
            for line in text.splitlines():
                if "ghcr.io/" in line:
                    with self.subTest(file=name, line=line.strip()):
                        self.assertIn("ghcr.io/raidostar/", line)


class TestOperationalLinksPointHere(unittest.TestCase):
    """설치와 신고는 이 포크로 와야 한다. 출처 표기와는 다른 문제다."""

    def test_the_skill_installer_downloads_this_fork(self):
        """
        업스트림 아카이브를 shipcast 라는 이름으로 설치하면, 여기서 한 보안 수정과
        기능이 빠진 코드를 쓰게 된다.
        """
        source = (ROOT / "docs/skill/mpt_agent.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            if "archive/refs/heads" in line:
                with self.subTest(line=line.strip()):
                    self.assertIn("raidostar/", line)

    def test_releases_issues_and_pulls_point_here(self):
        """
        원본 릴리스로 안내하면 여기 수정이 빠진 빌드를 받게 되고, 여기서 난 문제를
        원본에 신고하게 된다. 화면의 버그 신고 링크도 같은 문제다.
        """
        # 프로젝트 저장소의 운영 링크만 본다. `mpt-assets/releases/download/...`
        # 같은 데모 이미지 주소는 코드도 신고 창구도 아니다.
        owners = re.compile(
            r"github\.com/([^/\s)\"']+)/MoneyPrinterTurbo/(?:releases|issues|pulls)"
        )
        for name in ("README.md", "README-en.md", "webui/Main.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for owner in owners.findall(text):
                with self.subTest(file=name, owner=owner):
                    self.assertEqual(owner, "raidostar")


class TestNoBorrowedNumbers(unittest.TestCase):
    """다른 저장소의 지표를 이 프로젝트 것처럼 보여주면 안 된다."""

    BADGES = ("star-history.com", "shields.io/github/v/release", "shields.io/github/downloads")

    def test_no_readme_shows_another_repositorys_stats(self):
        """
        원본의 별 그래프와 다운로드 수를 그대로 달아 두면, 여기 숫자가 아닌 것을
        여기 성과로 읽히게 한다.
        """
        for name in ("README.md", "README-en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for badge in self.BADGES:
                with self.subTest(readme=name, badge=badge):
                    self.assertNotIn(badge, text)


class TestCodeIsFetchedFromHere(unittest.TestCase):
    """
    설치 경로가 원본을 가리키면, 따라 하는 사람은 이 포크의 보안 수정과 기능이
    빠진 코드를 shipcast 라는 이름으로 돌리게 된다.

    하나씩 잡는 대신 코드를 내려받는 주소 전체를 본다. 데모 이미지처럼 코드가
    아닌 자산 링크는 대상이 아니다.
    """

    FETCHES_CODE = re.compile(
        r"https?://[^\s\"')]*?(?:\.git\b|/archive/refs/|raw\.githubusercontent\.com/[^\s\"')]*)"
    )

    def test_every_install_url_points_at_this_fork(self):
        for path in _tracked_files():
            if path.name == Path(__file__).name:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            for url in self.FETCHES_CODE.findall(text):
                if "github" not in url:
                    continue
                with self.subTest(file=str(path.relative_to(ROOT)), url=url):
                    self.assertIn("raidostar/", url)


class TestTheRenamedNotebookIsReachable(unittest.TestCase):
    def test_the_colab_badge_opens_the_notebook_that_exists(self):
        """
        이름을 바꾸다 보면 링크 속 파일명만 바뀌고 파일은 그대로 남는다. 그러면
        안내된 한 번 클릭 설치가 404 가 된다.
        """
        text = (ROOT / "README-en.md").read_text(encoding="utf-8")
        self.assertIn("docs/shipcast.ipynb", text)
        self.assertTrue((ROOT / "docs/shipcast.ipynb").exists())

        for relative in re.findall(r"blob/main/([A-Za-z0-9_./-]+)", text):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).exists(), f"{relative} 가 없다")


if __name__ == "__main__":
    unittest.main()
