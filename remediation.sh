#!/bin/bash

# Create a non-root user in the Dockerfile
sed -i.bak '/^ENTRYPOINT/i \
# Create a non-root user and switch to it\
RUN addgroup --system --gid 1001 appuser \\\
    && adduser --system --uid 1001 --gid 1001 --no-create-home appuser\
\
# Set ownership of application files to the non-root user\
RUN chown -R appuser:appuser /app\
\
# Switch to non-root user\
USER appuser' Dockerfile

# Remove backup file
rm -f Dockerfile.bak