OGCR project context:

- This instance makes heavy use of dynamic entities (system-level Dynamic Entities on OBP).
- When the user mentions carbon credits, projects or registries, look for the matching
  dynamic entity endpoints (e.g. /obp/dynamic-entity/...) before falling back to core endpoints.
- Example entity record: {"project_id": "OGCR-001", "status": "issued"}
- Prefer asking the user which registry they mean if more than one is available.
