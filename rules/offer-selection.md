# Offer selection rules

Rules version: `1.1`

## Business context

These rules apply to offer selection for an Automotive Express Order. A company manufacturing cars across multiple plants initiates an Express Order when a plant's stock availability for a part drops. Invited suppliers submit offers, and the agent selects the best offer for delivery to the requesting plant.

The agent receives an existing request and collected offers. These rules do not determine stock thresholds, initiate orders, invite suppliers, or place purchase orders. The plant's delivery destination is represented by its European city in the current task.

## Request and offers

The request identifies the required spare part by `part_id`, the required European delivery city by `delivery_location`, and an exclusive delivery deadline by `latest_delivery_date`.

Each offer contains a unique `offer_id`, a `supplier_id`, a `part_id`, a `delivery_location`, a `delivery_date`, and a `total_cost_eur`. The cost is the total amount for delivering the requested part, expressed in euros. Use this amount directly; do not add charges or perform currency conversion.

`supplier_id` is a required non-empty string identifying the supplier. Multiple offers may share the same supplier ID. Supplier identity does not affect eligibility or ranking under these rules.

Dates use the `YYYY-MM-DD` calendar-date format. Part identifiers and delivery city values use the same canonical representation in requests and offers and are compared exactly. Do not infer alternative part identifiers or city aliases.

## Eligibility

An offer is eligible only when all of the following conditions hold:

1. Its `part_id` equals the request's `part_id`.
2. Its `delivery_location` equals the request's `delivery_location`.
3. Its `delivery_date` is strictly earlier than the request's `latest_delivery_date`.

An offer delivering on the deadline itself is not eligible. Exclude ineligible offers before comparing costs, even if they are cheaper.

## Selecting the best offer

1. Among eligible offers, select the one with the lowest `total_cost_eur`.
2. If multiple eligible offers have the same lowest cost, select the one with the earliest `delivery_date`.

Here, the nearest delivery means the earliest calendar date, not the date closest to the deadline. An earlier delivery does not take precedence over a lower cost.

Return the chosen offer's identifier as `selected_offer_id`.

## Initial dataset scope

Initial evaluation cases contain at least one eligible offer and have a unique winner after applying both ranking rules. Cases with no eligible offers, or multiple offers tied on both lowest cost and earliest delivery date, require an additional policy and are outside this initial version. Do not invent another ranking rule.
