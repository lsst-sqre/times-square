### New features

- Notebook parameter names may no longer start with the reserved `ts_` prefix, which Squareone uses for viewer-control URL query parameters (such as `ts_hide_code` and `ts_nav_focus`) and strips before requesting renders. A `ts_`-prefixed parameter could never receive a value from the UI, so `validate_parameter_name` now rejects it with an error that names the parameter and explains the reservation. The violation surfaces through the GitHub check-run validation for notebook repositories, and the reservation is documented in the user guide.
