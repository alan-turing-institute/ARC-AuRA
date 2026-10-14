#!/bin/sh
# Start the server as the owner of the /cache bind mount (./litmcp/cache on the host),
# so the server can always write its cache and the files belong to the host user who
# owns that folder, whatever their uid. The container starts as root only to do this,
# then drops to that user before running anything else.
set -eu

if [ "$(id -u)" != 0 ]; then
    # Already started as a specific user (e.g. compose `user:`); nothing to switch
    exec "$@"
fi

uid=$(stat -c %u /cache)
gid=$(stat -c %g /cache)

if [ "$uid" = 0 ]; then
    # ./litmcp/cache didn't exist, so Docker created it as root. Hand it to the
    # image's litmcp user rather than running the server as root.
    chown 1000:1000 /cache
    uid=1000
    gid=1000
fi

exec setpriv --reuid="$uid" --regid="$gid" --clear-groups -- "$@"
