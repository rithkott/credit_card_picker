---
name: color
description: Switch Terminal profiles
---

Switch between your Terminal profiles.

## Usage

`/color [profile-name]`

Without arguments, shows available profiles.

## Profiles

- **Blossom** - `osascript -e 'tell application "Terminal" to set current settings of window 1 to settings set "Blossom"'`
- **Cherry** - `osascript -e 'tell application "Terminal" to set current settings of window 1 to settings set "Cherry"'`
- **Coffee** - `osascript -e 'tell application "Terminal" to set current settings of window 1 to settings set "Coffee"'`
- **Forest** - `osascript -e 'tell application "Terminal" to set current settings of window 1 to settings set "Forest"'`
- **Ocean** - `osascript -e 'tell application "Terminal" to set current settings of window 1 to settings set "Ocean"'`
- **Space** - `osascript -e 'tell application "Terminal" to set current settings of window 1 to settings set "Space"'`

## Examples

```
/color Blossom
/color Ocean
/color
```
