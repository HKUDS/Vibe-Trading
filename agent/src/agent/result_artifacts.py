"""Deliver oversized observations without losing their original result bytes."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from src.config.limits import TOOL_RESULT_LIMIT, truncate_tool_result
from src.tools.redaction import redact_tool_result

logger = logging.getLogger(__name__)


def persist_calculation_result(result: str, run_dir: str | Path | None) -> str:
    """Keep a JSON observation addressable by calculation tools and file readers.

    Args:
        result: Full JSON result, before any presentation truncation.
        run_dir: Authorized workspace; omission retains the original response.

    Returns:
        Result with a file reference, or a bounded receipt for a large result.
        Persistence errors remain visible without discarding the calculation.
    """
    if not run_dir:
        return result
    from src.tools.path_utils import safe_run_dir

    result = redact_tool_result(result)
    payload = json.loads(result)
    try:
        root = safe_run_dir(str(run_dir))
        digest = hashlib.sha256(result.encode()).hexdigest()
        folder = root / 'tool-results' / digest
        path = folder / 'result.json'
        _write_original(path, result, root)
        parts = save_result_parts(result, folder / 'parts', root)
        ref = {'path': str(path), 'sha256': digest, 'format': 'json',
               'relative_path': str(path.relative_to(root)),
               'parts_relative_dir': str((folder / 'parts').relative_to(root)),
               'parts_dir': str(folder / 'parts'), 'part_count': len(parts)}
    except (OSError, ValueError) as exc:
        payload['_artifact_error'] = str(exc)
        return json.dumps(payload, ensure_ascii=False)
    payload['_result_file'] = ref
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= TOOL_RESULT_LIMIT:
        return encoded
    receipt = {'_result_file': ref, '_delivery': (
        'Full JSON saved. Pass a __data_ref__ argument to quantlib_call with path, '
        'pointer (e.g. /NVDA.US), column=close, index=trade_date, transform=pct_change. '
        'For consecutive returns fetch max_rows=0. Read parts/1.txt onward for prose inspection.'
    )}
    for key in ('ok', 'status', 'module', 'function', 'input_sources'):
        if key in payload:
            receipt[key] = payload[key]
    receipt['_preview'] = result[:1000] + '\n...\n' + result[-1000:]
    if len(json.dumps(receipt, ensure_ascii=False)) > TOOL_RESULT_LIMIT:
        receipt.pop('input_sources', None)
    return json.dumps(receipt, ensure_ascii=False)


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
        Absolute paths to parts, in their original order.
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


def deliver_tool_result(result: str, run_dir: str | Path | None, registry) -> str:
    """Keep a large result in full, with a bounded valid JSON receipt.

    Args:
        result: Complete tool result; credentials are scrubbed before saving.
        run_dir: Current task workspace, never a cross-task data cache.
        registry: Actual registry, used to check for a local file reader.

    Returns:
        The original bounded result or a receipt naming its full file and
        readable parts. If saving or local reading is unavailable, retains
        the existing explicit truncation behavior without claiming a file.
    """
    result = redact_tool_result(result)
    if len(result) <= TOOL_RESULT_LIMIT or not run_dir:
        return truncate_tool_result(result)
    from src.tools.bash_tool import BashTool
    from src.tools.read_file_tool import ReadFileTool
    from src.tools.path_utils import safe_run_dir

    try:
        readable = isinstance(registry.get('bash'), BashTool)
        if not readable and isinstance(registry.get('read_file'), ReadFileTool):
            safe_run_dir(str(run_dir))
            readable = True
    except (AttributeError, KeyError, ValueError):
        readable = False
    if not readable:
        return truncate_tool_result(result)
    try:
        payload = json.loads(result)
        is_json = True
    except (ValueError, TypeError):
        payload = None
        is_json = False
    try:
        root = Path(run_dir).resolve()
        digest = hashlib.sha256(result.encode()).hexdigest()
        folder = root / 'tool-results' / digest
        path = folder / ('result.json' if is_json else 'result.txt')
        _write_original(path, result, root)
        parts = save_result_parts(result, folder / 'parts', root)
        part_count = len(parts)
    except (OSError, UnicodeError, ValueError):
        logger.warning('Could not preserve complete tool result', exc_info=True)
        return truncate_tool_result(result)

    receipt = {
        '_result_file': {'path': str(path), 'sha256': digest,
                         'format': 'json' if is_json else 'text',
                         'relative_path': str(path.relative_to(root)),
                         'parts_relative_dir': str((folder / 'parts').relative_to(root)),
                         'characters': len(result), 'parts_dir': str(folder / 'parts'),
                         'part_count': part_count},
        '_delivery': (
            'The complete tool result is saved in this task workspace. Load the JSON '
            'file with a quantlib_call __data_ref__ argument. For read_file, use the exact '
            'parts_relative_dir + /1.txt path relative to your current task workspace, '
            'through part_count in order. Do not refetch data because this preview '
            'is shortened. Source row limits/sampling still apply: inspect the '
            'original result coverage before calculating; saving does not fill missing rows.'
        ),
    }
    if isinstance(payload, dict):
        for key in ('status', 'ok', '_provenance', '_unresolved', '_diagnostics'):
            if key in payload:
                receipt[key] = payload[key]
    # Keep compact calculation bases visible beside the file reference. Curves
    # and large tables stay intact in the artifact rather than hiding the basis.
    if isinstance(payload, dict):
        for key in ('calculation_basis', 'comparisons', 'expiry_scenarios', 'summary', 'inputs'):
            if key in payload:
                candidate = {**receipt, key: payload[key]}
                if len(json.dumps(candidate, ensure_ascii=False)) <= TOOL_RESULT_LIMIT // 2:
                    receipt[key] = payload[key]
    # Bound the receipt too. Source metadata stays in the complete artifact if
    # it alone is larger than the delivery budget; no false absence is implied.
    if len(json.dumps(receipt, ensure_ascii=False)) > TOOL_RESULT_LIMIT // 2:
        for key in ('_diagnostics', '_provenance', '_unresolved'):
            receipt.pop(key, None)
        receipt['_metadata_location'] = 'Source metadata is in the complete result file.'
    room = max(0, TOOL_RESULT_LIMIT // 4 - len(json.dumps(receipt, ensure_ascii=False)))
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
