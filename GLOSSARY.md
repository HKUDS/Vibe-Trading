# Glossary

## Conversation Fork

An independent child conversation created from the committed history through a selected completed assistant turn.

## Source Session

The existing conversation selected for a Conversation Fork. It remains unchanged and may continue running.

## Fork Child

The new independent conversation created by a Conversation Fork. It records its immediate source for navigation and tracking but does not depend on that source for ownership or deletion.

## Completed Assistant Turn

A completed assistant response together with its associated tool calls and outputs. It is the cutoff unit for a Conversation Fork.

## Fork Lineage

The immediate source relationship between a Fork Child and its Source Session. Lineage supports navigation and tracking; it does not create cascading deletion or shared live execution state.

## Goal Snapshot

The current goal, claims, criteria, and evidence copied into a Fork Child when the fork is created, rather than reconstructed at the selected historical turn.
