"""email_search — 소속·이름·기술분야로 공개 출처에서 이메일을 찾는다."""

from .finder import EmailFinder
from .models import EmailHit, Person, SearchResult

__all__ = ["EmailFinder", "EmailHit", "Person", "SearchResult"]
__version__ = "0.1.0"
