"""Versioned knowledge: document sections, SUPERSEDES edges and retrieval.

Every retrievable chunk is one *version of one section* of a document, for
example ``edd-policy@v3#2.1``. When a new version replaces an old one, a
SUPERSEDES edge links them (new -> old). That edge is what lets Supersede
answer "was this evidence still valid when the agent used it?" and "what is
the current version to replay with?".
"""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .util import parse_day, tokens


@dataclass
class Chunk:
    id: str                    # "edd-policy@v3#2.1"
    doc_id: str                # "edd-policy"
    title: str                 # "EDD Policy"
    section: str               # "2.1"
    version: int
    text: str
    effective_on: str          # YYYY-MM-DD
    retired_on: str | None = None
    owner: str = ""
    kind: str = "document"     # document | definition | data
    meta: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.title} v{self.version} §{self.section}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d


class KnowledgeBase:
    """In-memory versioned chunk store with BM25 retrieval."""

    def __init__(self, chunks: list[Chunk], supersedes: list[tuple[str, str]] | None = None) -> None:
        self.chunks: dict[str, Chunk] = {c.id: c for c in chunks}
        # new_id -> old_id and the reverse index old_id -> new_id
        self.replaces: dict[str, str] = {}
        self.replaced_by: dict[str, str] = {}
        for new, old in supersedes or []:
            self.add_supersedes(new, old)
        self._index()

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_json(cls, path: str | Path) -> "KnowledgeBase":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        chunks = [Chunk(**c) for c in data["chunks"]]
        edges = [(e["new"], e["old"]) for e in data.get("supersedes", [])]
        return cls(chunks, edges)

    def add_supersedes(self, new_id: str, old_id: str) -> None:
        if new_id not in self.chunks or old_id not in self.chunks:
            raise KeyError(f"unknown chunk in SUPERSEDES edge {new_id} -> {old_id}")
        self.replaces[new_id] = old_id
        self.replaced_by[old_id] = new_id

    # -- version questions -------------------------------------------------
    def get(self, chunk_id: str) -> Chunk:
        return self.chunks[chunk_id]

    def status_on(self, chunk_id: str, day: date | str) -> str:
        """``current`` | ``retired`` | ``not_yet_effective`` on the given day."""
        c = self.chunks[chunk_id]
        d = parse_day(day) if isinstance(day, str) else day
        if parse_day(c.effective_on) > d:
            return "not_yet_effective"
        retired = parse_day(c.retired_on)
        if retired and retired <= d:
            return "retired"
        return "current"

    def days_out_of_date(self, chunk_id: str, day: date | str) -> int:
        c = self.chunks[chunk_id]
        d = parse_day(day) if isinstance(day, str) else day
        retired = parse_day(c.retired_on)
        return max(0, (d - retired).days) if retired else 0

    def current_version(self, chunk_id: str, day: date | str) -> str:
        """Follow SUPERSEDES edges forward to the version in force on ``day``."""
        seen = set()
        cur = chunk_id
        while self.status_on(cur, day) == "retired" and cur in self.replaced_by and cur not in seen:
            seen.add(cur)
            cur = self.replaced_by[cur]
        return cur

    # -- retrieval ---------------------------------------------------------
    def _index(self) -> None:
        self._tf: dict[str, Counter] = {cid: Counter(tokens(c.title + " " + c.text)) for cid, c in self.chunks.items()}
        self._len = {cid: sum(tf.values()) for cid, tf in self._tf.items()}
        self._avg = (sum(self._len.values()) / len(self._len)) if self._len else 1.0
        df: Counter = Counter()
        for tf in self._tf.values():
            df.update(set(tf))
        n = len(self._tf)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, top_k: int = 3, doc_ids: list[str] | None = None) -> list[tuple[str, float]]:
        """Plain BM25. Note: it does NOT look at versions; that is the bug we expose."""
        q = tokens(query)
        k1, b = 1.4, 0.75
        scored = []
        for cid, tf in self._tf.items():
            if doc_ids and self.chunks[cid].doc_id not in doc_ids:
                continue
            s = 0.0
            for t in q:
                if t not in tf:
                    continue
                f = tf[t]
                s += self._idf.get(t, 0.0) * f * (k1 + 1) / (f + k1 * (1 - b + b * self._len[cid] / self._avg))
            if s > 0:
                scored.append((cid, round(s, 4)))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_k]

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 3,
        doc_ids: list[str] | None = None,
        swaps: dict[str, str] | None = None,
        guard_day: str | None = None,
    ) -> dict:
        """Search, then apply evidence edits.

        ``swaps``     replay/fork edits: replace chunk A with chunk B.
        ``guard_day`` guard mode: replace any chunk retired on that day with
                      its current version, and record that it was blocked.
        """
        hits = self.search(query, top_k=top_k, doc_ids=doc_ids)
        out, swapped, blocked = [], [], []
        for cid, score in hits:
            final = cid
            if swaps and cid in swaps:
                final = swaps[cid]
                swapped.append({"from": cid, "to": final})
            elif guard_day and self.status_on(cid, guard_day) == "retired":
                final = self.current_version(cid, guard_day)
                blocked.append({"from": cid, "to": final})
            if final not in [o["id"] for o in out]:
                out.append({"id": final, "score": score})
        return {"chunks": out, "swapped": swapped, "blocked": blocked}
