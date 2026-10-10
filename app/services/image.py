from __future__ import annotations

import base64
import io
import os
import re
import time
import uuid
import warnings
from typing import Any

from PIL import Image, UnidentifiedImageError
from loguru import logger
import requests

from app.config import config
from app.services.material import (
    OPENAI_IMAGE_DEFAULT_SIZES,
    OPENAI_IMAGE_ENDPOINT_PATH,
    OPENAI_IMAGE_KEY_ERROR_STATUS_CODES,
    OPENAI_IMAGE_MAX_ATTEMPTS,
    OPENAI_IMAGE_MAX_BYTES,
    OPENAI_IMAGE_MAX_PIXELS,
    OPENAI_IMAGE_REQUEST_TIMEOUT,
    OPENAI_IMAGE_RETRY_BACKOFF_SECONDS,
    OPENAI_IMAGE_RETRYABLE_STATUS_CODES,
    OpenAIImagePaidResultError,
    OpenAIImageUnconfirmedError,
    _OpenAIImageDecodeError,
    _get_tls_verify,
    _openai_image_download_bytes,
    _openai_image_http_failure,
    _redact_request_error,
    _response_json_safely,
    get_api_key,
)
from app.utils import utils


def is_image_service_configured(app_config: dict | None = None) -> bool:
    """
    Check whether OpenAI-compatible image generation is minimally configured.
    """
    cfg = config.app if app_config is None else app_config
    base_url = str(cfg.get("openai_image_base_url", "") or "").strip()
    model = str(cfg.get("openai_image_model", "") or "").strip()
    return bool(base_url and model)


def get_image_storage_dir(custom_dir: str = "") -> str:
    """
    Get or create storage directory for standalone generated images.
    """
    if custom_dir and os.path.isabs(custom_dir):
        os.makedirs(custom_dir, exist_ok=True)
        return custom_dir
    return utils.storage_dir("images", create=True)


def format_image_prompt(prompt: str, template: str | None = None) -> str:
    """
    Wrap the given prompt with a template if {prompt} or {term} placeholder is present.
    """
    prompt = prompt.strip()
    if not template:
        template = str(config.app.get("openai_image_prompt_template", "") or "").strip()
    if not template:
        return prompt

    if "{prompt}" in template:
        return template.replace("{prompt}", prompt)
    if "{term}" in template:
        return template.replace("{term}", prompt)
    return prompt


import random

_FIRST_NAMES_MALE = ["Ahmed", "Omar", "Zaid", "Tariq", "Hassan", "Youssef", "Kareem", "Mustafa", "Ali", "Hamza", "Fahad", "Sultan", "Samir", "Rami", "Bilal", "Adel"]
_FIRST_NAMES_FEMALE = ["Noor", "Sara", "Lina", "Maryam", "Zainab", "Fatima", "Aya", "Huda", "Salma", "Dina", "Rania", "Yasmin", "Reem", "Layla", "Mona", "Zahra"]
_LAST_NAMES = ["Al-Mansoor", "Al-Hashimi", "Al-Rawi", "Al-Saadi", "Al-Bayati", "Al-Khafaji", "Al-Obeidi", "Al-Janabi", "Al-Najjar", "Al-Qaisi", "Al-Dulaimi", "Al-Zubaidi"]
_DEPARTMENTS = ["Computer Science", "Information Technology", "Software Engineering", "Electrical Engineering", "Civil Engineering", "Biomedical Science", "Business Administration", "Architecture", "Cybersecurity", "Data Science", "Artificial Intelligence"]
_BLOOD_TYPES = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]


def generate_random_identity(index: int = 1) -> dict[str, str]:
    """Generate unique randomized personal identity information for batch card generation."""
    is_female = random.random() < 0.5
    first_name = random.choice(_FIRST_NAMES_FEMALE if is_female else _FIRST_NAMES_MALE)
    last_name = random.choice(_LAST_NAMES)
    father_name = random.choice(_FIRST_NAMES_MALE)
    full_name = f"{first_name} {father_name} {last_name}"
    
    dept = random.choice(_DEPARTMENTS)
    blood = random.choice(_BLOOD_TYPES)
    
    birth_year = random.randint(2001, 2005)
    birth_month = random.randint(1, 12)
    birth_day = random.randint(1, 28)
    dob = f"{birth_year}-{birth_month:02d}-{birth_day:02d}"
    
    student_id = f"2026{random.randint(10000, 99999)}"
    reg_no = f"REG-{random.randint(100000, 999999)}"
    serial_no = f"SN{random.randint(10000000, 99999999)}"
    phone = f"+964 77{random.randint(10, 99)} {random.randint(100, 999)} {random.randint(1000, 9999)}"
    email = f"{first_name.lower()}.{last_name.lower().replace('al-', '')}@univ-fictional.edu"
    
    photo_desc = (
        f"passport-style ID photo of a young {'female student with a gentle smile' if is_female else 'male student in formal collared shirt'}, natural realistic lighting"
    )
    
    return {
        "full_name": full_name,
        "gender": "Female" if is_female else "Male",
        "father_name": father_name,
        "student_id": student_id,
        "reg_no": reg_no,
        "serial_no": serial_no,
        "department": dept,
        "blood_type": blood,
        "dob": dob,
        "issue_date": "2026-02-01",
        "expiry_date": "2030-06-30",
        "phone": phone,
        "email": email,
        "photo_desc": photo_desc,
    }


