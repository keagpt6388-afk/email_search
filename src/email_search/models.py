"""입력·출력 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from dataclasses import field as dc_field
from typing import Any


@dataclass
class Person:
    """입력: 이름(한글·로마자 어느 쪽이든), 소속, 기술분야(선택)."""

    name: str
    affiliation: str
    field: str = ""
    name_variants: list[str] = dc_field(default_factory=list)  # 공보 영문 표기 등 추가로 아는 표기

    @property
    def names(self) -> list[str]:
        return [n for n in [self.name, *self.name_variants] if n]


@dataclass
class EmailHit:
    """찾은 이메일 하나와 그 근거."""

    email: str
    source: str  # orcid | europepmc | europepmc_xml | biorxiv | oa_pdf | oa_html | homepage
    source_url: str  # 이메일이 실린 문서·페이지
    document_id: str  # DOI·PMCID·ORCID 등
    verified: bool  # 게이트: 소속 공식 도메인과 일치(또는 ORCID 본인 레코드)
    verification: str  # 검증 설명
    attribution: str  # 이 사람의 이메일이라고 본 근거
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SearchResult:
    person: Person
    emails: list[EmailHit] = dc_field(default_factory=list)
    identifiers: dict[str, str] = dc_field(default_factory=dict)  # orcid, openalex, ror …
    affiliation_names: list[str] = dc_field(default_factory=list)  # 소속 표기 확장 결과
    official_domains: dict[str, list[str]] = dc_field(default_factory=dict)  # 도메인 → 출처들
    homepages: list[tuple[str, str]] = dc_field(default_factory=list)  # (URL, 출처)
    log: list[str] = dc_field(default_factory=list)  # 단계별 기록(화면·시트 '탐색 로그')
    elapsed_s: float = 0.0

    @property
    def best(self) -> EmailHit | None:
        verified = [h for h in self.emails if h.verified]
        return (verified or self.emails or [None])[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "person": asdict(self.person),
            "emails": [h.to_dict() for h in self.emails],
            "identifiers": self.identifiers,
            "affiliation_names": self.affiliation_names,
            "official_domains": self.official_domains,
            "homepages": [list(x) for x in self.homepages],
            "log": self.log,
            "elapsed_s": round(self.elapsed_s, 1),
        }
