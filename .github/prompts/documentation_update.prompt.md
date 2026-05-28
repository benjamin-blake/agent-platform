---
name: documentation_update
description: Execute an evidence-based documentation update. Run git diff, extract evidence from every changed file, discover and update all relevant .md documentation files in the repository, then clean and commit. Do not stop until all five phases are complete.
agent: agent
model: GPT-5 mini
tools: ['execute/getTerminalOutput', 'execute/runInTerminal', 'read', 'edit/editFiles', 'search', 'agent']
---

## Intent

Document a specific set of code changes from a feature branch. Scope is `git diff origin/main` only. Does not audit the whole repository.

---

## YOUR TASK: Execute a Documentation Update

You are performing a documentation update. Work through **Phases 0–5 in sequence**. Do not skip phases. Do not stop after planning — write the actual file edits and commit them.

**Governing principles (apply throughout):**

1. **Single Source of Truth**: Every documentation change must be justified by actual code changes visible in `git diff origin/main`.
2. **Evidence-Based**: Every claim must reference the file it came from (e.g., `lambda/preprocessing/handler.py`).
3. **No Speculation**: If the code does not support a claim, flag it explicitly rather than inventing details.
4. **Traceability**: Add `<!-- Evidence: ... -->` comments above each change while drafting (remove them in Phase 5).

---

## ✅ Definition of Done

**Documentation updates are COMPLETE ONLY when ALL of the following are satisfied:**

1. ✅ **Phase 0**: Evidence extracted from `git diff origin/main`
2. ✅ **Phase 1-4**: All four documentation files updated with evidence citations
3. ✅ **Phase 5 - MANDATORY CLEANING**:
   - **5a**: CHANGELOG.md is in descending date order (newest first)
   - **5b**: ALL evidence comments `<!-- Evidence: ... -->` removed from final files
   - **5b**: ALL verification indicators (✅, 🔄, ⚠️) removed
   - **5b**: NO references to `personal_scripts/` remain
   - **5c**: Changes committed with descriptive message

⚠️ **CRITICAL**: If Phase 5 cleaning is incomplete, the documentation is NOT done. Evidence comments in the final commit will cause PR rejection.

---

## 🗺️ Documentation Discovery & Update Strategy

**Before updating, discover which .md documentation files exist in the repository** by listing the root and subdirectories for `README.md`, and checking for any domain-specific documentation files (e.g., `terraform/README.md`, `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE-WORKFLOW.md`, `docs/DECISIONS.md`, `docs/ROADMAP-PRODUCT.md`, `docs/ROADMAP-PLATFORM.yaml`, etc.).

Use this strategy to determine which discovered files need updating based on change type:

| Change Type | CHANGELOG.md | Root README | Domain-Specific READMEs (terraform/, etc.) | AGENT_WORKFLOW.md |
|---|---|---|---|---|
| Code logic & functions | ✓ Added/Changed | ✓ Architecture | ✓ if domain-specific (e.g., infrastructure for Terraform) | Only if workflow behaviour changes |
| Infrastructure/config | ✓ Added/Changed | ✓ if architecture-level | ✓ Update domain README if exists | Only if agent tooling affected |
| New modules or files | ✓ Added/Changed | ✓ if user-facing | ✓ Update domain README if exists | Only if workflow entrypoints change |
| Environment config | ✓ Changed | ✓ Setup section | ✓ Update domain README if affects domain | No |
| Bug fixes | ✓ Fixed | Only if user-facing | Only if user-facing | No |
| Dependencies | ✓ Added/Changed | Conditionally | ✓ Update domain README if domain-specific | No |
| Prompt files changed | ✓ Changed | No | No | ✓ Update if workflow loop, routing, or override docs change |

**Principle**: Update CHANGELOG.md always. For other files, only update if the changes are relevant to that document's scope.

---

---

## 📊 Execution Phases — Work Through These Now

### Phase 0 — Evidence Discovery (start here)

1. Run `git diff origin/main` to identify all changes.
2. For every modified or added file, record:
   - File path and purpose
   - Function/macro names and parameters
   - Configuration values and defaults
   - New environment variables
   - Breaking changes
3. Build an evidence list before touching any documentation file:
   ```
   [Evidence: lambda/preprocessing/handler.py | Implements automated S3 metadata extraction]
   [Evidence: terraform/modules/lambda/ | New environment variable: BAG_VALIDATION_MODE]
   ```
4. Use the Decision Matrix below to map each changed file to the documentation files that need updating.

### Phase 1 — Observe & Extract

1. For each changed file identified in Phase 0, read the diff and extract exact details: function signatures, variable names, default values, environment variable names.
2. Note any breaking changes or deprecations.
3. Discard internal refactors that have no user-facing effect.

