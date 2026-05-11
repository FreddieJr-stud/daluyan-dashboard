import 'dart:async';
import 'dart:io';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/painting.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:path_provider/path_provider.dart';

/// Tile provider that caches downloaded tiles to disk.
///
/// First request with WiFi downloads and saves the tile.
/// Subsequent requests (with or without WiFi) serve from disk cache.
class CachedTileProvider extends TileProvider {
  static Directory? _cacheDir;

  /// Must be called once before use (in main()).
  static Future<void> init() async {
    if (kIsWeb) return; // No file caching on web
    final appDir = await getApplicationCacheDirectory();
    _cacheDir = Directory('${appDir.path}/map_tiles');
    if (!_cacheDir!.existsSync()) {
      await _cacheDir!.create(recursive: true);
    }
  }

  // ── Pasig River corridor bounding box ──
  // Napindan (east) to Escolta (west), with ~0.005° padding
  static const double _minLat = 14.530;
  static const double _maxLat = 14.602;
  static const double _minLon = 120.972;
  static const double _maxLon = 121.108;

  /// Pre-cache Esri satellite tiles for the Pasig River corridor.
  /// [onProgress] reports (completed, total) counts.
  /// Returns the number of tiles downloaded (excludes already-cached).
  static Future<int> preCachePasigCorridor({
    List<int> zoomLevels = const [12, 13, 14, 15, 16],
    void Function(int completed, int total)? onProgress,
  }) async {
    if (_cacheDir == null) return 0;

    // Collect all tile coordinates
    final tiles = <(int z, int x, int y)>[];
    for (final z in zoomLevels) {
      final (x1, y1) = _latLonToTile(_maxLat, _minLon, z); // top-left
      final (x2, y2) = _latLonToTile(_minLat, _maxLon, z); // bottom-right
      for (int x = x1; x <= x2; x++) {
        for (int y = y1; y <= y2; y++) {
          tiles.add((z, x, y));
        }
      }
    }

    int downloaded = 0;
    int completed = 0;
    final client = HttpClient();
    const esriBase = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile';

    for (final (z, x, y) in tiles) {
      completed++;
      final file = File('${_cacheDir!.path}/${z}_${x}_$y.png');
      if (file.existsSync()) {
        onProgress?.call(completed, tiles.length);
        continue; // already cached
      }

      try {
        final url = '$esriBase/$z/$y/$x';
        final request = await client.getUrl(Uri.parse(url));
        request.headers.set(HttpHeaders.userAgentHeader, 'com.dalaray.voyageassistant');
        final response = await request.close();
        if (response.statusCode == 200) {
          final bytes = await consolidateHttpClientResponseBytes(response);
          await file.parent.create(recursive: true);
          await file.writeAsBytes(bytes);
          downloaded++;
        }
      } catch (_) {
        // Skip failed tiles silently
      }
      onProgress?.call(completed, tiles.length);
    }

    client.close();
    return downloaded;
  }

  /// Count how many corridor tiles are already cached.
  static Future<(int cached, int total)> getCacheStats({
    List<int> zoomLevels = const [12, 13, 14, 15, 16],
  }) async {
    if (_cacheDir == null) return (0, 0);

    int total = 0;
    int cached = 0;
    for (final z in zoomLevels) {
      final (x1, y1) = _latLonToTile(_maxLat, _minLon, z);
      final (x2, y2) = _latLonToTile(_minLat, _maxLon, z);
      for (int x = x1; x <= x2; x++) {
        for (int y = y1; y <= y2; y++) {
          total++;
          if (File('${_cacheDir!.path}/${z}_${x}_$y.png').existsSync()) {
            cached++;
          }
        }
      }
    }
    return (cached, total);
  }

  /// Convert lat/lon to tile x,y at a given zoom level.
  static (int x, int y) _latLonToTile(double lat, double lon, int zoom) {
    final n = math.pow(2, zoom);
    final x = ((lon + 180) / 360 * n).floor();
    final latRad = lat * math.pi / 180;
    final y = ((1 - math.log(math.tan(latRad) + 1 / math.cos(latRad)) / math.pi) / 2 * n).floor();
    return (x, y);
  }

  @override
  ImageProvider getImage(TileCoordinates coordinates, TileLayer options) {
    final url = getTileUrl(coordinates, options);

    if (_cacheDir == null) {
      // Fallback: no cache dir (web or init not called)
      return NetworkImage(url);
    }

    final file = File(
      '${_cacheDir!.path}/${coordinates.z}_${coordinates.x}_${coordinates.y}.png',
    );
    return _CachedTileImage(url, file);
  }
}

class _CachedTileImage extends ImageProvider<_CachedTileImage> {
  final String url;
  final File file;

  _CachedTileImage(this.url, this.file);

  @override
  ImageStreamCompleter loadImage(
    _CachedTileImage key,
    ImageDecoderCallback decode,
  ) {
    return MultiFrameImageStreamCompleter(
      codec: _load(decode),
      scale: 1.0,
    );
  }

  Future<ui.Codec> _load(ImageDecoderCallback decode) async {
    // Serve from cache if available
    if (file.existsSync()) {
      try {
        final bytes = await file.readAsBytes();
        final buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
        return decode(buffer);
      } catch (_) {
        // Corrupt cache file (e.g. partial write) — delete and re-download
        try { file.deleteSync(); } catch (_) {}
      }
    }

    // Download from network
    final client = HttpClient();
    try {
      final request = await client.getUrl(Uri.parse(url));
      request.headers.set(
        HttpHeaders.userAgentHeader,
        'com.dalaray.voyageassistant',
      );
      final response = await request.close();
      if (response.statusCode != 200) {
        throw HttpException('HTTP ${response.statusCode}');
      }
      final bytes = await consolidateHttpClientResponseBytes(response);

      // Save to cache (fire-and-forget)
      file.parent.create(recursive: true).then((_) => file.writeAsBytes(bytes));

      final buffer =
          await ui.ImmutableBuffer.fromUint8List(Uint8List.fromList(bytes));
      return decode(buffer);
    } finally {
      client.close();
    }
  }

  @override
  Future<_CachedTileImage> obtainKey(ImageConfiguration configuration) {
    return SynchronousFuture<_CachedTileImage>(this);
  }

  @override
  bool operator ==(Object other) =>
      other is _CachedTileImage && url == other.url;

  @override
  int get hashCode => url.hashCode;
}
