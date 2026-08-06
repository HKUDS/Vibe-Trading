"""Valuation models: DCF, comparable companies, three-statement projection.

The audit that motivated this package found no executable DCF, WACC, terminal
value or comps engine anywhere in the repository -- only markdown describing
them. These modules are the executable form.

Import submodules directly, so a missing optional dependency in one cannot
break the others::

    from src.quantlib.valuation.dcf import run_dcf
    from src.quantlib.valuation.comps import run_comps

Submodules:
  contracts       Shared input discipline -- missing inputs stop the model
  dcf             FCFF bridge, WACC build, dual terminal value, sensitivity grid
  comps           Peer set, calendarisation, EV bridge, multiple matrix
  threestatement  Linked P&L / cash flow / balance sheet with a hard balance check

The one rule every module here obeys is in :mod:`contracts`: a missing input
makes a model NOT RUNNABLE and is never silently defaulted. A valuation built
on quietly-chosen constants is indistinguishable, downstream, from one built on
filed statements -- and that is exactly the failure this package exists to make
impossible.
"""