def inject_dynamic_identity_to_prompt(base_prompt: str, item_index: int = 1) -> str:
    """Inject concise dynamic randomized personal identity while keeping the visual container 100% identical."""
    identity = generate_random_identity(item_index)
    
    variation_block = (
        f" Card details: Full Name: {identity['full_name']}, Student ID: {identity['student_id']}, "
        f"Department: {identity['department']}, Date of Birth: {identity['dob']}, Blood Type: {identity['blood_type']}, "
        f"Portrait Photo: {identity['photo_desc']}."
    )
    return f"{base_prompt}\n\n{variation_block}"


def analyze_reference_image_blueprint(
    image_bytes: bytes,
    user_prompt: str,
    vision_model: str = "",
    base_url: str = "",
    api_key: str = "",
) -> str:
    """
    Analyze reference image using a multimodal Vision LLM to produce an exact,
    photorealistic blueprint prompt that replicates the design structure 100%.
    """
    base_url = (base_url or str(config.app.get("openai_image_base_url", "") or "")).strip().rstrip("/")
    endpoint = f"{base_url}/{OPENAI_CHAT_COMPLETIONS_ENDPOINT_PATH}"

    # Default to available high-tier vision models
    if not vision_model:
        vision_model = "antigravity/gemini-3.7-flash-tiered"

    b64_img = base64.b64encode(image_bytes).decode("ascii")

    system_instruction = (
        "You are an expert design analysis and visual replication AI. "
        "Your task is to analyze the uploaded reference image in forensic detail "
        "(layout, exact colors, background gradients, fonts, typography hierarchy, shapes, logos, "
        "borders, element placements, photo box, barcodes) and synthesize a comprehensive, "
        "ultra-accurate image generation prompt that will reproduce the EXACT visual design and layout 100% identically.\n\n"
        "Incorporate the following user instructions and data substitutions while maintaining the visual container:\n"
        f"{user_prompt}\n\n"
        "Output ONLY the final descriptive image generation prompt. Do not add introductory or conversational text."
    )

    payload = {
        "model": vision_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": system_instruction},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
                ],
            }
        ],
    }

    if api_key:
        headers = {"Authorization": f"Bearer {api_key}"}
    else:
        cfg_key = get_api_key("openai_image_api_keys") if config.app.get("openai_image_api_keys") else ""
        headers = {"Authorization": f"Bearer {cfg_key}"} if cfg_key else {}

    logger.info(f"running vision blueprint analysis with model={vision_model}...")
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            proxies=config.proxy,
            verify=_get_tls_verify(),
            timeout=(30, 90),
        )
        if response.status_code == 200:
            body = response.json()
            choices = body.get("choices", [])
            if choices and isinstance(choices, list):
                content = choices[0].get("message", {}).get("content", "")
                if content and isinstance(content, str):
                    logger.info(f"vision analysis succeeded ({len(content)} chars)")
                    return content.strip()
        logger.warning(f"vision analysis returned status={response.status_code}: {response.text[:200]}")
    except Exception as e:
        logger.warning(f"vision analysis request failed: {e}")

    return user_prompt


