# Opey: local models and limiting customer data exposure

Working notes. Covers where an on-premise model earns its place in Opey, what an embedding model is and is not good for, and how to keep raw Open Bank Project (OBP) API responses out of a language model's context window.

---

## 1\. Why an on-premise model at all

The argument for a self-hosted model such as Mistral is not capability — it is that customer data never leaves the bank's perimeter. That reframes the question to: which tasks are worth doing *because* they touch raw account data?

Reasonable candidates:

- Transaction enrichment — merchant name normalisation, category tagging, recurring-payment detection. High volume, narrow, well within a small model's ability.  
- Summarising an account or statement period after Opey has made the API calls.  
- Anomaly or dispute triage — flagging an out-of-pattern transaction, drafting the first line of a support ticket.  
- Explaining what a given Consent actually grants, in the customer's language.

### The hybrid pattern

Run the local model as a redaction and de-identification layer. It removes or tokenises identifying data from the API response; a hosted frontier model does the harder multi-step reasoning on the sanitised version; the local side restores the real values before display. Frontier-quality orchestration, nothing identifiable crossing the boundary.

### Honest scoping

Small self-hosted models degrade noticeably on multi-turn tool use — which is exactly what Opey does when chaining OBP calls. Natural-language-to-endpoint mapping is feasible with a constrained endpoint schema and output validation, but needs real evaluation before it runs unsupervised. Do not plan on a small local model for long-context work over a full API specification.

---

## 2\. Embedding models

An embedding model converts text into a fixed-length vector, positioned so that similar meanings land near each other. It emits no words — only coordinates. It cannot rewrite, redact or restructure anything.

Used for semantic search: chunk the documents, embed each chunk once, store the vectors. At query time, embed the question, retrieve the nearest chunks, insert them into the generative model's prompt. This is the retrieval half of retrieval-augmented generation.

Easy to self-host: typically a few hundred megabytes, acceptable on CPU, no GPU required, milliseconds per chunk. Open-weight families worth evaluating include BGE, E5, Nomic Embed and Jina — rankings shift, so check the Massive Text Embedding Benchmark leaderboard rather than trusting a name.

Two points worth having ready for bank conversations:

- A *hosted* embedding endpoint means sending the full raw text of every indexed document to a third party. Banks often scrutinise the generative model and wave the embedding step through, which is backwards — indexing is usually the higher-volume transfer.  
- Vectors are not encryption. Embedding inversion research shows meaningful reconstruction of source text from stored vectors, so a vector database inherits the classification of whatever went into it, and needs the same access controls.

### Where embeddings help Opey

Highest value is the endpoint catalogue, not the documentation. OBP exposes several hundred endpoints across multiple API versions, plus per-bank dynamic endpoints. Embedding each endpoint's summary, description, tags and parameter schema, then retrieving the top handful per question, turns endpoint selection from a context-window problem into a retrieval problem. The same applies to tool selection in the Model Context Protocol server.

Then, in rough order of value: the glossary and error-message catalogue; per-bank dynamic entities and endpoints; the bank's own product terms and runbooks.

Three things determine whether it works:

- **Retrieval must inherit the authorisation model.** A vector index knows nothing about Consents. If an index holds entitlement-scoped content, similarity search will return it to a caller the API would have refused. Filter by the caller's entitlements as part of the query, not afterwards.  
- **Version and deployment metadata, not just similarity.** Without a hard filter on API version, Opey will recommend deprecated v3.1 endpoints on a v5.x instance.  
- **Hybrid retrieval.** Pure vector search is weak on exact tokens such as endpoint names and error codes. Combine with keyword search.

### Where embeddings do not help

Do not embed transaction or account data. Transactions are queried with filters through the API, which already enforces Consents. Vectorising them creates a second copy of customer data outside that control path, for no retrieval benefit.

---

## 3\. How much of an API response does the model actually see?

By default, all of it. In a standard tool-calling loop the entire response body is inserted into the context window verbatim as a tool result.

Two consequences banks will ask about:

- **Consents bound what the API returns, not what the model sees of it.** They are the outer perimeter; within it there is no second filter. "Access is governed by Consents" is true, but answers a narrower question than the one being asked.  
- **It persists and is re-transmitted.** The payload stays in context for the rest of the session and is sent again on every subsequent turn. One call fetching 200 transactions can cross the boundary a dozen times in a conversation.

