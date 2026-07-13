### New features

- Imports of local Python modules (sibling `.py` files or packages in the same GitHub repository) are now automatically inlined into GitHub-synced notebooks at sync time, so those notebooks execute correctly under Noteburst, which only receives the notebook file itself. Modules are resolved against the notebook's own directory first and then the repository root, mirroring how imports resolve when running the notebook interactively in JupyterLab. The inlined module cells are inserted before the notebook's parameters cell and reconstruct each module in `sys.modules`, so the notebook's own import statements work unchanged. Notebooks without local imports are unaffected.

### Bug fixes

- The parameters-cell marker (`times_square.cell_type = "parameters"` cell metadata) is now reliably reapplied on every sync of a GitHub-backed page, not just when the page is first created. Previously the marker was lost when an existing page was re-synced, since GitHub is the source of truth and the notebook is re-fetched fresh on every sync.

- A notebook whose content fails to load or inline during a repository sync no longer causes the sync to delete that notebook's previously-synced page; the page is kept as-is and the error is logged.