def save_image_bytes(
    image_bytes: bytes,
    save_dir: str = "",
    prefix: str = "gen-image",
) -> tuple[str, int, int]:
    """
    Normalize and save image bytes as PNG.
    Returns (saved_path, width, height).
    """
    target_dir = get_image_storage_dir(save_dir)
    filename = f"{prefix}-{time.strftime('%Y%m%d_%H%M%S')}-{uuid.uuid4().hex[:8]}.png"
    image_path = os.path.join(target_dir, filename)

    if len(image_bytes) > OPENAI_IMAGE_MAX_BYTES:
        raise _OpenAIImageDecodeError("generated image exceeds size limit")

    image = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(image_bytes))
            if image.width * image.height > OPENAI_IMAGE_MAX_PIXELS:
                raise ValueError("generated image exceeds pixel limit")
            image.load()
    except (
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        if image is not None:
            image.close()
        raise _OpenAIImageDecodeError(f"{type(exc).__name__}: {exc}") from exc

    with image:
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            image = image.convert("RGB")
        image.save(image_path, format="PNG")
        width, height = image.size

    return image_path, width, height


OPENAI_IMAGE_EDITS_ENDPOINT_PATH = "images/edits"
OPENAI_CHAT_COMPLETIONS_ENDPOINT_PATH = "chat/completions"


def _extract_images_from_chat_response(body: Any, api_key: str = "") -> list[bytes]:
    """
    Extract generated image bytes from /chat/completions response.
    Supports markdown images `![...](data:image/...;base64,...)`, raw data URIs,
    image URLs, choices[].message.images, or multipart parts.
    """
    if not isinstance(body, dict):
        return []
    choices = body.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return []

    collected: list[bytes] = []

    def _try_b64(raw: str) -> bool:
        cleaned = raw.strip()
        if len(cleaned) < 100:
            return False
        try:
            b = base64.b64decode(cleaned)
            if len(b) > 50:
                collected.append(b)
                return True
        except Exception:
            pass
        return False

    def _try_url(u: str) -> bool:
        cleaned = u.strip()
        if cleaned.startswith(("http://", "https://")):
            img_b, _ = _openai_image_download_bytes(cleaned, api_key)
            if img_b:
                collected.append(img_b)
                return True
        return False

    for choice in choices:
        if not isinstance(choice, dict):
            continue
        msg = choice.get("message", {})
        if not isinstance(msg, dict):
            continue

        # Check images array field (e.g. msg.images)
        for field_name in ("images", "image_urls", "output_images"):
            field_val = msg.get(field_name)
            if isinstance(field_val, list):
                for item in field_val:
                    if isinstance(item, str):
                        if "base64," in item:
                            _try_b64(item.split("base64,", 1)[1])
                        elif item.startswith(("http://", "https://")):
                            _try_url(item)
                        else:
                            _try_b64(item)

        content = msg.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        url_obj = part.get("image_url", {})
                        url_str = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
                        if "base64," in url_str:
                            _try_b64(url_str.split("base64,", 1)[1])
                        elif url_str.startswith(("http://", "https://")):
                            _try_url(url_str)
                    elif part.get("type") == "image":
                        b64_val = part.get("image", "") or part.get("b64_json", "")
                        if isinstance(b64_val, str):
                            _try_b64(b64_val)
                    elif part.get("type") == "text":
                        text_val = part.get("text", "")
                        if isinstance(text_val, str):
                            # extract markdown images
                            for m in re.findall(r"!\[.*?\]\((.*?)\)", text_val):
                                if "base64," in m:
                                    _try_b64(m.split("base64,", 1)[1])
                                elif m.startswith(("http://", "https://")):
                                    _try_url(m)
                            # extract data URIs
                            for m in re.findall(r"data:image/[a-zA-Z0-9+.-]+;base64,([A-Za-z0-9+/=]+)", text_val):
                                _try_b64(m)
        elif isinstance(content, str):
            # Check for markdown image format: ![alt](url or data URI)
            for m in re.findall(r"!\[.*?\]\((.*?)\)", content):
                if "base64," in m:
                    _try_b64(m.split("base64,", 1)[1])
                elif m.startswith(("http://", "https://")):
                    _try_url(m)

            # Check for data URI in plain text
            for m in re.findall(r"data:image/[a-zA-Z0-9+.-]+;base64,([A-Za-z0-9+/=]+)", content):
                _try_b64(m)

            # Check for pure URLs in text
            for m in re.findall(r"https?://[^\s\)\"']+", content):
                if any(ext in m.lower() for ext in (".png", ".jpg", ".jpeg", ".webp", "image", "generations")):
                    _try_url(m)

            # If content itself looks like raw base64
            if not collected and len(content.strip()) > 500 and not any(c in content for c in (" ", "\n", "\t")):
                _try_b64(content)

    return collected


def request_openai_image_generation(
    endpoint: str,
    payload: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    api_key_override: str = "",
) -> tuple[list[bytes], str]:
    """
    Send /images/generations or /images/edits request and return a list of image bytes or failure reason.
    Supports both JSON payload and multipart/form-data (files + data).
    """
    if api_key_override:
        configured_keys = [api_key_override]
    else:
        api_keys = config.app.get("openai_image_api_keys")
        if isinstance(api_keys, (list, tuple)):
            configured_keys = [k for k in api_keys if str(k or "").strip()]
        elif str(api_keys or "").strip():
            configured_keys = [str(api_keys).strip()]
        else:
            configured_keys = []

    failure_detail = "no request attempt was made"
    for attempt in range(1, OPENAI_IMAGE_MAX_ATTEMPTS + 1):
        if api_key_override:
            api_key = api_key_override
        else:
            api_key = get_api_key("openai_image_api_keys") if configured_keys else ""

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        retryable = False
        try:
            if files is not None:
                response = requests.post(
                    endpoint,
                    data=data or {},
                    files=files,
                    headers=headers,
                    proxies=config.proxy,
                    verify=_get_tls_verify(),
                    timeout=OPENAI_IMAGE_REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
            else:
                response = requests.post(
                    endpoint,
                    json=payload or {},
                    headers=headers,
                    proxies=config.proxy,
                    verify=_get_tls_verify(),
                    timeout=OPENAI_IMAGE_REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
        except requests.exceptions.ConnectTimeout as e:
            failure_detail = f"connect timeout: detail={_redact_request_error(e, api_key)}"
            retryable = True
        except Exception as e:
            raise OpenAIImageUnconfirmedError(
                f"unconfirmed image request: {type(e).__name__}, detail={_redact_request_error(e, api_key)}"
            ) from e
        else:
            status = int(getattr(response, "status_code", 200) or 200)
            if 300 <= status < 400:
                response.close()
                raise OpenAIImageUnconfirmedError(
                    "image generation returned a redirect; request terminated for billing safety"
                )
            if status in OPENAI_IMAGE_KEY_ERROR_STATUS_CODES:
                failure_detail = _openai_image_http_failure(response, status, api_key)
                retryable = len(configured_keys) > 1
            elif status in OPENAI_IMAGE_RETRYABLE_STATUS_CODES:
                failure_detail = _openai_image_http_failure(response, status, api_key)
                retryable = True
            elif status >= 400:
                return [], _openai_image_http_failure(response, status, api_key)
            else:
                body = _response_json_safely(response)
                collected_bytes: list[bytes] = []

                if isinstance(body, dict):
                    data_list = body.get("data")
                    if isinstance(data_list, list):
                        for entry in data_list:
                            if not isinstance(entry, dict):
                                continue
                            b64_payload = entry.get("b64_json")
                            if b64_payload and isinstance(b64_payload, str):
                                try:
                                    img_b = base64.b64decode(b64_payload)
                                    collected_bytes.append(img_b)
                                except Exception as e:
                                    logger.warning(f"failed to decode b64_json: {e}")
                            else:
                                img_url = entry.get("url")
                                if isinstance(img_url, str) and img_url.startswith(("http://", "https://")):
                                    img_b, err = _openai_image_download_bytes(img_url, api_key)
                                    if img_b is not None:
                                        collected_bytes.append(img_b)
                                    else:
                                        logger.warning(f"failed to download image url: {err}")

                    if not collected_bytes:
                        collected_bytes.extend(_extract_images_from_chat_response(body))

                if collected_bytes:
                    return collected_bytes, ""

                failure_detail = f"empty image payload from provider: {_openai_image_response_message(body) or 'data=[]'}"
                retryable = True

        if retryable and attempt < OPENAI_IMAGE_MAX_ATTEMPTS:
            backoff_seconds = OPENAI_IMAGE_RETRY_BACKOFF_SECONDS[
                min(attempt - 1, len(OPENAI_IMAGE_RETRY_BACKOFF_SECONDS) - 1)
            ]
            logger.warning(
                f"openai image request failed, retrying: attempt={attempt}/{OPENAI_IMAGE_MAX_ATTEMPTS}, "
                f"next_retry_in={backoff_seconds}s, detail={failure_detail}"
            )
            time.sleep(backoff_seconds)
            continue
        return [], failure_detail

    return [], failure_detail


def resolve_image_endpoint(base_url: str, has_reference_image: bool = False) -> str:
    """
    Resolve the exact endpoint URL from base_url.
    - If base_url ends with a specific endpoint (e.g. /images/edits or /images/generations), uses it as-is.
    - Otherwise defaults to /images/generations.
    """
    cleaned = base_url.strip().rstrip("/")
    if (
        cleaned.endswith("/images/generations")
        or cleaned.endswith("/images/edits")
        or cleaned.endswith("/chat/completions")
    ):
        return cleaned
    return f"{cleaned}/{OPENAI_IMAGE_ENDPOINT_PATH}"


def generate_images(
    prompt: str,
    size: str = "",
    n: int = 1,
    model: str = "",
    base_url: str = "",
    api_key: str = "",
    prompt_template: str = "",
    save_dir: str = "",
    reference_image_bytes: bytes | None = None,
    cached_blueprint: str = "",
) -> list[dict[str, Any]]:
    """
    Generate one or more images from a prompt using OpenAI-compatible text-to-image API.
    If reference_image_bytes is provided:
      1. Analyzes the sample image with Vision to extract exact visual layout, colors, and design.
      2. Sends the visual blueprint to the image generation model for high-fidelity replication.
      3. For multiple images (n > 1), randomizes individual credentials on each card while preserving the template.
    """
    prompt = prompt.strip()
    if not prompt and not cached_blueprint:
        raise ValueError("Prompt cannot be empty")

    base_url = (base_url or str(config.app.get("openai_image_base_url", "") or "")).strip().rstrip("/")
    model = (model or str(config.app.get("openai_image_model", "") or "")).strip()

    if not base_url:
        raise ValueError("openai_image_base_url is not configured")
    if not model:
        raise ValueError("openai_image_model is not configured")

    image_size = size.strip() or str(config.app.get("openai_image_size", "") or "").strip() or "1024x1024"
    total_images = max(1, int(n))
    base_prompt = format_image_prompt(prompt, prompt_template)

    # Use cached blueprint or analyze reference image
    if cached_blueprint:
        active_blueprint = cached_blueprint
        logger.info("reusing cached design blueprint from previous generation...")
    elif reference_image_bytes is not None:
        logger.info("analyzing sample image to extract exact visual design, colors, and layout...")
        extracted_bp = analyze_reference_image_blueprint(
            image_bytes=reference_image_bytes,
            user_prompt=base_prompt,
            vision_model="antigravity/gemini-3.7-flash-tiered",
            base_url=base_url,
            api_key=api_key.strip(),
        )
        active_blueprint = extracted_bp or base_prompt
    else:
        active_blueprint = base_prompt

    endpoint = resolve_image_endpoint(base_url, has_reference_image=bool(reference_image_bytes))

    logger.info(
        f"generating {total_images} image(s) using model={model}: endpoint={endpoint}, "
        f"size={image_size}"
    )

    results: list[dict[str, Any]] = []
    last_failure = ""

    for item_idx in range(1, total_images + 1):
        if total_images > 1 or reference_image_bytes is not None or cached_blueprint:
            prompt_for_item = inject_dynamic_identity_to_prompt(active_blueprint, item_idx)
        else:
            prompt_for_item = active_blueprint

        logger.info(f"requesting image {item_idx}/{total_images} with model={model}...")

        payload = {
            "model": model,
            "prompt": prompt_for_item,
            "n": 1,
            "size": image_size,
        }
        image_bytes_list, failure_detail = request_openai_image_generation(
            endpoint=endpoint,
            payload=payload,
            api_key_override=api_key.strip(),
        )

        if not image_bytes_list:
            last_failure = failure_detail
            logger.warning(f"failed to generate image {item_idx}/{total_images}: {failure_detail}")
            continue

        for img_bytes in image_bytes_list:
            saved_path, width, height = save_image_bytes(
                img_bytes,
                save_dir=save_dir,
                prefix="openai-image",
            )
            file_size = os.path.getsize(saved_path) if os.path.isfile(saved_path) else len(img_bytes)
            record = {
                "path": saved_path,
                "filename": os.path.basename(saved_path),
                "width": width,
                "height": height,
                "size_bytes": file_size,
                "prompt": prompt,
                "final_prompt": prompt_for_item,
                "blueprint": active_blueprint,
                "model": model,
                "created_at": time.time(),
            }
            results.append(record)

    if not results:
        raise RuntimeError(f"Image generation failed: {last_failure or 'No images returned'}")

    logger.info(f"successfully generated and saved {len(results)}/{total_images} images to {get_image_storage_dir(save_dir)}")
    return results


def list_saved_images(save_dir: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """
    List existing generated images in storage/images directory.
    """
    target_dir = get_image_storage_dir(save_dir)
    if not os.path.isdir(target_dir):
        return []

    images = []
    for entry in os.scandir(target_dir):
        if entry.is_file() and entry.name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            stat = entry.stat()
            images.append({
                "path": entry.path,
                "filename": entry.name,
                "size_bytes": stat.st_size,
                "created_at": stat.st_mtime,
            })

    images.sort(key=lambda x: x["created_at"], reverse=True)
    return images[:limit]
