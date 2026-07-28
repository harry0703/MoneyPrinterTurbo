import io
import os
import re
from typing import Optional

import requests
from loguru import logger
from PIL import Image

from app.config import config
from app.utils import utils

_WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_COMMONS_FILEPATH = "https://commons.wikimedia.org/wiki/Special:FilePath/{filename}"
_LOGO_PROPERTY = "P154"
_HTTP_TIMEOUT = (15, 30)


def _tls_verify() -> bool:
    tls_verify = config.app.get("tls_verify", True)
    if isinstance(tls_verify, str):
        tls_verify = tls_verify.strip().lower() not in ("0", "false", "no", "off")
    return bool(tls_verify)


def _cache_path(company_name: str) -> str:
    cache_dir = utils.storage_dir("cache_logos", create=True)
    key = re.sub(r"[^a-z0-9]+", "-", company_name.strip().lower()).strip("-")
    return os.path.join(cache_dir, f"{key}.png")


def _find_wikidata_logo_filename(company_name: str) -> Optional[str]:
    search_params = {
        "action": "wbsearchentities",
        "search": company_name,
        "language": "en",
        "format": "json",
        "type": "item",
        "limit": 1,
    }
    r = requests.get(
        _WIKIDATA_API,
        params=search_params,
        proxies=config.proxy,
        verify=_tls_verify(),
        timeout=_HTTP_TIMEOUT,
    )
    results = (r.json() or {}).get("search") or []
    if not results:
        return None
    entity_id = results[0]["id"]

    claims_params = {
        "action": "wbgetclaims",
        "entity": entity_id,
        "property": _LOGO_PROPERTY,
        "format": "json",
    }
    r = requests.get(
        _WIKIDATA_API,
        params=claims_params,
        proxies=config.proxy,
        verify=_tls_verify(),
        timeout=_HTTP_TIMEOUT,
    )
    claims = ((r.json() or {}).get("claims") or {}).get(_LOGO_PROPERTY)
    if not claims:
        return None
    return claims[0]["mainsnak"]["datavalue"]["value"]


def fetch_company_logo(company_name: str) -> str:
    """
    解析公司名到本地缓存的 Logo PNG 路径；任何失败都返回空字符串，
    调用方据此跳过该公司的 Logo 叠加，不应让整条视频生成任务失败。
    """
    try:
        # Compute cache path (may raise FileExistsError on TOCTOU race or
        # AttributeError on non-string company_name; both must degrade to "")
        cache_path = _cache_path(company_name)
        if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
            return cache_path

        filename = _find_wikidata_logo_filename(company_name)
        if not filename:
            logger.warning(f"no Wikidata logo (P154) found for company: {company_name}")
            return ""

        url = _COMMONS_FILEPATH.format(filename=filename.replace(" ", "_")) + "?width=512"
        r = requests.get(
            url, proxies=config.proxy, verify=_tls_verify(), timeout=_HTTP_TIMEOUT
        )
        if r.status_code != 200 or not r.content:
            logger.warning(
                f"failed to download logo for {company_name}: HTTP {r.status_code}"
            )
            return ""

        # Validate downloaded bytes are a decodable image before caching
        try:
            img = Image.open(io.BytesIO(r.content))
            img.verify()
        except Exception as img_err:
            logger.warning(
                f"downloaded bytes for {company_name} are not a valid image: {img_err}"
            )
            return ""

        with open(cache_path, "wb") as f:
            f.write(r.content)
        return cache_path
    except Exception as e:
        logger.warning(f"failed to fetch logo for company {company_name}: {e}")
        return ""
