##############################
Backfilling GitHub numeric IDs
##############################

Times Square records GitHub's stable numeric IDs — the repository ID, its owner's ID, and the ID of the Times Square GitHub App installation — on every page it syncs from a GitHub repository.
Those IDs survive organization and repository renames, so Times Square keys its rename handling on them rather than on the ``owner/repo`` name strings that a rename invalidates.

Pages created before Times Square started recording those IDs have none.
Such pages are still found by their owner and repository names, and they get their IDs the next time their repository is synced, but until then a rename of their repository is only healed by that next sync.
The ``backfill-github-ids`` command fills the IDs in for every such page at once, so that renames are handled by ID from the start.

Running the backfill
====================

Run the command once, from a pod that has the Times Square configuration and secrets, after deploying a version of Times Square that captures the IDs:

.. code-block:: sh

   times-square backfill-github-ids

The command resolves each distinct ``owner/repository`` name pair through the GitHub App API and reports what it did:

.. code-block:: text

   repositories resolved: 12
   repositories skipped: 1
   pages filled: 87

Pass ``--dry-run`` first to see what the run would fill in.
A dry run still resolves every repository through the GitHub API, but writes nothing:

.. code-block:: sh

   times-square backfill-github-ids --dry-run

The command is safe to re-run: pages that already carry a repository ID are never rewritten, because their IDs came from a sync, which is authoritative.

Repositories the GitHub App cannot resolve — because they were deleted, made private, or renamed while Times Square was not receiving webhooks — are logged with their owner and repository names and skipped, and the run carries on.
For an organization or user rename that the App never saw, run :samp:`times-square rename-github-owner --old {old} --new {new}` to update the stored owner strings, then run the backfill again.

Running as a Kubernetes job
===========================

In a Phalanx environment, run the command as a one-off Kubernetes ``Job`` in the Times Square namespace.
The job's pod needs the same image, environment, and secrets as the Times Square API deployment, since the command reads the database configuration and the GitHub App credentials from the environment.

Copy those from the running deployment:

.. code-block:: sh

   kubectl get deployment times-square -n times-square -o yaml

and apply a job that reuses them, overriding the container command:

.. code-block:: yaml

   apiVersion: batch/v1
   kind: Job
   metadata:
     name: times-square-backfill-github-ids
     namespace: times-square
   spec:
     template:
       spec:
         restartPolicy: Never
         # Copy containers[0].image, env, envFrom, and volumeMounts, plus
         # any volumes and the service account, from the times-square
         # deployment.
         containers:
           - name: backfill
             image: ghcr.io/lsst-sqre/times-square:<tag>
             command: ["times-square", "backfill-github-ids"]

Then read the report from the job's logs:

.. code-block:: sh

   kubectl logs -n times-square job/times-square-backfill-github-ids

Delete the job once the report looks right.

Daily name reconciliation
=========================

Once a page carries its repository's numeric ID, Times Square keeps its stored names current on its own.
A daily ``reconcile_github_names`` cron in the worker re-reads every repository behind a live page from the GitHub API — by its numeric ID, which no rename or transfer changes — and rewrites the stored owner and repository names whenever they disagree with GitHub's answer.
That heals renames that happened while Times Square was down, or whose webhook delivery failed, without waiting for the repository's next push.
Like the rename webhooks, it is a pure name flip: nothing is re-synced from GitHub and no notebook is re-executed.

The cron logs one summary line per run:

.. code-block:: text

   Reconciled GitHub repository names  repositories_checked=12 repositories_healed=1
   repositories_skipped=0 repositories_failed=1 pages_updated=7

A repository counted in ``repositories_failed`` is one the GitHub App could not read, logged with the status code GitHub returned.
Its pages are always left exactly as they are: a deleted repository, an uninstalled app, and a transient authentication failure are indistinguishable from here, and only the webhooks can tell them apart.
``repositories_skipped`` counts repositories whose current owner is no longer in :envvar:`TS_GITHUB_ORGS`; their names are reported rather than healed, so that pages are never moved into an organization Times Square does not sync from.

Pages that have no numeric IDs yet are not reconciled — that is what the backfill above is for.
