# Agent evaluations

A Python project for evaluating the offer-selection component of an Automotive Express Order agent using natural-language business rules. Models run on OCI Generative AI through the Responses API. Evaluation datasets and results will be published to Langfuse Cloud, with a possible future move to self-hosted Langfuse on OCI.

## Business context: Automotive Express Order

The company operates multiple plants that manufacture cars. When the stock availability of a part at a plant drops, an Express Order is initiated to replenish that part. Multiple suppliers are invited to submit offers, and the agent identifies the best offer for the requesting plant.

The business workflow is:

1. A plant identifies reduced stock availability for a part.
2. An Express Order specifies the required part, delivery destination, and deadline.
3. Invited suppliers submit offers.
4. The agent selects the best offer using the documented business rules.

This project evaluates step 4 only. Stock monitoring, replenishment triggers, supplier invitations, offer collection, purchase-order placement, and delivery execution are outside scope. Requests and collected offers are provided as inputs.

For the initial task, the plant's delivery destination is represented by a European city. The current input contract does not distinguish different plants in the same city.

## Current task

The agent receives a requested part ID, a European delivery city, an exclusive delivery deadline, and JSON offers. It reads the rules from a separate file and returns the selected offer ID.

Each offer includes an offer ID, a supplier ID, a part ID, a delivery city, a delivery date, and a total cost in euros. Supplier IDs identify suppliers and do not affect the current selection rules.

An eligible offer must match the requested part and city and deliver strictly before the deadline. The lowest total cost in euros wins; equal costs are resolved by choosing the earliest delivery date.

The evaluator compares the selected offer ID with the expected ID stored separately in the dataset. An exact match scores 1; a different valid selection scores 0. Execution failures and invalid responses are reported separately.

Initial cases have at least one eligible offer and a unique winner after these rules. Policies for no eligible offers and remaining ties are still to be defined.

## Project documents

* [Task specification and JSON example](specs/offer-selection.md)
* [Catalog specification and data provenance](specs/catalogs.md)
* [Natural-language selection rules, version 1.1](rules/offer-selection.md)
* [Repository working rules](AGENTS.md)
* [Changelog](CHANGELOG.md)

## Development environment

Use the `agent-evals` Conda environment:

```sh
conda activate agent-evals
```

The project currently contains documentation, specifications, and [synthetic reference catalogs](data/catalogs/README.md): 50 suppliers, 100 automotive parts with average costs in euros, and 10 European capital cities representing plant locations. Agent implementation, evaluation datasets, dependencies, and Langfuse integration will follow.
