###################
Notebook parameters
###################

Times Square notebooks can declare *parameters* in their sidecar YAML file (``{notebook}.yaml``).
Each parameter has a name and a JSON Schema that describes its type, default, and constraints.
Viewers set parameter values through the page's URL query string, and Times Square substitutes those values into the notebook before it is executed.

Parameter naming rules
======================

A parameter's name must:

- Be a valid Python variable name: it must start with a letter and contain only letters, numbers, and underscores.
- Not be a Python keyword (for example, ``lambda`` or ``class``).
- Not start with the reserved ``ts_`` prefix.

.. _ts-prefix-reservation:

The ``ts_`` prefix is reserved
------------------------------

The Squareone frontend reserves ``ts_``-prefixed URL query parameters for viewer controls (such as ``ts_hide_code`` and ``ts_nav_focus``) and strips all ``ts_*`` keys before requesting a render.
A notebook parameter named ``ts_start`` could therefore never receive a value from the UI — it would silently fall back to its schema default even when the browser URL appeared to set it.

To prevent this ambiguity, Times Square rejects any parameter whose name starts with ``ts_``.
If a notebook's sidecar declares such a parameter, its GitHub check run fails with an error that names the offending parameter and explains the reservation.
Rename the parameter so it does not start with ``ts_``.
