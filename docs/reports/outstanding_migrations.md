# Outstanding MDQ+ Migration Order

This repository does not record which SQL files have already been applied to
each environment. Confirm the target database state before applying any item.

For Task 8, apply this migration before deploying the matching backend code:

1. `backend/migrations/add_reliable_support_messages.sql`

The migration is additive and creates the durable support submission table.
It has been created for deployment and was not executed during implementation.
