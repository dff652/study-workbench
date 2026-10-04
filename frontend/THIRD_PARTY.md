# Third-party frontend components

Selected layout and shadcn-style component source is copied from [`satnaing/shadcn-admin`](https://github.com/satnaing/shadcn-admin), pinned at commit `e16c87f213a5ba5e45964e9b67c792105ec74d26` (MIT; copyright 2024 Sat Naing). The complete license text is in [`LICENSE`](LICENSE). Hashes below are SHA-256 for both the pinned upstream files and the copied files in this repository; matching values verify the copies are unmodified.

| Upstream file | SHA-256 |
|---|---|
| `src/components/ui/button.tsx` | `97ed8ef5651a6e264ded042b024b5be39673ba2ff222017fbcf845cf3ed37226` |
| `src/components/ui/card.tsx` | `72728c3734479c247347759fc11bb01c3acac38f8e87da6aeb03d69c39e0f9cc` |
| `src/components/ui/badge.tsx` | `a642d7a932b91ec610f09078452d34c379900845066955311506b6d503ea11e6` |
| `src/components/ui/table.tsx` | `8ebadfa3965fc72792d160579ff6beb0b80d9dd0d3acd56db7a34168e956b531` |
| `src/components/layout/main.tsx` | `e200dbc0e1b8cf383fdf6b7f7588ac1c9419de65f2658692e7941324bd09c572` |
| `src/styles/theme.css` | `faee559c9a21b2084bf7bae193e70f0ab18b18a393a06fec1408669652c266a1` |
| `src/lib/utils.ts` | `cc244af40baa5fe88abff3f80b424a7aa654b3137a7db612a8fe94861b61e04e` |

This frontend uses its own same-origin session and API flow. It does not copy the upstream demo authentication or business data.

The complete installed license texts for bundled React, Radix, Lucide, class-variance-authority, clsx, scheduler, tailwind-merge and Tailwind CSS dependencies are retained in [DEPENDENCY_LICENSES.txt](DEPENDENCY_LICENSES.txt), with versions from the lock file. The runtime image copies these to `/app/licenses/frontend-dependency-notices.txt`; legal notices do not depend on minifier comment retention.
