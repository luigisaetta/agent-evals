# Automotive Express Order: offer selection

## Business context

The company operates multiple automotive manufacturing plants. When stock availability for a part at a plant decreases, an Express Order is initiated. Multiple suppliers are invited to submit offers to supply the part to that plant. The agent's responsibility in this project is to identify the best offer among those received.

Only offer selection is evaluated. Stock monitoring, the decision to initiate an Express Order, supplier invitations, offer collection, purchase-order placement, and delivery execution are upstream or downstream activities outside this scope.

Each evaluation case represents one Express Order for one part and one requesting plant's delivery destination. The current contract represents that destination as a European city through `delivery_location`; it does not introduce a `plant_id` or distinguish plants sharing the same city. The number of plants, invited suppliers, and received offers need not be equal.

## Problem and scope

Evaluate whether an LLM-based agent can select the best offer for an automotive production part in an Express Order by applying business rules written in natural language in a file.

The agent receives a request identifying a spare part, a delivery city, an exclusive delivery deadline, and N structured JSON offers. Offers may differ from the requested part or city and must be filtered according to the rules. It loads the rule text and selects an offer using an OCI Generative AI model through the Responses API. The evaluator compares the selected offer with the expected offer recorded in the dataset.

This specification defines the task, data contract, and success criterion. The natural-language business rules are maintained in [rules/offer-selection.md](../rules/offer-selection.md), version `1.1`. Implementation and dataset creation are subsequent work.

## Input and output contract

* Rules: `rules/offer-selection.md`. Its contents are supplied to the model for each task.
* Task input: a `request` object containing `part_id`, `delivery_location`, and `latest_delivery_date`, plus a non-empty `offers` array.
* Each offer contains `offer_id`, `supplier_id`, `part_id`, `delivery_location`, `delivery_date`, and `total_cost_eur`. Offer identifiers must be unique within the case.
* `supplier_id` is a required non-empty string identifying the supplier. It need not be unique within a case and does not affect eligibility or ranking.
* Identifiers and delivery locations are non-empty strings. Locations are canonical European city names, compared exactly, without alias resolution or implicit normalization.
* Dates are valid calendar dates in `YYYY-MM-DD` format, without times or time zones.
* `total_cost_eur` is a non-negative JSON number with at most two decimal places. Use decimal monetary comparisons, avoiding binary floating-point rounding artifacts.
* Agent output: structured JSON containing `selected_offer_id`, identifying one of the supplied offers.
* Dataset reference: `expected_offer_id`, stored separately from the task input and never included in the model prompt.
* Dataset metadata: a stable case identifier and the applicable rules version.

## Business rules

An offer is eligible only if its part ID and delivery city exactly match the request and its delivery date is strictly before the request's deadline. Delivery on the deadline is excluded.

Rank eligible offers by total cost in euros, ascending, then by delivery date, ascending. The earliest delivery wins a cost tie. This interprets "nearest delivery" as earliest delivery, rather than proximity to the deadline.

## Example

Task input:

```json
{
  "request": {
    "part_id": "PART-001",
    "delivery_location": "Milan",
    "latest_delivery_date": "2026-12-10"
  },
  "offers": [
    {"offer_id": "A", "supplier_id": "SUP-001", "part_id": "PART-001", "delivery_location": "Milan", "delivery_date": "2026-12-08", "total_cost_eur": 100.00},
    {"offer_id": "B", "supplier_id": "SUP-002", "part_id": "PART-001", "delivery_location": "Milan", "delivery_date": "2026-12-07", "total_cost_eur": 100.00},
    {"offer_id": "C", "supplier_id": "SUP-003", "part_id": "PART-001", "delivery_location": "Milan", "delivery_date": "2026-12-10", "total_cost_eur": 80.00},
    {"offer_id": "D", "supplier_id": "SUP-004", "part_id": "PART-002", "delivery_location": "Milan", "delivery_date": "2026-12-06", "total_cost_eur": 60.00},
    {"offer_id": "E", "supplier_id": "SUP-005", "part_id": "PART-001", "delivery_location": "Paris", "delivery_date": "2026-12-06", "total_cost_eur": 50.00},
    {"offer_id": "F", "supplier_id": "SUP-001", "part_id": "PART-001", "delivery_location": "Milan", "delivery_date": "2026-12-06", "total_cost_eur": 110.00}
  ]
}
```

Expected agent output: `{"selected_offer_id": "B"}`.

Offers C, D, and E are ineligible due to the deadline, part, and city respectively. B beats A on delivery date at equal cost and beats F on cost despite F's earlier delivery. The dataset stores `expected_offer_id: "B"` separately from the input.

## Success criterion

For each completed case with valid output:

`selection_correct = 1 if selected_offer_id == expected_offer_id else 0`

Compare identifiers exactly. This is a deterministic evaluation; no LLM judge is needed. A rationale, if added later, does not affect this score.

Report selection accuracy as the number of correct selections divided by the number of valid, scored cases. Also report total attempted cases, valid scored cases, invalid outputs, agent errors, and infrastructure failures, so a high accuracy cannot conceal incomplete evaluation coverage. Invalid outputs and execution failures cannot count as successful cases.

The criterion above defines success for an individual case. An experiment-level acceptance threshold has not yet been set.

## Assumptions and open decisions

* Initial cases contain at least one eligible offer and a unique winner after cost and delivery-date comparisons.
* Define the outcome when no offer is eligible, or when multiple offers tie on both lowest cost and earliest date, before adding such cases to the dataset. These cases are currently outside scope.
* Select the OCI model and connection configuration during implementation.

## Acceptance criteria and verification approach

* The agent receives the rule text, complete request, and offers, without the expected answer.
* Input validation requires a non-empty `supplier_id` for every offer and allows multiple offers from the same supplier.
* Eligibility checks cover mismatched parts, mismatched cities, and delivery dates before, on, and after the deadline.
* Ranking checks cover lower cost taking precedence over earlier delivery, and earlier delivery breaking equal-cost ties.
* The model selects the offer; application code validates the response without replacing the selection with its own ranking algorithm.
* Every valid selection refers to an offer present in the input.
* The evaluator assigns 1 to an exact reference match and 0 to a different valid selection.
* Invalid or unknown identifiers and execution failures are reported explicitly.
* Unit checks use local fixtures and mocked model responses to verify the input/output contract and scoring. Real OCI calls are optional integration checks.
* Experiments record rule and dataset versions, model configuration, selected and expected identifiers, scores, and execution status for later publication to Langfuse Cloud.
