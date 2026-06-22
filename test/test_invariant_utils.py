import pytest
import sys
import os

# Add the app directory to the Python path to import the actual module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.utils.utils import md5


@pytest.mark.parametrize("payload", [
    # Exact exploit case: known MD5 collision input
    "d131dd02c5e6eec4693d9a0698aff95c2fcab58712467eab4004583eb8fb7f8955ad340609f4b30283e488832571415a085125e8f7cdc99fd91dbdf280373c5bd8823e3156348f5bae6dacd436c919c6dd53e2b487da03fd02396306d248cda0e99f33420f577ee8ce54b67080a80d1ec69821bcb6a8839396f9652b6ff72a70",
    # Boundary case: empty string
    "",
    # Valid input: typical password
    "MySecurePassword123!",
    # Another adversarial input: SQL injection attempt
    "' OR '1'='1",
    # Input with null byte
    "password\x00withnull",
])
def test_md5_hash_function_always_produces_hexdigest(payload):
    """Invariant: MD5 hash function must always return a 32-character hexadecimal string regardless of input content."""
    result = md5(payload)
    
    # Property 1: Result must be a string
    assert isinstance(result, str), f"MD5 output must be string, got {type(result)}"
    
    # Property 2: Result must be exactly 32 characters (MD5 hex digest length)
    assert len(result) == 32, f"MD5 hex digest must be 32 chars, got {len(result)}"
    
    # Property 3: Result must contain only hexadecimal characters (0-9, a-f)
    assert all(c in '0123456789abcdef' for c in result), f"MD5 output must be hex only: {result}"
    
    # Property 4: Same input must always produce same output (deterministic)
    second_result = md5(payload)
    assert result == second_result, f"MD5 must be deterministic for input: {payload}"