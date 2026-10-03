"""Pixel Agents office manager for Vibe-Trading.

This package provides a lightweight task-and-agent management layer for a
trading office that coordinates several specialist agents. It keeps the system
self-contained and works as a starter for future expansion into live broker
automation, portfolio monitoring, and research handoff flows.
"""

from .office import Agent, OfficeManager, Task

__all__ = ["Agent", "OfficeManager", "Task"]
