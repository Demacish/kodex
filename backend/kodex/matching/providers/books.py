"""E-book providers. ISBN first, then title and author:

- Open Library: ``/isbn/{isbn}.json`` (an edition, with its work) and
  ``/search.json`` (``fields`` must be given). One call a second, three
  with an identifying User-Agent.
- Google Books: ``volumes?q=isbn:…`` or ``intitle:…+inauthor:…``; 1 000
  calls a day with a key.
- Hardcover (GraphQL, token): editions by ISBN; 60 calls a minute and
  5 000 a day.
"""

from __future__ import annotations

from typing import Any

from kodex.formats.opf import isbn13
from kodex.matching.providers.base import BookRef, NotConfigured, NotFound, ProviderClient, RatePolicy


def _year(value: Any) -> int | None:
    text = str(value or "")
    for i in range(len(text) - 3):
        chunk = text[i : i + 4]
        if chunk.isdigit() and 1400 <= int(chunk) <= 2100:
            return int(chunk)
    return None


class OpenLibrary(ProviderClient):
    name = "open_library"
    base_url = "https://openlibrary.org/"
    default_policy = RatePolicy(min_interval=0.4)
    _FIELDS = "key,title,author_name,first_publish_year,isbn,publisher,number_of_pages_median,edition_key,language"

    def lookup_isbn(self, isbn: str) -> BookRef:
        edition = self.get(f"isbn/{isbn}.json", {}, lookup=True)
        work_key = ((edition.get("works") or [{}])[0]).get("key")
        isbns = [
            normalised
            for raw in (edition.get("isbn_13") or []) + (edition.get("isbn_10") or [])
            if (normalised := isbn13(raw))
        ]
        return BookRef(
            provider="open_library",
            id=str(edition.get("key", "")).removeprefix("/books/"),
            title=str(edition.get("title") or ""),
            year=_year(edition.get("publish_date")),
            publisher=(edition.get("publishers") or [None])[0],
            isbn13=sorted(set(isbns)),
            page_count=edition.get("number_of_pages"),
            work_id=str(work_key).removeprefix("/works/") if work_key else None,
        )

    def search_books(self, title: str, author: str | None = None) -> list[BookRef]:
        params = {"title": title, "fields": self._FIELDS, "limit": "10"}
        if author:
            params["author"] = author
        payload = self.get("search.json", params)
        books = []
        for doc in payload.get("docs") or []:
            books.append(
                BookRef(
                    provider="open_library",
                    id=str(doc.get("key", "")).removeprefix("/works/"),
                    title=str(doc.get("title") or ""),
                    authors=list(doc.get("author_name") or []),
                    year=doc.get("first_publish_year"),
                    publisher=(doc.get("publisher") or [None])[0],
                    isbn13=sorted({n for raw in doc.get("isbn") or [] if (n := isbn13(raw))})[:20],
                    page_count=doc.get("number_of_pages_median"),
                    work_id=str(doc.get("key", "")).removeprefix("/works/"),
                )
            )
        return books


class GoogleBooks(ProviderClient):
    name = "google_books"
    base_url = "https://www.googleapis.com/books/v1/"
    secret_params = frozenset({"key"})
    default_policy = RatePolicy(min_interval=0.5, window=86400.0, window_limit=1000)

    def __init__(self, *, api_key: str = "", **kwargs: Any) -> None:
        self.api_key = api_key
        super().__init__(**kwargs)

    def auth_params(self) -> dict[str, str]:
        return {"key": self.api_key} if self.api_key else {}

    def _volumes(self, query: str) -> list[BookRef]:
        payload = self.get("volumes", {"q": query, "maxResults": "10", "printType": "books"})
        return [_google_book(item) for item in payload.get("items") or []]

    def lookup_isbn(self, isbn: str) -> BookRef:
        books = self._volumes(f"isbn:{isbn}")
        if not books:
            raise NotFound(f"google_books: no volume for ISBN {isbn}")
        return books[0]

    def search_books(self, title: str, author: str | None = None) -> list[BookRef]:
        query = f'intitle:"{title}"' + (f' inauthor:"{author}"' if author else "")
        return self._volumes(query)


def _google_book(item: dict[str, Any]) -> BookRef:
    info = item.get("volumeInfo") or {}
    isbns = [n for ident in info.get("industryIdentifiers") or [] if (n := isbn13(str(ident.get("identifier", ""))))]
    return BookRef(
        provider="google_books",
        id=str(item.get("id", "")),
        title=" ".join(p for p in (info.get("title"), info.get("subtitle")) if p)
        if info.get("subtitle")
        else str(info.get("title") or ""),
        authors=list(info.get("authors") or []),
        year=_year(info.get("publishedDate")),
        publisher=info.get("publisher"),
        isbn13=sorted(set(isbns)),
        page_count=info.get("pageCount"),
        cover_url=(info.get("imageLinks") or {}).get("thumbnail"),
        language=info.get("language"),
        summary=info.get("description"),
    )


_HARDCOVER_ISBN_QUERY = """
query ($isbn: String!) {
  editions(where: {_or: [{isbn_13: {_eq: $isbn}}, {isbn_10: {_eq: $isbn}}]}, limit: 1) {
    id title isbn_13 pages release_date
    publisher { name }
    book { id title release_year contributions { author { name } } book_series { position series { name } } }
  }
}
"""


class Hardcover(ProviderClient):
    name = "hardcover"
    base_url = "https://api.hardcover.app/v1/graphql"
    default_policy = RatePolicy(min_interval=1.0, window=86400.0, window_limit=5000)

    def __init__(self, *, token: str, **kwargs: Any) -> None:
        if not token:
            raise NotConfigured("hardcover: HARDCOVER_API_TOKEN is not set")
        self.token = token.removeprefix("Bearer ").strip()
        super().__init__(**kwargs)

    def extra_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def lookup_isbn(self, isbn: str) -> BookRef:
        payload = self.post("", {"query": _HARDCOVER_ISBN_QUERY, "variables": {"isbn": isbn}}, lookup=True)
        editions = (payload.get("data") or {}).get("editions") or []
        if not editions:
            raise NotFound(f"hardcover: no edition for ISBN {isbn}")
        edition = editions[0]
        book = edition.get("book") or {}
        series = (book.get("book_series") or [{}])[0]
        return BookRef(
            provider="hardcover",
            id=str(edition.get("id")),
            title=str(edition.get("title") or book.get("title") or ""),
            authors=[
                c["author"]["name"] for c in book.get("contributions") or [] if (c.get("author") or {}).get("name")
            ],
            year=book.get("release_year") or _year(edition.get("release_date")),
            publisher=(edition.get("publisher") or {}).get("name"),
            isbn13=[edition["isbn_13"]] if edition.get("isbn_13") else [],
            page_count=edition.get("pages"),
            series=((series.get("series") or {}).get("name")),
            series_index=str(series["position"]) if series.get("position") is not None else None,
            work_id=str(book.get("id")) if book.get("id") else None,
        )
