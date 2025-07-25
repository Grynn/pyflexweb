"""
PyFlexWeb - Interactive Brokers Flex Web Service Client

A command-line tool to easily download IBKR Flex Activity and Trade Confirmation reports.
"""

try:
    from importlib.metadata import version
except ImportError:
    # Python < 3.8
    from importlib_metadata import version  # type: ignore

__version__ = version("pyflexweb")
