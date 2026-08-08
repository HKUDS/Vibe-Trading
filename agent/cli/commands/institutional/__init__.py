"""Institutional research workflow slash commands.

This package turns five recurring sell-side / buy-side workflows into explicit,
discoverable slash commands instead of prose buried in a swarm preset:

``/comps``      comparable company analysis
``/dcf``        discounted cash flow
``/attrib``     Brinson-Fachler performance attribution
``/memo``       investment memo
``/earnings``   earnings surprise bridge
``/screen``     systematic idea screen

Layout — deliberately import-cycle free:

``playbooks.py``
    Pure data. Imports nothing from :mod:`cli`, so
    :mod:`cli.commands.slash_router` can read the command specs at its own
    import time without a circular import.
``runner.py``
    Rendering + prompt construction + the shared ``run_playbook`` entry.
``comps.py`` / ``dcf.py`` / ``attrib.py`` / ``memo.py`` / ``earnings.py`` /
``screen.py``
    One thin ``run(ctx, *args)`` module per command. The REPL dispatcher
    (``cli.main._dispatch_slash``) passes the command keyword only for the
    modules listed in ``_MULTI_COMMAND_MODULES``; every other handler module
    owns exactly one command, so each command gets its own module here.

This ``__init__`` intentionally stays import-free.
"""
