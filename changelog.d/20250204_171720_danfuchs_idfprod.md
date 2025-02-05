### New features

- `GET /v1/github/rendered/{display_path}` that returns a rendered GitHub-backed notebook template. This route provides the same functionality as `GET /v1/pages/{page}/rendered`, but finds the page based on its GitHub URL path. This is an additional path, all existing functionality, including the existing template rendering path, remains unchanged.

  We need to deploy Times Square to environments where some users should not have permissions to execute notebooks, but they should have permissions to render notebook templates for certain GitHub-based notebooks. This will let us configure that access via methods that apply permissions based on URL paths.
