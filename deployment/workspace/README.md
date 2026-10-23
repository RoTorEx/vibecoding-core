# Remote Vibecoding

One application workspace, two independent Git repositories and one Docker
Compose project with two application containers.

- telegram-vibecoding owns Telegram menus, messages, images and display.
- vibecoding-core owns host sessions, execution, history and the Core API.

This directory is not a third Git repository. Common Compose/Make/README
entrypoints are links to versioned files owned by Vibecoding Core. Keep each
component's source changes and commits in its own repository.

Codex runs on the host as the existing developer account through SSH so the
two-container deployment preserves native host/sudo access. No additional
persistent executor service is introduced.

See vibecoding-core/TASK.md for the accepted migration queue and component docs
for configuration, state, updates and recovery.
