# Contributors

This is a rolling credit store, not a one-time thank-you page. It gets
updated every time a pull request (or a directly pushed commit) lands on
`main`: a new contributor gets a row, an existing one's count goes up. Rank
is by merged pull requests, with commit counts alongside for context, since
one PR can be a single commit or forty.

## Built on

This project would not exist without
[**blinkpy**](https://github.com/fronzbot/blinkpy) — the Python library that
does the actual Blink account login, token refresh, camera discovery, and
the live-view handshake this proxy extends across both the `immis://` and
`rtsps://` transports. Written and maintained by **Kevin Fronczak**
([@fronzbot](https://github.com/fronzbot)).

## Leaderboard

Counted from this repository's merged pull requests and `git log` on
2026-09-10, at the 0.8.0 release. Commits include merge commits, and the
several git identities some contributors have committed under are counted
together.

| Rank | Contributor | Merged PRs | Commits |
|---|---|---|---|
| 1 | [@Teethree89](https://github.com/Teethree89) | 19 | 119 |
| 2 | [@bbolinger](https://github.com/bbolinger) | 19 | 26 |
| 3 | [@fritzzetik](https://github.com/fritzzetik) | 4 | 9 |
| 4 | [@ivhazu](https://github.com/ivhazu) | 1 | 1 |

@bbolinger drew level on merged pull requests at 0.8.0, taking five of the
seven in that release; rank is held on the commit tiebreak.

## Maintaining this file

When a pull request merges into `main`:

1. Find the author's row, or add one if this is their first PR — a first PR
   counts starting at #1, not once some threshold is hit.
2. Add 1 to "Merged PRs", and add that PR's commit count to "Commits".
3. Re-sort by Merged PRs, ties broken by Commits.

A commit pushed straight to `main` without a PR counts toward "Commits" only.
