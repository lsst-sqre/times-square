### Other changes

- Times Square now explicitly refuses to check notebooks from forks. Before creating or re-running GitHub check runs, the worker verifies that the repository's owner is in `TS_GITHUB_ORGS` and that the head commit doesn't come from a fork's pull request. Previously, forks were excluded only as a side effect of GitHub sending `check_suite` webhook events solely for commits pushed to the repository where the app is installed.
