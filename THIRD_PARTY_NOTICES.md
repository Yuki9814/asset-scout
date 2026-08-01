# Third-party notices

Asset Scout does not vendor external downloader or resolver code. Users install and manage these executables separately; the application records the resolved executable path, version output, and SHA-256 digest in local integration diagnostics and acquisition lineage.

## parse-video-py

- Project: [wujunwei928/parse-video-py](https://github.com/wujunwei928/parse-video-py)
- Pinned revision: `4904bb27e311f7302b0c8b4121724ef0b3491399`
- License: MIT (see the upstream repository at the pinned revision)
- Invocation used by Asset Scout: `parse-video-py parse URL --format json`

The resolver is replaceable and failure-closed. Asset Scout does not store resolver media URLs as durable source metadata, does not pass browser cookies, and performs its own HTTPS, redirect, private-address, size, MIME, media-readability, and digest checks during acquisition.

## BVText

BVText is an optional external executable discovered from `ASSET_SCOUT_BVTEXT_BIN`, `PATH`, or a project-local ignored override. Asset Scout does not copy the BVText repository or binary. Refer to the local BVText project for its own license and dependency notices.
