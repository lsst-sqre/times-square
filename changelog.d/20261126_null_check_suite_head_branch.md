### Bug fixes

- Times Square now accepts `check_suite` webhooks for check suites that have no head branch. GitHub can report a check suite's head branch as null, and Times Square failed to parse such a webhook, so the delivery failed and no check runs were created. The commit is still checked only if it is on a branch of the repository: the head of a branch, or in the history of the default branch.
