# Delta for skills

## ADDED Requirements

### Requirement: Eight Vietnam Skills
The package MUST ship at least 8 Vietnam-specific skills, distributed across existing categories:

| Skill | Category |
|-------|----------|
| `vn-data-routing` | Data Source |
| `vn-financial-statements-vas` | Analysis |
| `vn-sector-rotation-vn` | Analysis |
| `vn-vn30-arbitrage` | Strategy |
| `vn-ex-rights-calendar` | Flow |
| `vn-foreign-room` | Risk Analysis |
| `vn-margin-list` | Risk Analysis |
| `vn-pre-warning-stocks` | Risk Analysis |

#### Scenario: VN skills discoverable
- WHEN the user issues `/skills` after `pip install vibe-trading-ai`
- THEN all 8 VN skills appear in their declared categories
- AND each shows name, category, and 1-line description

### Requirement: Foreign Ownership Room Tracking
The `vn-foreign-room` skill MUST fetch current foreign ownership and remaining room for any HOSE/HNX listed stock, raising an alert flag when room is ≥95% utilized.

#### Scenario: Full-room warning
- GIVEN `MWG` foreign room is 99.2% utilized
- WHEN the skill runs
- THEN the result includes `room_full=true` and `room_remaining_pct=0.8`
- AND downstream strategy generation MUST consider room constraint before proposing foreign-investor-targeted entries

### Requirement: VAS Financial Statements
The `vn-financial-statements-vas` skill MUST fetch point-in-time VAS statements via `VNFundamentalProvider` and emit results with both VAS account codes and IFRS-equivalent labels.

#### Scenario: VAS↔IFRS mapping
- WHEN the skill returns balance sheet for `FPT` Q4 2024
- THEN each line item carries `vas_code`, `ifrs_label`, `value_vnd`
- AND the mapping JSON is documented and version-pinned

### Requirement: VN Bundled-Skill Regression Coverage
Every Vietnam skill MUST be pinned by at least one regression test, consistent with the existing Bundled-Skill Regression Coverage requirement.

#### Scenario: CI fails on missing VN skill
- GIVEN a PR that removes `vn-foreign-room` from the registry
- WHEN CI runs the bundled-skill regression suite
- THEN the test fails naming the missing skill