### Phase 2 — Verify & Cross-reference

1. Open each documentation file that the Decision Matrix flagged for update.
2. Find every section that references the changed code.
3. Identify contradictions between the current documentation and the new code.
4. Flag anything the code does not support — do not document it.

### Phase 3 — Update Documentation Files

1. **Discover** which .md files exist in the repository (root, subdirectories, domain-specific docs).
2. **Map changes** to the appropriate documentation files using the updated strategy above.
3. Edit each flagged file. Add `<!-- Evidence: path/to/file.ext | Description -->` immediately above every changed line or block.
4. Use UK English throughout (summarise, behaviour, optimise).
5. Use exact names from the code — no abbreviations or interpretations.
6. For CHANGELOG.md: add a new version entry dated today in `[X.Y.Z] - YYYY-MM-DD` format with `Added`, `Changed`, and `Fixed` subsections as appropriate.

### Phase 4 — Validate Traceability

1. Confirm every documentation claim has a corresponding evidence comment above it.
2. Check that evidence citations are accurate (correct file path, correct description).
3. Verify all existing documentation content is preserved unless directly contradicted.
4. Confirm all internal links and cross-references still resolve.

### Phase 5 — Mandatory Cleaning & Commit

**Do not skip this phase. Evidence comments must not appear in the final commit.**

**5a — Verify CHANGELOG.md date order**: Entries must be newest first. Fix the order if needed.

**5b — Strip all evidence artefacts** from every file edited:
- Remove ALL `<!-- Evidence: ... -->` comments
- Remove ALL `<!-- Verified: ... -->` comments
- Remove ALL verification indicators: ✅ ✓ 🔄 ⚠️ 📝
- Remove ALL references to `personal_scripts/`

Confirm with:
```powershell
Get-Content (Get-ChildItem -Filter "*.md" -Recurse) | Select-String "Evidence|Verified|personal_scripts" -ErrorAction SilentlyContinue
```
If there is any output, keep cleaning.

**5c — Commit**:
```powershell
git add (Get-ChildItem -Filter "CHANGELOG.md" -Recurse | Select-Object -ExpandProperty FullName -First 1), (Get-ChildItem -Filter "README.md" -Recurse)
git commit -m "docs: [brief description of what changed]"
```

---

## Example: Complete Documentation Update

### Branch Changes Identified
```
FROM: git diff origin/main

1. File: lambda/preprocessing/handler.py
   - Added function: validate_bag_format(event)
   - Added environment variable: BAG_VALIDATION_ENABLED (default: True)
   - Modified: handler() function signature (added validation_mode parameter)

2. File: terraform/modules/lambda/main.tf
   - New variable: bag_validation_enabled (type: bool, default: true)
   - New environment variable mapping: BAG_VALIDATION_ENABLED

3. File: lambda/preprocessing/requirements.txt
   - Added dependency: bagit==1.8.1
```

### Documentation Updates (WITH evidence for review)

**CHANGELOG.md Update:**
```markdown
## [0.0.2] - 2026-01-15

### Added
<!-- Evidence: lambda/preprocessing/handler.py | validate_bag_format function -->
- Bag validation against BagIt v1.0+ specifications in preprocessing Lambda
<!-- Evidence: terraform/modules/lambda/main.tf | bag_validation_enabled variable -->
- New environment variable `BAG_VALIDATION_ENABLED` to control validation behaviour
<!-- Evidence: lambda/preprocessing/requirements.txt | bagit==1.8.1 dependency -->
- bagit==1.8.1 dependency for validation operations

### Changed
<!-- Evidence: lambda/preprocessing/handler.py | handler() function signature -->
- Lambda handler now accepts validation_mode parameter
```

**Root README.md Update (Architecture Section):**
```markdown
<!-- Evidence: lambda/preprocessing/handler.py | validate_bag_format() function -->
**Preprocessing (AWS Lambda):** Triggered by S3 events, the preprocessing Lambda handles extraction and preparation when bags arrive. New in [0.0.2]: validates incoming bags against BagIt v1.0+ specifications before processing.

<!-- Evidence: terraform/modules/lambda/main.tf | BAG_VALIDATION_ENABLED variable mapping -->
The validation behaviour is controlled by the BAG_VALIDATION_ENABLED environment variable (default: enabled).
```

### After Phase 5 Cleaning (FINAL - NO evidence comments)

**CHANGELOG.md (final version):**
```markdown
## [0.0.2] - 2026-01-15

### Added
- Bag validation against BagIt v1.0+ specifications in preprocessing Lambda
- New environment variable `BAG_VALIDATION_ENABLED` to control validation behaviour
- bagit==1.8.1 dependency for validation operations

### Changed
- Lambda handler now accepts validation_mode parameter
```

