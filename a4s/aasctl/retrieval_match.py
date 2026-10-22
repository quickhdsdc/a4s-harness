"""Exact embedding retrieval constrained by the AAS hierarchy and value shape.

No lexical score fusion, local inference model or per-property chat calls.
Cosine similarity is retrieval evidence, not a correctness probability.
"""
from __future__ import annotations

import re
from typing import Any

import numpy as np

from . import match
from .index import Index, Node, _split_words

ALGORITHM = "embedding-graph-filtered-v1"
LEAF_THRESHOLD = .48
HOST_THRESHOLD = .45
MIN_MARGIN = .04
_NUMERIC = {"xs:int", "xs:integer", "xs:long", "xs:decimal", "xs:double", "xs:float"}
_SCOPES = (
    ({"cell", "cells"}, {"module", "modules"}, {"pack", "packs"}),
    ({"min", "minimum", "lower"}, {"max", "maximum", "upper"}),
)


def words(text: str) -> set[str]:
    return set(re.findall(r"[^\W_]+", _split_words(text).casefold()))


def scope_conflict(source: set[str], target: set[str]) -> bool:
    # Only an explicit, unambiguous qualifier may exclude an opposite branch.
    # Unspecified scope remains unknown; definitions mentioning several levels
    # are deliberately not used as hard constraints.
    for group in _SCOPES:
        left = {i for i, vocabulary in enumerate(group) if source & vocabulary}
        right = {i for i, vocabulary in enumerate(group) if target & vocabulary}
        if len(left) == len(right) == 1 and left != right:
            return True
    return False


class Retriever:
    def __init__(self, index: Index):
        self.index = index
        self.by_path = {n.path: n for n in index.nodes}
        vectors = np.asarray(index.vectors, dtype="float32")
        if not index.nodes:
            self.vectors = np.empty((0, 0), dtype="float32")
        else:
            self.vectors = vectors / np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
        self.contexts = [self._context(node) for node in index.nodes]

    def _context(self, node: Node) -> set[str]:
        # Include the complete parent chain: repeated leaf names must retain
        # their cell/module/pack or lower/upper branch, including list parents.
        context = words(node.path + " " + (node.id_short or "") + " " + node.preferred_name)
        seen = {node.path}
        parent = node.parent
        while parent and parent not in seen:
            seen.add(parent)
            ancestor = self.by_path.get(parent)
            if ancestor is None:
                context |= words(parent)
                break
            context |= words(ancestor.id_short or "") | words(ancestor.preferred_name)
            parent = ancestor.parent
        return context

    def _compatible(self, entity: match.Entity, node: Node, shape: Any) -> bool:
        if node.model_type == "Blob":
            return entity.model_type == "Blob"
        if node.model_type not in ("Property", "MultiLanguageProperty", "Range", "File", "ReferenceElement"):
            return False
        if entity.unit and node.unit and match.unit_warning(entity.unit, node.unit):
            return False  # Never silently convert kWh to Wh or overwrite incompatible units.
        if node.model_type == "Range":
            return shape.model_type == "Range"
        if node.model_type == "File":
            return shape.model_type == "File"
        if node.value_type == "xs:boolean":
            return str(entity.value).strip().lower() in ("true", "false", "0", "1")
        if node.value_type in _NUMERIC:
            # An interval cannot be populated into a numeric scalar.
            return shape.model_type != "Range" and bool(re.fullmatch(
                r"\s*[+-]?(?:\d+(?:[.,]\d+)?|\.\d+)(?:[eE][+-]?\d+)?\s*",
                str(entity.value or "")))
        return True

    def rank(self, entity: match.Entity, vector: Any, *, containers: bool = False, limit: int = 5) -> list[match.Candidate]:
        if not self.index.nodes:
            return []
        query = np.asarray(vector, dtype="float32")
        query = query / max(float(np.linalg.norm(query)), 1e-12)
        dense = self.vectors @ query
        shape = match.infer_element_type(entity)
        source = words(entity.entity)
        rows = []
        for i, node in enumerate(self.index.nodes):
            if scope_conflict(source, self.contexts[i]):
                continue
            if containers:
                if node.model_type not in match.CONTAINER_TYPES:
                    continue
                if (node.model_type == "SubmodelElementList" and node.type_value_list_element
                        and node.type_value_list_element != shape.model_type):
                    continue
            elif not self._compatible(entity, node, shape):
                continue
            rows.append(i)
        # Scan ALL eligible target fields; no BM25 shortlist or score bonus.
        rows.sort(key=lambda i: (-float(dense[i]), self.index.nodes[i].path))
        return [match.Candidate(path=self.index.nodes[i].path, id_short=self.index.nodes[i].id_short,
            model_type=self.index.nodes[i].model_type, score=float(dense[i]),
            parent=self.index.nodes[i].parent, unit=self.index.nodes[i].unit,
            definition=self.index.nodes[i].definition or self.index.nodes[i].description,
            type_value_list_element=self.index.nodes[i].type_value_list_element) for i in rows[:limit]]

    def decide(self, entity: match.Entity, vector: Any, *, create: bool = True) -> match.Decision:
        leaves = self.rank(entity, vector)
        containers = self.rank(entity, vector, containers=True) if create else []
        candidates = leaves + containers
        best = leaves[0] if leaves else None
        gap = best.score - leaves[1].score if best and len(leaves) > 1 else 1.0
        if best and best.score >= LEAF_THRESHOLD and gap >= MIN_MARGIN:
            decision = match.decide(entity, candidates, theta_high=-1, theta_low=-1)
            decision.reason = "Embedding cosine ranking after AAS graph, unit and type filters; clear first-rank margin; no LLM arbitration"
            return decision
        host = containers[0] if containers else None
        host_gap = host.score - containers[1].score if host and len(containers) > 1 else 1.0
        if (not best or best.score < LEAF_THRESHOLD) and host and host.score >= HOST_THRESHOLD and host_gap >= MIN_MARGIN:
            decision = match.decide(entity, candidates, theta_high=2, theta_low=2,
                host=lambda e, c: (host, "Embedding suggests this AAS collection; review placement"))
            decision.score = host.score
            return decision
        decision = match.decide(entity, candidates, theta_high=2, theta_low=2)
        decision.reason = "Ambiguous or weak embedding evidence; review the candidates or select a target manually"
        decision.band = "below"
        return decision
