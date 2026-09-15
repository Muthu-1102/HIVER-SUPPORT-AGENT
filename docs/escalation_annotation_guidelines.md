# Independent Escalation Annotation Workspace

This workspace is separate from the frozen intent gold set. Annotate the 40 reconstructed conversation threads referenced by conversation_id. Use the source manifest to locate each record in data/processed/spotify_conversations.jsonl; verify the source line and record hash before annotation.

## Annotation rules

Human escalation required means that, based on the customer conversation itself, a trained support operation should involve a human specialist or supervisor rather than completing the case through routine automated guidance. Examples include account compromise/security containment, a child/minor account issue requiring exception handling, repeated or duplicate charges requiring investigation, explicit unresolved-support escalation, or a sensitive case needing protected human handling.

Do not mark escalation solely because an issue is important, urgent-sounding, high priority, a billing/login/technical intent, or likely to benefit from a human response. A high-priority queue is not automatically a human-escalation decision.

Channel handoff is separate. Mark channel_handoff_required when the conversation requires moving to a private or authenticated channel to proceed safely. A channel handoff may occur without human escalation, and human escalation may occur without a channel handoff.

Use unclear when the available thread context does not support a reliable yes/no decision. Do not resolve uncertainty from production routing output, classifier predictions, candidate-screening metadata, or existing gold labels.

Record a concise verbatim evidence_quote from the customer conversation supporting the decision. If no single quote is sufficient, use the shortest relevant quoted span and explain the ambiguity in ambiguity_notes.

Use only these escalation types: security_account_compromise, minor_or_child_account, repeated_or_duplicate_charge, churn_or_cancellation_threat, prior_unresolved_support, privacy_or_secure_channel, other, none.

Use none only when escalation_required is no. Use one or more specific types when escalation_required is yes; use the best-supported type(s) when it is unclear, or use an empty list if no type can be supported. Do not use none together with another type.

Confidence is the annotator's confidence in the escalation decision, not confidence in the production classifier. Set is_ambiguous to true when multiple interpretations remain plausible.

## Provenance and independence

- Do not edit the source corpus, canonical gold annotations, candidate set, production code, or routing outputs.
- Do not copy production routing decisions into this annotation.
- Do not infer labels from target_queue, action, requires_human_escalation, intent labels, or cross-cutting flags.
- Do not use human LLM-judge safety scores as case-level escalation labels.
- Annotate the complete reconstructed thread, including customer and Spotify messages.
- A second annotator must complete the same records independently. Disagreements require separate adjudication before any metric is reported.

Blank values in the templates are intentional. The canonical gold annotations and existing intent adjudications remain unchanged.
