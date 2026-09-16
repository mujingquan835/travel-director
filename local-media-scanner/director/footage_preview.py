"""Retired R06 experiment: retained import guard, no media editing implementation."""
from director.project import ProjectConflict


def build_footage_preview(*args, **kwargs):
    raise ProjectConflict('R06 corrected: footage editing/rendering is retired; use --build-guide for music and picture suggestions.')
