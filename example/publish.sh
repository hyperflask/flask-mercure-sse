#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $0 <message>"
    exit 1
fi

jwt=$(uv run flask mercure publisher-jwt)
uv run flask mercure publish --hub http://localhost:5000/.well-known/mercure --jwt "$jwt" "messages" "<p>$1</p>"