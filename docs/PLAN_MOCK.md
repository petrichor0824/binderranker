# BinderRanker `plan-mock`

`binderranker plan-mock` is an offline development, testing, and
demonstration command for the BinderRanker Agent planning layer.

It supplies a deterministic mock `UserRequest` payload in place of a
real model response.

It does **not**:

- call a model API;
- grant execution approval;
- execute BinderRanker;
- submit remote jobs.

## Minimal example

Create `payload.json`:

    {
      "project_name": "demo",
      "input_dir": "sample_data/test_two_chain",
      "input_layout": "existing_chains",
      "binder_chain": "A",
      "execute_requested": false
    }

Run:

    binderranker plan-mock \
      --payload payload.json \
      --text "Rank this backbone dataset" \
      --output runs/agent/mock_plan.json

The command writes a planning-session JSON file.

## Core payload fields

| Field | Meaning |
| --- | --- |
| `project_name` | Optional project identifier. |
| `input_dir` | Candidate backbone PDB directory. Required for a complete request. |
| `input_layout` | Input-chain layout. Required for a complete request. |
| `binder_chain` | Binder chain for an `existing_chains` request. |
| `source_chain` | Source chain for a `concatenated_single_chain` request. |
| `target_residue_count` | Target length for a `concatenated_single_chain` request. |
| `target_chains` | Optional target-chain identifiers. |
| `desired_regions` | Optional desired target/interface regions. |
| `undesired_regions` | Optional undesired regions. |
| `hotspots` | Optional hotspot residues. |
| `region_policy` | Region handling policy. Default: `diagnostic`. |
| `region_filter` | Region filtering mode. Default: `off`. |
| `requested_top_k` | Requested result count. Default: `30`. |
| `execute_requested` | Records whether the user asked for execution. It does not grant approval or execute BinderRanker. |

The natural-language request comes from `--text` or `--text-file`.
The mock payload represents the structured fields that a model provider
would otherwise return.

## Concatenated single-chain example

For a request in which target and binder are stored in one source chain,
the corresponding information includes the source chain and target
residue count:

    {
      "project_name": "single_chain_demo",
      "input_dir": "data/candidates",
      "input_layout": "concatenated_single_chain",
      "source_chain": "A",
      "target_residue_count": 140,
      "normalized_target_chain": "A",
      "normalized_binder_chain": "B",
      "execute_requested": false
    }

`normalized_target_chain` and `normalized_binder_chain` must remain
distinct.

## Safety semantics

`execute_requested: true` only records that execution was requested.
The planning layer does not treat that field as approval.

Actual approval and execution remain separate deterministic BinderRanker
workflow steps.
