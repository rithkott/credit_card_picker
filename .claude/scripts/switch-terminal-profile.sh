#!/bin/bash
# Terminal profile switcher

PROFILE="${1:-}"

case "$PROFILE" in
  Blossom|Cherry|Coffee|Forest|Ocean|Space)
    osascript -e "tell application \"Terminal\" to set current settings of window 1 to settings set \"$PROFILE\""
    if [ $? -eq 0 ]; then
      echo "✓ Switched to $PROFILE profile"
    else
      echo "✗ Failed to switch to $PROFILE profile"
    fi
    ;;
  "")
    echo "Available profiles: Blossom, Cherry, Coffee, Forest, Ocean, Space"
    echo "Usage: switch-terminal-profile.sh <profile>"
    ;;
  *)
    echo "Unknown profile: $PROFILE"
    echo "Available profiles: Blossom, Cherry, Coffee, Forest, Ocean, Space"
    exit 1
    ;;
esac
