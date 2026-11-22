"""Parser registration for research-related command families."""
from __future__ import annotations
import argparse

def register(subparsers: argparse._SubParsersAction) -> None:
    from src.factors.cli_handlers import add_subparser as add_alpha
    from src.hypotheses.cli_handlers import add_subparser as add_hypothesis
    from src.research_artifacts.cli_handlers import add_subparser as add_artifact
    from src.research_lab.cli import add_subparser as add_lab
    from cli.commands.research_playbook import add_subparser as add_playbook
    from cli.commands.strategy_evidence import add_subparser as add_strategy
    from cli.commands.paper_trade import add_parser as add_paper
    add_alpha(subparsers)
    add_hypothesis(subparsers)
    add_artifact(subparsers)
    add_lab(subparsers)
    add_playbook(subparsers)
    add_strategy(subparsers)
    add_paper(subparsers)
