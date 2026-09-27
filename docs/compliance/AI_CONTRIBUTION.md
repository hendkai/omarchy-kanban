# AI-assisted development and release scope

Release: 1.1.0 · assessed 2026-09-27 · maintainer: `hendkai`.

## Development provenance

AI assistance was used for implementation, documentation, test creation, code review, and release preparation. Known tools/models for this work: Hermes Agent with Z.AI GLM-5.3 for implementation, and OpenAI GPT-6 Astra for orchestration and independent tool-based verification. An earlier Codex Spark invocation was rejected before producing code; it is not credited with implementation.

Verification is agent-operated and backed by actual test output and live UI checks. This document does **not** assert that a human reviewed every line, that tests establish security, or that any percentage of the code is human/AI authored. Release ownership and maintenance remain with the repository maintainer. No private prompts, task records, machine addresses, credentials, or original private Git history are part of this public repository.

## Shipped functionality

The plugin is a deterministic SQLite status reader and QML interface. It performs no model inference, training, biometric processing, emotion recognition, synthetic media generation, or automated Kanban decisions. It displays existing task titles and counts, rather than generating them. Optional SSH collection executes this repository's collector with the selected remote account's permissions. See SECURITY.md for the actual trust boundary.

## Regulatory scope and limitations

This release is offered as free MIT-licensed community software; no paid service, monetisation, warranty, or commercial support commitment is attached to this release. The European Commission's CRA open-source guidance distinguishes software supplied in a commercial activity from non-monetised free/open-source software. This is an initial scope assessment, not a legal opinion, conformity declaration, CE claim, or exemption guarantee. Reassess if the distribution or support model changes.

AI-assisted coding and an AI-powered shipped product are different questions. The described runtime contains no AI model or inferential AI service. No claim of EU AI Act certification or exhaustive legal compliance is made. The full consolidated legal texts were not successfully retrieved during release preparation; legal conclusions requiring those texts remain outside this technical release review.

Sources consulted on 2026-09-27:

- European Commission, CRA open-source guidance: https://digital-strategy.ec.europa.eu/en/policies/cra-open-source
- European Commission, AI system definition guidelines (non-binding guidance): https://digital-strategy.ec.europa.eu/en/library/commission-publishes-guidelines-ai-system-definition-facilitate-first-ai-acts-rules-application
- Legal-text reference, Regulation (EU) 2024/2847: https://eur-lex.europa.eu/eli/reg/2024/2847/oj
- Legal-text reference, Regulation (EU) 2024/1689: https://eur-lex.europa.eu/eli/reg/2024/1689/oj

Review again at the next release, before adding model-generated output or new network destinations, on commercialisation, or when security/legal requirements change; scheduled scope review by 2027-03-27.
