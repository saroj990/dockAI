"""Fuzzy and phonetic container name matching for NL targets."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import docker

from dockai.tools.containers import _primary_name

_MIN_NORM_LEN = 4
_DEFAULT_MIN_SCORE = 0.84
_FOCUS_MIN_SCORE = 0.72
_MAX_EDIT_DISTANCE = 2


def normalize_container_token(value: str) -> str:
    """Collapse case and separators (pg tileserv == pg_tileserv)."""
    return "".join(ch for ch in (value or "").lower() if ch.isalnum())


def phonetic_skeleton(value: str) -> str:
    """
    Consonant-heavy skeleton for near-miss names (tilserv ~ tileserv).
    """
    n = normalize_container_token(value)
    parts: list[str] = []
    last = ""
    for ch in n:
        if ch in "aeiouy":
            continue
        if ch == last:
            continue
        parts.append(ch)
        last = ch
    return "".join(parts)


def _edit_distance(a: str, b: str, *, max_dist: int) -> int | None:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_dist:
        return None
    if len(a) > len(b):
        a, b = b, a
    prev = list(range(len(a) + 1))
    for ch_b in b:
        curr = [prev[0] + 1]
        row_min = curr[0]
        for j, ch_a in enumerate(a, start=1):
            val = min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + (0 if ch_a == ch_b else 1),
            )
            curr.append(val)
            row_min = min(row_min, val)
        if row_min > max_dist:
            return None
        prev = curr
    dist = prev[-1]
    return dist if dist <= max_dist else None


def similarity_score(query: str, candidate: str) -> float:
    qn = normalize_container_token(query)
    cn = normalize_container_token(candidate)
    if not qn or not cn:
        return 0.0
    if qn == cn:
        return 1.0
    if len(qn) >= _MIN_NORM_LEN and (qn in cn or cn in qn):
        return 0.92
    ratio = SequenceMatcher(None, qn, cn).ratio()
    qs, cs = phonetic_skeleton(query), phonetic_skeleton(candidate)
    skel = SequenceMatcher(None, qs, cs).ratio() if qs and cs else 0.0
    dist = _edit_distance(qn, cn, max_dist=_MAX_EDIT_DISTANCE)
    edit_boost = 0.0
    if dist is not None and dist <= _MAX_EDIT_DISTANCE:
        edit_boost = 0.88 - (dist * 0.06)
    return max(ratio, skel * 0.96, edit_boost)


def pick_best_container_name(
    query: str,
    candidates: list[str],
    *,
    focus: str | None = None,
    min_score: float = _DEFAULT_MIN_SCORE,
    focus_min_score: float = _FOCUS_MIN_SCORE,
) -> str | None:
    """
    Return the best candidate name, or None when nothing is close enough.

    When ``focus`` is set, it can win at a lower threshold (session context).
    """
    text = (query or "").strip()
    if not text or not candidates:
        return None
    if _looks_like_container_id(text):
        return text if text in candidates else None

    unique = sorted({c.strip() for c in candidates if c and c.strip()})
    scored: list[tuple[float, str]] = []
    for name in unique:
        score = similarity_score(text, name)
        threshold = focus_min_score if focus and name == focus else min_score
        if score >= threshold:
            scored.append((score, name))

    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    best_score, best_name = scored[0]
    # Ambiguous: two names equally close — do not guess.
    if len(scored) > 1 and scored[1][0] >= best_score - 0.02:
        if scored[1][0] >= min_score:
            return None
    return best_name


def _looks_like_container_id(target: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{8,64}", target.strip().lower()))


def list_container_names(client: docker.DockerClient) -> list[str]:
    try:
        containers = client.containers.list(all=True, sparse=True)
    except Exception:  # noqa: BLE001
        return []
    return [_primary_name(c) for c in containers]


def refine_tool_target(
    client: docker.DockerClient,
    arguments: dict[str, Any],
    *,
    focus_container: str | None,
) -> dict[str, Any]:
    """Rewrite tool ``target`` using Docker names + fuzzy/phonetic match."""
    args = dict(arguments)
    raw = args.get("target")
    if raw is None:
        return args
    text = str(raw).strip()
    if not text:
        return args

    names = list_container_names(client)
    if focus_container and focus_container not in names:
        names.append(focus_container)

    exact = normalize_container_token(text)
    for name in names:
        if normalize_container_token(name) == exact:
            args["target"] = name
            return args

    best = pick_best_container_name(text, names, focus=focus_container)
    if best:
        args["target"] = best
    return args


def refine_target_with_focus(raw_target: str, focus_container: str | None) -> str:
    """Intent-layer correction when only session focus is available."""
    target = (raw_target or "").strip()
    if not target or not focus_container:
        return target
    best = pick_best_container_name(
        target, [focus_container], focus=focus_container
    )
    return best or target
