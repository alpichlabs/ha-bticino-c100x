# BTicino C100X Linphone runtime

This private helper embeds CPython 3.9 and the official Linphone 5.4 Python
distribution. It is the sole SIP/media owner for the Home Assistant integration
and communicates only through a mode-0600 Unix socket.

The helper and the combined runtime archive are licensed under GPLv3. The
corresponding helper source is `runtime/helper.py`; Linphone source for the exact
5.4 build is available from Belledonne Communications and is linked from the
release notes. Build inputs are checksum-pinned by `runtime/build-runtime.sh`.

The archive is Linux amd64 only. Never start the helper manually with production
credentials; Home Assistant supervises its lifecycle and sanitizes diagnostics.
