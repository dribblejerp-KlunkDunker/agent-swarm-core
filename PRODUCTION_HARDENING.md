# Production hardening and deployment contract

## Supported deployment profile

The runtime's durable coordination profile is **single-host, multi-process**. SQLite transactions serialize approval, lock, task, evidence, and audit updates across processes that share the same local database file. This implementation is not a distributed database and must not be treated as safe multi-host coordination on NFS or an arbitrary shared filesystem. Use a server database and a database-backed lock adapter before deploying multiple hosts.

This is an engineering hardening baseline, not a security certification. Review the controls below against the deployment's threat model.

## Mandatory production configuration

Set all three variables before constructing runtime components:

- SWARM_ENV=production
- SWARM_STATE_DB=/absolute/path/to/swarm-state.sqlite3
- SWARM_AUDIT_KEY=<a secret of at least 32 characters, from your secrets manager>

The audit key turns the audit log into an HMAC chain. Inject it at process start from a secrets manager; never store it next to the database or in the repository. Losing the key means the existing chain can no longer be verified, so back it up with the same care as the database. A database written without a key cannot later be opened with one (and vice versa): the runtime refuses rather than mixing chain modes, so archive an unkeyed development database and start a new one for production.

The database path must be on a durable local filesystem. The runtime rejects missing paths and in-memory storage when production mode is enabled. SQLite database files are restricted to owner read/write on POSIX systems; store the file in a directory owned by the runtime service account with directory permissions 0700. Back up the database consistently and test restores.

Use a dedicated low-privilege OS identity for the runtime. Do not place the database in the source checkout, a shared downloads directory, or a temporary directory. Keep database backups and any exported audit data under the same confidentiality controls.

## Approval identity is an integration responsibility

In production, ApprovalGate fails closed unless approver_authorizer is provided. The callback must validate actor against a trusted authentication context or identity provider and confirm that the actor has the required approval role for the record. A string comparison or a caller-supplied display name is not authentication.

The callback should be short-running, deterministic, and fail closed on network errors or unknown identities. Do not call arbitrary services while holding the application's own locks. The adapter must authenticate the current actor independently; do not build this callback by trusting record.approver alone.

Example contract (illustrative; connect it to the application's real identity layer):

    def authorize_approver(actor, approval_record):
        principal = trusted_identity_context.current_principal()
        return (
            principal is not None
            and principal.subject == actor
            and principal.has_role("release-approver")
            and approval_record.scope in principal.allowed_release_scopes
        )

The application must call ApprovalGate.approve(task_id, approver=authenticated_subject, evidence=current_evidence) only after interactive or service-to-service authentication. A valid approval is bound to the requested action, exact scope, evidence digest, expiry, approver, requester, and an audit event hash. Replacing the approval row without the corresponding audit proof is rejected.

Request approvals through RuntimeServices.request_approval(task, scope=..., approver=...). It records the task owner as the requester, and the requester can never approve. In production, can_proceed denies any approval without a recorded requester (reason separation_of_duties_unverified), so an approval requested directly on the gate cannot be used to act.

Actions are matched by category. An action string that names more than one irreversible category, such as "merge and deploy", becomes a compound action that only an approval for that same compound action can satisfy.

## Resource locking

Use the same SWARM_STATE_DB for every runtime component on a host. Resource identities must be normalized and consistent; use repository-relative POSIX paths for files and directories and documented stable identifiers for external resources.

Locks are leased for 30 minutes unless the caller chooses another duration (up to 7 days). Renew the lease before it expires during long work; do not choose a short lease without implementing a heartbeat. An expired lease is removed and audited when a lock API next checks state, so a crashed agent cannot hold a resource forever. Locks without a lease are refused in production.

These locks coordinate cooperating runtime processes; they do not prevent an unrelated process from editing files outside the runtime.

## Evidence and audit trail

Evidence is stored in SQLite and starts in PENDING; only the registry can change it to VERIFIED. Registry reads return detached values so modifying a returned Python object cannot change stored status. Evidence content may contain confidential information: store only material that is necessary, prohibit secrets and credentials, restrict database access, and encrypt the storage volume/backups according to the deployment policy.

The audit log is append-only through the runtime API and HMAC-chained in production. SQLiteStateStore.verify_audit_chain() detects modification or reordering of logged events. Without the audit key, someone who can write the database file cannot recompute a valid chain after editing it.

Deleting the newest events is still invisible to the chain alone. Export checkpoints regularly with SQLiteStateStore.audit_checkpoint() (or `swarm audit checkpoint --out <file>`) to storage the database host cannot rewrite, and verify against the latest one with verify_audit_chain(anchor=checkpoint) or `swarm audit verify --anchor <file>`. RuntimeServices.health_check(audit_anchor=...) includes the anchor in its readiness verdict. This is **tamper-evident, not tamper-proof**: someone holding the key and write access to both the database and every checkpoint store can still rewrite history.

Task records must change only through RuntimeServices in production. TaskBoard.add_or_update() and TaskBoard.save() write without lifecycle checks and raise in production; in development they are allowed and logged with lifecycle_checked=false.

Never place passwords, access tokens, API keys, private keys, credential values, or raw secrets in approval notes, lock reasons, evidence titles, task objectives, logs, or audit payloads. Keep evidence references concise and content out of ordinary audit events.

## Release and recovery procedure

1. Ground the repository and create a bounded task record.
2. Reserve resources before editing; capture a checkpoint before a risky change.
3. Collect test/build/diff/security evidence and have the evidence registry verify it.
4. Move the task to READY_FOR_RELEASE only with matching verified evidence references.
5. Create a pending approval for the exact action and scope. Move to AWAITING_APPROVAL only when that request matches the task's evidence.
6. Authenticate the approver using the application's identity adapter and approve the unchanged evidence bundle.
7. Before performing an external side effect, call can_proceed with the action, exact scope, and current evidence. Fail closed on errors.
8. Record the outcome and post-action evidence. Back up the database and test restoration routinely.

Restoring a task board does not authorize resumed work. Revalidate state, approval expiry and proof, evidence, repository revision, and locks before execution.

## CI and repository governance

The Runtime Validation workflow runs regression tests, bytecode compilation, and the runtime audit (`python -m runtime selftest`) with read-only repository permissions. The audit drives a full production lifecycle against a real database file with a keyed chain, and proves that an unkeyed rewrite and a truncated history are both detected. A final step installs the package and runs the `swarm` CLI. Its third-party actions are pinned to full commit SHAs, and execution is bounded by a timeout.

**GitHub branch protection is a repository setting and is not changed by this code commit.** Before treating main as a protected production branch, open Repository Settings, then Branches or Rulesets, and apply a rule to main that:
- requires pull requests for changes,
- requires the runtime-audit status check,
- blocks force pushes and branch deletion,
- requires review for changes by collaborators where the team size allows it,
- dismisses stale approvals when the diff changes.

After saving the rule, verify the branch API reports protection enabled and confirm a direct push is rejected. For a single-maintainer repository, a self-review requirement may be counterproductive; use a second trusted reviewer when available and document any emergency bypass.

## Operational gaps that remain deployment-specific

The repository intentionally does not invent an identity provider, production deployment target, backup service, secrets manager, or distributed lock backend. Those integrations must be supplied and exercised in the target environment before a multi-host or externally accessible deployment is approved. The current workflow proves the behavior of this code on GitHub's hosted Linux runner; it does not prove runtime configuration, access control, data retention, recovery objectives, or production infrastructure.
