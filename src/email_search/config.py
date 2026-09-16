"""설정. 환경변수 접두어 EMS_. 모두 선택이며 키가 없어도 동작한다(익명 한도)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(f"EMS_{name}", default)


@dataclass
class Settings:
    contact_email: str = field(default_factory=lambda: _env("CONTACT_EMAIL"))  # OpenAlex polite pool·Unpaywall 파라미터·User-Agent
    openalex_api_key: str = field(default_factory=lambda: _env("OPENALEX_API_KEY"))  # 무료 키(선택). 일일 예산 소진 시 자동으로 익명 전환
    dart_api_key: str = field(default_factory=lambda: _env("DART_API_KEY"))  # OpenDART 무료 키(선택) — 국내 법인 영문 상호·홈페이지
    s2_api_key: str = field(default_factory=lambda: _env("S2_API_KEY"))  # Semantic Scholar(선택)
    core_api_key: str = field(default_factory=lambda: _env("CORE_API_KEY"))  # CORE(선택)
    timeout: float = field(default_factory=lambda: float(_env("TIMEOUT", "30")))
    cache_dir: Path = field(default_factory=lambda: Path(_env("CACHE_DIR", "cache")))
    pdf_budget: int = field(default_factory=lambda: int(_env("PDF_BUDGET", "8")))  # 사람당 읽어 볼 OA PDF 수(차단된 시도는 절반 비용)
    author_candidates: int = field(default_factory=lambda: int(_env("AUTHOR_CANDIDATES", "2")))  # 저자 레코드가 여럿일 때 훑을 상위 후보 수

    @property
    def user_agent(self) -> str:
        mail = self.contact_email if "@" in self.contact_email else "unknown@example.org"
        return f"email-search/0.1 (mailto:{mail})"