**Root README.md (final version):**
```markdown
**Preprocessing (AWS Lambda):** Triggered by S3 events, the preprocessing Lambda handles extraction and preparation when bags arrive. New in [0.0.2]: validates incoming bags against BagIt v1.0+ specifications before processing.

The validation behaviour is controlled by the BAG_VALIDATION_ENABLED environment variable (default: enabled).
```

---

---

## ✅ Pre-Submission Checklist

**BEFORE creating the PR, verify ALL items:**

### Phase 1-4 Verification (Content)
- [ ] Every documentation claim has a corresponding code snippet in git diff
- [ ] Evidence citations include file path and location (line number or function name)
- [ ] No details were invented or inferred (only actual code content is documented)
- [ ] All existing documentation remains unless explicitly contradicted by new code
- [ ] Cross-references and links are still valid
- [ ] UK English spelling and terminology are consistent
- [ ] All four files are updated where applicable (use Decision Matrix)
- [ ] Breaking changes are highlighted with clear migration path
- [ ] Code examples match actual implementation from branch
- [ ] CHANGELOG entry includes version number and date in ISO format (YYYY-MM-DD)

### Phase 5 Cleaning (MANDATORY - PR WILL BE REJECTED WITHOUT)
- [ ] **5a**: CHANGELOG.md is in descending date order (newest first)
- [ ] **5b**: NO `<!-- Evidence: ... -->` comments remain in any file
- [ ] **5b**: NO verification indicators (✅, 🔄, ⚠️) remain in any file
- [ ] **5b**: NO references to `personal_scripts/` remain in any file
- [ ] **5c**: Run `git diff origin/main` and verify output looks correct
- [ ] **5c**: Committed with clear message describing updates
- [ ] **5c**: Ready to push and create PR

⚠️ **CRITICAL**: If any Phase 5 item is incomplete, do NOT submit. Evidence comments in the final commit will cause automatic PR rejection.

---

---

## Usage Tips

### ✅ When to Use This Approach
- **Feature releases**: Document new functionality across all layers with evidence
- **Bug fixes**: Update relevant sections with file references
- **Architecture changes**: Reflect changes in terraform/ and root README with evidence
- **Setup process changes**: Update setup instructions with implementation references
- **Dependency updates**: Document version changes with exact file references
- **Breaking changes**: Highlight changes that affect users with evidence citations

### 🎯 Best Practices
1. **Be specific**: Use exact file names, function names, variable names from code
2. **Discover before documenting**: Identify all .md files in the repository (root, subdirectories, domain-specific docs) before making assumptions about documentation structure
3. **Layered documentation**:
   - Root README.md: High-level architecture and overview
   - Domain-specific READMEs (e.g., terraform/README.md): Domain-specific details and examples
   - CHANGELOG.md: Chronological record with file and function references
   - Other domain docs (if present): Architecture decisions, roadmaps, getting started guides
4. **Evidence first**: Extract evidence from code BEFORE writing documentation
5. **UK English**: Use consistent terminology (summarise, behaviour, optimise, etc.)
6. **Link appropriately**: Cross-reference related sections and files when needed

### 📝 Example: Complete Documentation Update Request

Here's a more detailed real-world example:

```
Update documentation for: "Added new data processing module"

## Changes Made
- Created new module: src/data/processors/custom_processor.py
- Implements data validation and transformation logic
- Integrates with existing pipeline architecture

## Update Strategy:
1. First, discover all .md files in the repository
2. Identify which are relevant to this change:
   - CHANGELOG.md: Always update
   - Root README.md: Update if changes affect overall architecture
   - Domain-specific docs (e.g., terraform/README.md): Update only if relevant
   - Other docs (ARCHITECTURE.md, ARCHITECTURE-WORKFLOW.md, DECISIONS.md, etc.): Update if decision/architectural impact (use ARCHITECTURE.md for trading system changes; ARCHITECTURE-WORKFLOW.md for workflow/executor/telemetry changes)

## Example updates:

### CHANGELOG.md (ALWAYS)
Add entry under new version section:
- Added custom_processor module for enhanced data transformation

### README.md (if architecture-relevant)
Update architecture section to reference new processing capability

### terraform/README.md or other domain docs (if applicable)
Update only if the module affects infrastructure, deployment, or domain-specific workflows

Format all markdown consistently with the existing documentation style.
```

---

## 📝 See Also
- [Full Audit Prompt](documentation_full_audit.prompt.md) - Comprehensive repository documentation audit
- [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) - CHANGELOG format standard
- Repository .md files - Discover all documentation in the repository before assuming structure
