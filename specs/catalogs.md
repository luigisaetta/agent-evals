# Synthetic Automotive catalogs

## Scope and provenance

Provide local reference data for future Express Order requests, offers, and evaluation datasets. Store three UTF-8 JSON arrays in `data/catalogs/`, with English names and no extra record fields beyond the contracts below.

Supplier names are fictional. Part names and average costs are illustrative synthetic data, not supplier quotations or verified market prices. Locations use real European capitals as hypothetical plant destinations; they do not represent actual company plants.

## Catalog contracts

* `suppliers.json`: 50 records with `id` and `name`. IDs range from `SUP-001` to `SUP-050`.
* `parts.json`: 100 records with `id`, `name`, and `average_cost_eur`. IDs range from `PART-001` to `PART-100`. The cost is an indicative per-unit part cost in euros, represented as a positive JSON number with at most two decimal places. It is reference data for future generation, not an offer's total delivery cost or an additional ranking criterion.
* `locations.json`: 10 records with only `id`, `country`, and `name`. IDs range from `LOC-001` to `LOC-010`. Names are European capitals and include Rome (`Rome` is the English name for Roma). Country names are in English.

IDs and names must be unique within each catalog. Each ID is a stable reference and must not be reassigned to another entity when the catalogs are edited.

## Relationship to the offer-selection task

Future offers can reference supplier catalog `id` through `supplier_id` and part catalog `id` through `part_id`. The current request and offer contract still represents `delivery_location` as the location's city `name`; the location catalog ID does not change that contract. No assumption is made that every supplier can provide every part.

These catalogs are reference data, not evaluation cases, agent outputs, or expected selections. This change does not implement a generator or alter selection rules.

## Acceptance criteria and verification

Parse all files using Python in the `agent-evals` environment. Verify exact record counts, exact field sets, non-empty strings, sequential unique IDs, unique names, positive two-decimal-compatible costs, and the expected set of ten capital/country pairs including Rome, Italy. No external service calls or additional dependencies are required.
