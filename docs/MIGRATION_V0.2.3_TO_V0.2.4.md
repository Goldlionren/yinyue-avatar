# Migration from v0.2.3 to v0.2.4

The loader recognizes schema v1. Before any migration write it builds and fully
validates a schema-v2 candidate, creates
`baseline-backups/state-v0.2.3-pre-migration-rNNNN.json`, re-reads the source to
detect concurrent change, atomically replaces state, and appends one migration
event. It never rewrites history. Re-running migration is a validated no-op.

Revision, `last_image`, prompt identifiers, character, all legacy visual and
internal values, and recent memory events are retained. The mapping is listed
in `STATE_SCHEMA_V0.2.4.md`. Tests use a synthetic, production-shaped revision
196 fixture and never write the real production state.

Rollback before deployment is `git checkout v0.2.3`. After a test migration,
stop writers, verify the pre-migration backup, and atomically restore it as
`state.json`; leave history intact or append an administrative rollback event.
For total disaster recovery use the v0.2.3 full recovery package and its
dry-run-first restoration script. Migration tests do not install into
production.
