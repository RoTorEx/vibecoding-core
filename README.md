# Vibecoding Core

Host-owned native agent sessions for Remote Vibecoding.

The sibling telegram-vibecoding repository owns the Telegram interface. Common
Compose/workspace operations live under deployment/workspace and are linked
from the workspace root. See BUSINESS.md, docs/architecture.md and TASK.md.

Python 3.13+ and uv are required for development. Run make install and make check.

Each component has independent semantic versions, changelog and annotated Git
tags. The canonical version is its own src package __init__.py; Hatch derives
package metadata from it. uv.lock locks dependencies and records the root
package as dynamic; the installed metadata and wheel carry the concrete version.
Run make release interactively and enter MAJOR.MINOR.PATCH at the prompt; this
checks, updates metadata/changelog and creates a local release commit/tag.
Then make release-push atomically pushes only this repository's main and release
tag and verifies the remote references. Neither command deploys or releases the
sibling. Common deployment continues to select each image revision separately.

Both projects use Vibecoding Kernel 1.3.5. Run make vibe-pull to refresh the local
committed rules; make vibe-kernel-set configures the machine-local kernel path.
