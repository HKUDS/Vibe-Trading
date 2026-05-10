# Delta for strategy-export

## ADDED Requirements

### Requirement: Amibroker AFL Export
`/pine <run_id>` MUST additionally emit an Amibroker AFL file (`strategy.afl`) when the source run uses the VN equity engine, alongside existing Pine v6, TDX, and MQL5 outputs.

#### Scenario: One-command VN export
- GIVEN a completed VN equity strategy run `vn123`
- WHEN the user issues `/pine vn123`
- THEN four files are written to `agent/runs/vn123/exports/`:
  `strategy.pine`, `strategy.tdx`, `strategy.mq5`, `strategy.afl`
- AND each file is syntactically valid in its target platform

### Requirement: AFL Syntax Validation
Generated AFL code MUST pass syntax validation before being written to disk, consistent with the existing Export Validation Before Import requirement.

#### Scenario: Invalid AFL refused
- GIVEN a generated AFL string that fails the syntax validator
- WHEN the exporter attempts to write
- THEN the write is refused
- AND a clear error names the offending construct
- AND no partial `.afl` file is left on disk

### Requirement: VN Compliance Disclaimer in Exports
All VN strategy exports MUST embed a UBCK-compliant disclaimer comment header stating that the output is research, not investment advice.
