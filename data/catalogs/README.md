# Automotive reference catalogs

These JSON arrays provide synthetic reference data for the Express Order use case:

| File | Records | Fields |
| --- | ---: | --- |
| [suppliers.json](suppliers.json) | 50 | `id`, `name` |
| [parts.json](parts.json) | 100 | `id`, `name`, `average_cost_eur` |
| [locations.json](locations.json) | 10 | `id`, `country`, `name` |

Supplier names are fictional. Automotive part costs are illustrative per-unit estimates in euros, not market quotations or total offer costs. Plant locations are hypothetical and use real European capitals, including Rome, Italy. All names are in English.

Use supplier and part IDs as `supplier_id` and `part_id` in future offers. The existing `delivery_location` field uses a location's city name. Average part costs do not change the offer-selection rules.

See the [catalog specification](../../specs/catalogs.md) for validation criteria and assumptions.
