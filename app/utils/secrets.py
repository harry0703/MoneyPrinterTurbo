def redact_secret(value: str, visible_prefix: int = 3, visible_suffix: int = 4) -> str:
    secret = str(value or "")
    if not secret:
        return ""

    visible = visible_prefix + visible_suffix
    if len(secret) <= visible:
        return "*" * len(secret)

    masked_length = len(secret) - visible
    return f"{secret[:visible_prefix]}{'*' * masked_length}{secret[-visible_suffix:]}"
