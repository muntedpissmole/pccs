"""Desired-state automation engine for PCCS."""

from .world import WorldStore
from .policy import desired_outputs
from .precedence import resolve_light, resolve_screen
from .reconcile import Reconciler

__all__ = ["WorldStore", "desired_outputs", "resolve_light", "resolve_screen", "Reconciler"]