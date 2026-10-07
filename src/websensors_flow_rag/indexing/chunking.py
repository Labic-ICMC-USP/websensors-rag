from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from websensors_flow_rag.config import ChunkingSettings
from websensors_flow_rag.utils import normalize_text


_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass
class MarkdownBlock:
    text: str
    heading_path: list[str]
    overlap: bool = False


def estimate_tokens(text: str) -> int:
    words = re.findall(r"\S+", text)
    return max(1, int(math.ceil(len(words) * 1.3))) if text.strip() else 0


def _split_large_block(text: str, max_tokens: int) -> list[str]:
    if estimate_tokens(text) <= max_tokens:
        return [text]
    words = text.split()
    max_words = max(1, int(max_tokens / 1.3))
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def parse_markdown_blocks(markdown: str) -> tuple[str | None, list[MarkdownBlock]]:
    headings: dict[int, str] = {}
    title: str | None = None
    blocks: list[MarkdownBlock] = []
    buffer: list[str] = []

    def current_path() -> list[str]:
        return [headings[level] for level in sorted(headings)]

    def flush() -> None:
        nonlocal buffer
        text = "\n".join(buffer).strip()
        if text:
            blocks.append(MarkdownBlock(text=text, heading_path=current_path()))
        buffer = []

    for line in markdown.splitlines():
        match = _HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            value = match.group(2).strip()
            if title is None and level == 1:
                title = value
            for existing in list(headings):
                if existing >= level:
                    del headings[existing]
            headings[level] = value
            continue
        if not line.strip():
            flush()
        else:
            buffer.append(line)
    flush()
    return title, blocks


def _tail_overlap(group: list[MarkdownBlock], overlap_tokens: int) -> MarkdownBlock | None:
    if overlap_tokens <= 0 or not group:
        return None
    text = "\n\n".join(item.text for item in group).strip()
    words = text.split()
    max_words = max(1, int(overlap_tokens / 1.3))
    tail = " ".join(words[-max_words:]).strip()
    if not tail:
        return None
    return MarkdownBlock(text=tail, heading_path=list(group[-1].heading_path), overlap=True)


def _group_text(group: list[MarkdownBlock]) -> str:
    return "\n\n".join(item.text for item in group).strip()


def _group_tokens(group: list[MarkdownBlock]) -> int:
    return estimate_tokens(_group_text(group))


def _build_section_groups(blocks: list[MarkdownBlock], settings: ChunkingSettings) -> list[list[MarkdownBlock]]:
    groups: list[list[MarkdownBlock]] = []
    index = 0
    pending_overlap_source: list[MarkdownBlock] | None = None

    while index < len(blocks):
        next_block = blocks[index]
        current: list[MarkdownBlock] = []

        if pending_overlap_source:
            available = max(0, settings.max_tokens - estimate_tokens(next_block.text))
            overlap_budget = min(settings.overlap_tokens, available)
            overlap = _tail_overlap(pending_overlap_source, overlap_budget)
            if overlap is not None:
                current.append(overlap)

        while index < len(blocks):
            block = blocks[index]
            candidate = current + [block]
            if current and _group_tokens(candidate) > settings.max_tokens:
                break
            current.append(block)
            index += 1
            if _group_tokens(current) >= settings.target_tokens:
                break

        if not current:
            current = [next_block]
            index += 1

        groups.append(current)
        pending_overlap_source = current

    if len(groups) >= 2 and _group_tokens(groups[-1]) < settings.min_chunk_tokens:
        previous = groups[-2]
        last_without_overlap = [item for item in groups[-1] if not item.overlap]
        candidate = previous + last_without_overlap
        if last_without_overlap and _group_tokens(candidate) <= settings.max_tokens:
            groups[-2] = candidate
            groups.pop()

    return groups


def structural_chunks(markdown: str, settings: ChunkingSettings) -> tuple[str | None, list[dict[str, Any]]]:
    title, parsed = parse_markdown_blocks(markdown)
    expanded: list[MarkdownBlock] = []
    for block in parsed:
        for part in _split_large_block(block.text, settings.max_tokens):
            expanded.append(MarkdownBlock(text=part, heading_path=list(block.heading_path)))

    grouped_by_section: list[list[MarkdownBlock]] = []
    current_section: list[MarkdownBlock] = []
    current_path: list[str] | None = None
    for block in expanded:
        if current_section and block.heading_path != current_path:
            grouped_by_section.append(current_section)
            current_section = []
        current_path = list(block.heading_path)
        current_section.append(block)
    if current_section:
        grouped_by_section.append(current_section)

    groups: list[list[MarkdownBlock]] = []
    for section_blocks in grouped_by_section:
        groups.extend(_build_section_groups(section_blocks, settings))

    chunks: list[dict[str, Any]] = []
    for sequence, group in enumerate(groups, start=1):
        content = _group_text(group)
        path = list(group[-1].heading_path) if group else []
        section = path[-1] if path else None
        heading_text = " > ".join(path)
        prefix_parts: list[str] = []
        if title:
            prefix_parts.append(f"Título: {title}")
        if heading_text:
            prefix_parts.append(f"Seção: {heading_text}")
        embedding_text = "\n".join(prefix_parts + [content])
        estimated = estimate_tokens(content)
        if estimated > settings.max_tokens:
            raise RuntimeError(
                f"Chunk {sequence} excedeu max_tokens: {estimated} > {settings.max_tokens}."
            )
        chunks.append(
            {
                "sequence": sequence,
                "type": "text",
                "title": title,
                "section": section,
                "heading_path": path,
                "heading_text": heading_text,
                "content": content,
                "embedding_text": embedding_text,
                "estimated_tokens": estimated,
            }
        )
    return title, chunks


def collect_provenance_items(docling_json: dict[str, Any]) -> list[tuple[str, set[int]]]:
    items: list[tuple[str, set[int]]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            text = value.get("text")
            prov = value.get("prov")
            if isinstance(text, str) and text.strip() and isinstance(prov, list):
                pages: set[int] = set()
                for item in prov:
                    if isinstance(item, dict) and item.get("page_no") is not None:
                        try:
                            pages.add(int(item["page_no"]))
                        except (TypeError, ValueError):
                            pass
                normalized = normalize_text(text)
                if pages and len(normalized) >= 8:
                    items.append((normalized, pages))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(docling_json)
    return items


def attach_pages(chunks: list[dict[str, Any]], docling_json: dict[str, Any]) -> None:
    provenance = collect_provenance_items(docling_json)
    for chunk in chunks:
        normalized_chunk = normalize_text(chunk["content"])
        pages: set[int] = set()
        for normalized_item, item_pages in provenance:
            if normalized_item in normalized_chunk or (
                len(normalized_chunk) >= 24 and normalized_chunk in normalized_item
            ):
                pages.update(item_pages)
        chunk["page_start"] = min(pages) if pages else None
        chunk["page_end"] = max(pages) if pages else None
