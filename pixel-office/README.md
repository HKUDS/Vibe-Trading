# Pixel Office

This workspace is the management place for the Pixel Agent office.

It keeps three tracks:

- Trading research and signal generation
- Risk and execution oversight
- Office operations and delegation routing

Use the included Python manager to create agents, assign work, and monitor the office state.

Quick start:

```bash
PYTHONPATH=agent python -m src.pixel_agents.cli --help
PYTHONPATH=agent python -m src.pixel_agents.cli init --storage ./pixel-office/office_state.json
PYTHONPATH=agent python -m src.pixel_agents.cli dashboard --storage ./pixel-office/office_state.json
```
