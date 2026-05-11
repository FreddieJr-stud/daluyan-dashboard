# Ferry Sprite Map Auto-Adjust

**Date:** 2026-03-29
**Status:** Approved
**Branch:** feat/dalaray-voice

## Problem

The ferry sprite (with its pulsing blue circle, ~80px diameter) gets hidden behind two UI overlay elements on the map view:

1. **"Back to Speed Table" button** — top-left area of the map
2. **Bottom-left white prediction/SOC box** — shows SOC range, anomaly chips, tide info

The existing `_ensureFerryVisible()` at `main.dart:1890-1918` has two issues:
- Hardcoded overlay zone (520px wide, 240px tall from bottom) doesn't match actual element sizes
- Only checks the bottom-left zone — the top button is never checked
- Only pans horizontally — vertical overlap is ignored

## Solution

Use `GlobalKey` on each overlay widget to dynamically measure their screen bounds. On every ferry position update, check if the blue circle collides with any overlay and snap the map to clear the overlap.

## Detailed Design

### 1. GlobalKey Declarations

Add two `GlobalKey` instances to `_DashboardHomeState`:

```dart
final _overlayKeySpeedBtn = GlobalKey();
final _overlayKeyBottomBox = GlobalKey();
```

Attach these keys to:
- The "Back to Speed Table" / navigation button widget
- The bottom-left `Positioned` widget containing SOC/anomaly/tide info

### 2. Screen Rect Helper

```dart
Rect? _getOverlayRect(GlobalKey key, {double padding = 20.0}) {
  final renderBox = key.currentContext?.findRenderObject() as RenderBox?;
  if (renderBox == null || !renderBox.hasSize) return null;
  final topLeft = renderBox.localToGlobal(Offset.zero);
  return Rect.fromLTWH(
    topLeft.dx - padding,
    topLeft.dy - padding,
    renderBox.size.width + padding * 2,
    renderBox.size.height + padding * 2,
  );
}
```

The `padding` parameter adds a margin around the element so the ferry doesn't sit right at the edge.

### 3. Updated `_ensureFerryVisible(LatLng ferryPos)`

Algorithm:
1. Skip if `_userOverrideMap` is true (user manually panning)
2. Run in `addPostFrameCallback` (needs layout to be complete)
3. Convert `ferryPos` to screen coordinates via `camera.latLngToScreenPoint()`
4. Build ferry collision rect: screen point ± 40px (blue circle radius)
5. For each overlay key, get its padded screen rect
6. If ferry rect intersects an overlay rect, compute the minimum (dx, dy) shift to clear it
7. Accumulate shifts from all overlapping elements
8. Convert shifted map center to LatLng via `camera.pointToLatLng()`
9. Call `_mapController.move(newCenter, camera.zoom)` — instant snap

Shift calculation per overlap:
- `dx`: move ferry right past overlay's right edge, OR left past overlay's left edge — whichever is shorter
- `dy`: move ferry down past overlay's bottom edge, OR up past overlay's top edge — whichever is shorter
- Pick the direction that requires the smallest displacement

### 4. No Animation

Map snaps instantly to the adjusted position. This avoids visual jitter from frequent small animations as the ferry moves continuously.

### 5. User Override Respected

The existing `_userOverrideMap` flag (set when user manually pans/zooms, resets after 15s timer) prevents the auto-adjust from fighting user interaction.

## Files Modified

- `flutter_application_1/lib/main.dart`:
  - Add 2 `GlobalKey` declarations
  - Add `_getOverlayRect()` helper method
  - Rewrite `_ensureFerryVisible()` with dynamic collision detection
  - Add `key:` parameter to the speed table button widget and bottom-left positioned widget

## No New Dependencies

Uses only existing Flutter APIs (`GlobalKey`, `RenderBox`, `Rect`).
