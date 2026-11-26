"""Deliver oversized observations without losing their original result bytes."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.tools.path_utils import FileRoots, safe_run_dir
from src.tools.redaction import redact_tool_result

logger = logging.getLogger(__name__)


def persist_calculation_result(result: str, run_dir: str | Path | None, *, roots: FileRoots, export_csv: bool = False) -> str:
    """Keep a JSON observation addressable by calculation tools and file readers.

    Args:
        result: Full JSON object as text, before any presentation truncation.
        run_dir: Authorized workspace. None retains the original response.
        roots: File roots used to validate the supplied run directory.
        export_csv: Also save normalized market bars from the result as a CSV.

    Returns:
        Result with a file reference, or a bounded receipt for a large result.
        Persistence errors remain visible without discarding the calculation.

    Raises:
        json.JSONDecodeError: A run directory was provided but the result is invalid JSON.
    """
    if not run_dir:
        return result

    result = redact_tool_result(result)
    payload = json.loads(result)
    try:
        root = safe_run_dir(str(run_dir), roots=roots)
        ref = _persist_result_files(result, root, is_json=True)
        folder = Path(ref["path"]).parent
    except (OSError, ValueError) as exc:
        payload['_artifact_error'] = str(exc)
        return json.dumps(payload, ensure_ascii=False)
    payload['_result_file'] = ref
    if export_csv:
        from src.data_gateway.bar_artifact import export_bars_csv

        try:
            payload['_csv_file'] = export_bars_csv(payload, folder, root)
        except (OSError, ValueError) as exc:
            payload['_csv_error'] = str(exc)
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= TOOL_RESULT_LIMIT:
        return encoded
    receipt = {'_result_file': ref, '_delivery': (
        'Full JSON saved. Pass a __data_ref__ argument to quantlib_call with path, '
        'pointer (e.g. /NVDA.US), column=close, index=trade_date, transform=pct_change. '
        'Inspect the saved JSON before requesting more data. Only if rows are explicitly sampled/truncated and consecutive bars are needed, fetch max_rows=0 for the bounded window. Read parts/1.txt onward for prose inspection.'
    )}
    metadata = ('ok', 'status', 'module', 'function', 'input_sources', '_provenance',
                '_csv_file', '_csv_error', '_data_layout', '_request_window')
    receipt.update((key, payload[key]) for key in metadata if key in payload)
    if len(json.dumps(receipt, ensure_ascii=False)) > TOOL_RESULT_LIMIT // 2 and '_provenance' in receipt:
        receipt.pop('_provenance')
        receipt['_metadata_location'] = 'Source metadata is in the complete result file.'
    if isinstance(payload.get('_summary'), dict):
        candidate = {**receipt, '_summary': payload['_summary'], '_delivery': (
            'Full bars saved at _result_file. _summary contains observed counts, endpoints, '
            'sequence checks, statistics and provenance; it does not assert calendar completeness. '
            'Use that summary directly for a snapshot. Read the artifact for calculations needing '
            'other fields or individual bars; no refetch is needed.'
        )}
        # MCP uses _preview to distinguish receipts from inline results.
        candidate['_preview'] = json.dumps(payload['_summary'], ensure_ascii=False)[:200]
        metadata = ('_unresolved', '_diagnostics', '_recovery', 'complete')
        candidate.update((key, payload[key]) for key in metadata if key in payload)
        encoded = json.dumps(candidate, ensure_ascii=False)
        if len(encoded) <= TOOL_RESULT_LIMIT:
            return encoded
        receipt['_summary_omitted'] = 'Summary exceeds the tool envelope; read the saved artifact.'
    receipt['_preview'] = _json_outline(payload, TOOL_RESULT_LIMIT // 4)
    if len(json.dumps(receipt, ensure_ascii=False)) > TOOL_RESULT_LIMIT:
        receipt.pop('input_sources', None)
    return json.dumps(receipt, ensure_ascii=False)


def _outline(value, depth: int, width: int):
    if isinstance(value, dict):
        if depth <= 0 or not value:
            return {'type': 'object', 'keys': list(value)[:width]}
        return {'type': 'object', 'fields': {
            key: _outline(item, depth - 1, width) for key, item in list(value.items())[:width]}}
    if isinstance(value, list):
        outline = {'type': 'array', 'length': len(value)}
        if value and depth > 0:
            outline['items'] = _outline(value[0], depth - 1, width)
        return outline
    if isinstance(value, bool):
        return {'type': 'boolean'}
    if isinstance(value, (int, float)):
        return {'type': 'number'}
    return {'type': 'null' if value is None else 'string'}


def _json_outline(value, limit: int) -> dict:
    """Describe a JSON value's shape without any of its values.

    A head+tail text excerpt of a large result splices unrelated records
    (one symbol's first prices beside another's last) into what reads as one
    series. An outline names keys, array lengths and value types only.

    Args:
        value: Parsed JSON value.
        limit: Maximum encoded size of the outline in characters.

    Returns:
        The most detailed outline that fits ``limit``; an object or array is
        described at least by its type and key list or length.
    """
    for depth, width in ((3, 40), (2, 40), (2, 10), (1, 10), (0, 10)):
        outline = _outline(value, depth, width)
        if len(json.dumps(outline, ensure_ascii=False)) <= limit:
            break
    if isinstance(value, dict) and len(value) > width:
        outline['omitted_keys'] = len(value) - width
    return outline


def _write_original(path: Path, content: str, root: Path) -> None:
    """Save immutable content inside the workspace, or refuse a changed path."""
    if not path.resolve().is_relative_to(root):
        raise ValueError('Result artifact escapes workspace')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(content)
    except FileExistsError:
        if path.read_text(encoding='utf-8') != content:
            raise ValueError('Existing result artifact was modified')


def save_result_parts(content: str, folder: Path, root: Path) -> list[str]:
    """Save immutable parts that fit through the actual read_file JSON envelope.

    Args:
        content: Complete, already redacted result text.
        folder: Directory for sequentially numbered parts.
        root: Workspace boundary that every file must stay within.

    Returns:
        Paths to the parts in their original order.

    Raises:
        ValueError: The path leaves no room for content in the read envelope,
            a part escapes the workspace, or an existing part's content differs.
        OSError: A part or its directory could not be read or written.
    """
    offset, part_count = 0, 0
    while offset < len(content):
        part = folder / f'{part_count + 1}.txt'
        low, high = 0, min(len(content) - offset, TOOL_RESULT_LIMIT)
        while low < high:
            size = (low + high + 1) // 2
            envelope = json.dumps({'status': 'ok', 'path': str(part),
                                   'content': content[offset:offset + size]}, ensure_ascii=False)
            if len(envelope) <= TOOL_RESULT_LIMIT:
                low = size
            else:
                high = size - 1
        if not low:
            raise ValueError('Artifact path leaves no room for readable content')
        _write_original(part, content[offset:offset + low], root)
        part_count += 1
        offset += low
    return [str(folder / f"{index + 1}.txt") for index in range(part_count)]


def _persist_result_files(
    result: str, root: Path, *, is_json: bool, include_characters: bool = False,
) -> dict:
    digest = hashlib.sha256(result.encode()).hexdigest()
    folder = root / 'tool-results' / digest
    path = folder / ('result.json' if is_json else 'result.txt')
    parts_dir = folder / 'parts'
    _write_original(path, result, root)
    parts = save_result_parts(result, parts_dir, root)
    return {
        'path': str(path), 'sha256': digest, 'format': 'json' if is_json else 'text',
        'relative_path': str(path.relative_to(root)),
        'parts_relative_dir': str(parts_dir.relative_to(root)),
        **({'characters': len(result)} if include_characters else {}),
        'parts_dir': str(parts_dir), 'part_count': len(parts),
    }


_FILE_READ_FIELDS = ('path', 'truncated', 'returned_chars', 'total_chars', 'returned_lines', 'total_lines')


def _file_read_receipt(payload, has_shell: bool) -> dict | None:
    """Say what a saved read_file response holds instead of claiming a complete result."""
    from src.tools.read_file_tool import _OUTPUT_LIMIT

    if not (isinstance(payload, dict) and payload.get('status') == 'ok'
            and isinstance(payload.get('path'), str) and isinstance(payload.get('content'), str)):
        return None
    receipt = {key: payload[key] for key in _FILE_READ_FIELDS if key in payload}
    pages = ('_result_file holds this read_file response, not the source file; its pages are '
             'parts_relative_dir + /1.txt through part_count, fragments of the response JSON in order.')
    if not payload.get('truncated'):
        receipt['_delivery'] = f'Its content is the complete text of the source file at path. {pages}'
        return receipt
    shown, total = payload.get('returned_chars'), payload.get('total_chars')
    held = f'the first {shown} of {total} characters' if isinstance(shown, int) else f'part of the {total} characters'
    rest = (f'Use bash on path to read the source from character {shown} onward.' if has_shell and isinstance(shown, int)
            else 'Use bash on path to read the rest of the source.' if has_shell
            else f'read_file always reads from the first line: a larger limit returns more lines, up to '
                 f'{_OUTPUT_LIMIT:,} characters, and it has no offset, so text past that is not reachable through read_file.')
    receipt['_delivery'] = (
        f'Its content is a partial preview: only {held} of the source file at path, which is unchanged. '
        f'{pages} Saving the response did not save the rest of the source. {rest}'
    )
    return receipt


def deliver_tool_result(result: str, run_dir: str | Path | None, registry, *, tool_name: str | None = None) -> str:
    """Keep a large result in full, with a bounded valid JSON receipt.

    Args:
        result: Complete tool result. Credentials are scrubbed before saving.
        run_dir: Current task workspace, if available.
        registry: Actual registry, used to check for a local file reader.
        tool_name: Executed tool. A read_file receipt describes the saved response's
            partial or complete source content and keeps the source path.

    Returns:
        The original bounded result or a receipt naming its full file and readable
        parts. If saving or local reading is unavailable, returns the bounded
        presentation without claiming a file was saved.
    """
    result = redact_tool_result(result)
    if len(result) <= TOOL_RESULT_LIMIT or not run_dir:
        return truncate_tool_result(result)
    from src.tools.bash_tool import BashTool
    from src.tools.read_file_tool import ReadFileTool

    try:
        shell = registry.get('bash')
        reader = registry.get('read_file')
        readable = has_shell = isinstance(getattr(shell, "_tool", shell), BashTool)
        if not readable and isinstance(getattr(reader, "_tool", reader), ReadFileTool):
            safe_run_dir(str(run_dir), roots=registry.policy.file_roots)
            readable = True
    except (AttributeError, KeyError, ValueError):
        readable = has_shell = False
    if not readable:
        return truncate_tool_result(result)
    try:
        payload = json.loads(result)
        is_json = True
    except (ValueError, TypeError):
        payload = None
        is_json = False
    try:
        workspace = getattr(registry, "session_workspace", None)
        root = Path(workspace).expanduser().resolve() if workspace else Path(run_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        ref = _persist_result_files(result, root, is_json=is_json, include_characters=True)
    except (OSError, UnicodeError, ValueError):
        logger.warning('Could not preserve complete tool result', exc_info=True)
        return truncate_tool_result(result)

    receipt = {
        '_result_file': ref,
        '_delivery': (
            'The complete tool result is saved in this task workspace. Load the JSON '
            'file with a quantlib_call __data_ref__ argument. For read_file, use the exact '
            'parts_relative_dir + /1.txt path relative to your current task workspace, '
            'through part_count in order. Do not refetch data because this preview '
            'is shortened. Source row limits/sampling still apply: inspect the '
            'original result coverage before calculating; saving does not fill missing rows.'
        ),
    }
    file_read = _file_read_receipt(payload, has_shell) if tool_name == 'read_file' else None
    if file_read:
        receipt.update(file_read)
    if isinstance(payload, dict):
        metadata = ('status', 'ok', '_provenance', '_unresolved', '_diagnostics')
        receipt.update((key, payload[key]) for key in metadata if key in payload)
        # Keep compact calculation bases visible beside the artifact reference.
        for key in ('calculation_basis', 'comparisons', 'expiry_scenarios', 'summary', 'inputs'):
            if key in payload:
                candidate = {**receipt, key: payload[key]}
                if len(json.dumps(candidate, ensure_ascii=False)) <= TOOL_RESULT_LIMIT // 2:
                    receipt[key] = payload[key]
    # Store oversized source metadata in the complete artifact.
    if len(json.dumps(receipt, ensure_ascii=False)) > TOOL_RESULT_LIMIT // 2:
        for key in ('_diagnostics', '_provenance', '_unresolved'):
            receipt.pop(key, None)
        receipt['_metadata_location'] = 'Source metadata is in the complete result file.'
    room = max(0, TOOL_RESULT_LIMIT // 4 - len(json.dumps(receipt, ensure_ascii=False)))
    if is_json:
        receipt['_preview'] = _json_outline(payload, room)
        encoded = json.dumps(receipt, ensure_ascii=False)
        if len(encoded) <= TOOL_RESULT_LIMIT:
            return encoded
        room = 0
    # A text preview inside JSON cannot break the surrounding JSON envelope.
    while room:
        receipt['_preview'] = result[:room // 2] + '\n... preview ...\n' + result[-room // 2:]
        encoded = json.dumps(receipt, ensure_ascii=False)
        if len(encoded) <= TOOL_RESULT_LIMIT:
            return encoded
        room //= 2
    receipt.pop('_preview', None)
    encoded = json.dumps(receipt, ensure_ascii=False)
    return encoded if len(encoded) <= TOOL_RESULT_LIMIT else truncate_tool_result(result)
