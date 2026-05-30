import os


def resolve_path_within_directory(
    base_dir: str,
    unsafe_path: str,
    *,
    require_file: bool = True,
) -> str:
    # 사용자가 전달한 경로는 파일명, 상대 경로, 절대 경로일 수 있고, `../`가 끼어 있을 수도 있습니다.
    # 여기서는 이를 통일하여 실제 경로로 해석하고, commonpath로 그 경로가 여전히 허용된 디렉터리 내에 있는지 판단합니다.
    # 이 방식은 단순히 문자열 접두사를 판단하는 것보다 신뢰할 수 있으며, 심볼릭 링크, 중복 구분자, 상대 경로
    # 같은 상황을 커버할 수 있어, 업로드 디렉터리, 소재 디렉터리, 작업 산출물 디렉터리 같은 화이트리스트 디렉터리에 적합합니다.
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
        # Windows에서 서로 다른 드라이브 문자는 ValueError를 발생시키며, 이런 경로는 반드시 허용된 디렉터리에 속하지 않습니다.
        raise ValueError("path is outside the allowed directory") from exc

    if common_path != base_dir_real:
        raise ValueError("path is outside the allowed directory")

    if require_file and not os.path.isfile(resolved_path):
        raise ValueError("file does not exist")

    return resolved_path
