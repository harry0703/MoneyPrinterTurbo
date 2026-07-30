import os


def resolve_path_within_directory(
    base_dir: str,
    unsafe_path: str,
    *,
    require_file: bool = True,
) -> str:
    # 사용자가 넘기는 경로는 파일명, 상대 경로, 절대 경로일 수 있고 `../` 가 섞일 수도 있다.
    # 여기서 실제 경로로 일괄 해석한 뒤 commonpath 로 허용 디렉터리 안에 남아 있는지
    # 판정한다. 단순 문자열 접두사 비교보다 신뢰할 수 있어 심볼릭 링크, 중복 구분자,
    # 상대 경로 같은 경우를 모두 덮으며, 업로드·소재·작업 산출물 디렉터리처럼
    # 화이트리스트 디렉터리에 두루 쓸 수 있다.
    if not unsafe_path:
        raise ValueError("empty path is not allowed")

    base_dir_real = os.path.realpath(base_dir)
    candidate_path = unsafe_path
    if not os.path.isabs(candidate_path):
        candidate_path = os.path.join(base_dir_real, candidate_path)

    resolved_path = os.path.realpath(candidate_path)
    try:
        common_path = os.path.commonpath([base_dir_real, resolved_path])
    except ValueError as exc:
        # Windows 에서 드라이브 문자가 다르면 ValueError 가 난다. 이런 경로는 반드시 허용 디렉터리 밖이다.
        raise ValueError("path is outside the allowed directory") from exc

    if common_path != base_dir_real:
        raise ValueError("path is outside the allowed directory")

    if require_file and not os.path.isfile(resolved_path):
        raise ValueError("file does not exist")

    return resolved_path