Also worth auditing separately: the tracing and observability layer. Tools such as LangSmith capture full request and response payloads by default, and that store is frequently a larger and longer-lived copy of customer data than anything the model provider retains.

---

## 4\. The layered approach to sanitisation

Sanitisation belongs in the tool wrapper, between the API response and the context window. The model never receives the raw body because the raw body is never handed to it — not because the model was instructed to ignore it.

### Layer 1 — Field restriction: already solved by Views

OBP Views restrict which fields an API call returns, and Opey's Consents are scoped to particular Views. This is better than a client-side allowlist because it is enforced server-side: the restriction survives a compromised or buggy Opey deployment, since the excluded fields were never transmitted at all. Worth stating explicitly in bank conversations.

A standard, deliberately minimal Opey View definition per account type would be a concrete sellable artefact — a bank can inspect it field by field before granting anything. It turns "Opey respects Consents" into "here is precisely what Opey can see."

Two things Views do not cover, which is where the remaining work sits: they restrict *which* fields, not what is inside them; and they restrict fields, not volume.

### Layer 2 — Tokenisation

Replace identifiers with stable placeholders (`ACCOUNT_1`, `PARTY_3`), holding the mapping in the session store outside the context. Tokens must be consistent within a session, or the model cannot tell that six transactions went to the same payee, and must carry a type hint, or it loses track of what the field is.

Largely redundant where a View already excludes identifiers and counterparty names. Worth considering only where a View must expose an identifier for the answer to be useful and the hosted model should not see it.

### Layer 3 — Rehydration

Code substitutes real values back into the model's answer before display. The authorised user sees real data throughout; the model saw none of it. Only needed if you tokenise, and it is the fiddliest layer to get right — so not needing it is a good outcome.

### Layer 4 — Free text

Transaction descriptions, payment references and memo fields carry unstructured personally identifiable information that no field restriction catches. This is the genuine job for an on-premise model — and a dedicated named-entity-recognition model (spaCy, or a fine-tuned encoder) beats a generative one on accuracy, latency and cost. Run it over those fields only.

Recall is the weak point: names, addresses and identifiers in payment references are messy and multilingual, and no recogniser catches everything. Mask aggressively — replace anything entity-shaped and accept false positives — rather than precisely.

Better still, ask whether the free text is needed at all. For most questions the description field matters only for merchant identification and categorisation. If a local model derives the category *before* sanitisation and only the category crosses the boundary, the raw description never needs to.

### Layer 5 — Aggregate in code instead of reading records

This addresses volume, which is a separate problem from fields. Views control which columns cross the boundary; nothing yet controls how many rows.

"How much did I spend on groceries last quarter" implemented naively means 2,000 records in the context, re-sent every turn. Instead, the model emits a specification of what it wants computed; code executes it against the response, which stays outside the context; only the result goes in — one number, or twelve monthly numbers. Exposure drops by roughly three orders of magnitude, and stays dropped for the whole session.

It is also more accurate. Models are unreliable at summing hundreds of figures; a `sum()` in code is not. The privacy argument and the correctness argument point the same way, which makes it an easier sell internally than most privacy work.

Design decisions:

- The specification must be a constrained schema, not generated code. Validate against a whitelist of operations before execution — no model-authored expressions evaluated against customer data.  
- Keep a clean fallback for questions that genuinely need records ("what was that odd payment last Tuesday"). Hard-cap the record-reading path at a small page size so the aggregate path is the only way to answer volume questions.

---

## 5\. Where this converges

Views handle fields. Aggregation handles volume. A local model handles free text by summarising rather than passing it through. Tokenisation becomes optional rather than foundational.

Two things make it defensible rather than merely well-intentioned:

**The sanitiser must sit on the far side of a trust boundary the model cannot cross** — a separate service, not a prompt instruction or a tool the model can call with different parameters. A useful property: prompt injection in a transaction description cannot defeat tokenisation, because the model has no access to the mapping regardless of what it is persuaded to attempt.

**Test it adversarially.** A leak-detection pass over serialised context — known values from the raw response, regular expressions for account and card formats, checksum validation on International Bank Account Numbers — running in continuous integration against real endpoint shapes. Assume the sanitiser is wrong somewhere and build the thing that finds out.

---

## Open questions

- Does Opey reliably pick the aggregate path over reading records? That is a model-behaviour question, and needs evaluation against a real question distribution rather than assumption.  
- What does the tracing and observability layer currently retain?  
- Which View is granted to Opey by default, and is a minimal standard View definition worth shipping as a product artefact?

