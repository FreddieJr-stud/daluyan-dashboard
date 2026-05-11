import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'providers/dashboard_provider.dart';
import 'models/dashboard_data.dart';
import 'services/cached_tile_provider.dart';
import 'models/voice_models.dart';
import 'services/voice_service.dart';
import 'widgets/charging_panel.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Initialize tile cache for offline map support
  await CachedTileProvider.init();

  // Load saved server URL from SharedPreferences
  final prefs = await SharedPreferences.getInstance();
  final savedUrl = prefs.getString('server_url');

  // Priority: saved URL > --dart-define > default localhost
  const envUrl = String.fromEnvironment('SERVER_URL');
  final serverUrl = savedUrl
      ?? (envUrl.isNotEmpty ? envUrl : 'http://localhost:5000');

  // Load Cloud STT API key from --dart-define (set by launcher from local_keys.env)
  const cloudSttKey = String.fromEnvironment('CLOUD_STT_KEY');

  final dashProvider = DashboardProvider(serverUrl: serverUrl);
  final voiceService = VoiceService(dashProvider);
  voiceService.init(cloudSttKey: cloudSttKey.isNotEmpty ? cloudSttKey : null);

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: dashProvider),
        ChangeNotifierProvider.value(value: voiceService),
      ],
      child: const DalarayApp(),
    ),
  );
}

// River waypoints from OpenStreetMap relation 8751702 (Pasig River Ferry route).
// Actual river geometry from Napindan (east) to Escolta (west).
// Our 9 stations are tagged; Kalawaan/San Joaquin/Quinta are pass-through.
const List<({double lat, double lon, String? station})> _riverPath = [
  // — Napindan (Pinagbuhatan) —
  (lat: 14.5359379, lon: 121.1021445, station: 'Napindan'),
  (lat: 14.5358599, lon: 121.1017740, station: null),
  (lat: 14.5372697, lon: 121.0988241, station: null),
  (lat: 14.5391390, lon: 121.0980034, station: null),
  (lat: 14.5407280, lon: 121.0961446, station: null),
  (lat: 14.5427219, lon: 121.0965443, station: null),
  (lat: 14.5451001, lon: 121.0948062, station: null),
  (lat: 14.5526914, lon: 121.0928535, station: null),
  (lat: 14.5529510, lon: 121.0920489, station: null),
  (lat: 14.5520060, lon: 121.0893130, station: null),
  (lat: 14.5532106, lon: 121.0874918, station: null),
  (lat: 14.5532028, lon: 121.0821411, station: null),
  (lat: 14.5538460, lon: 121.0808408, station: null),
  (lat: 14.5534365, lon: 121.0765940, station: null),
  (lat: 14.5546620, lon: 121.0739286, station: null),
  (lat: 14.5550764, lon: 121.0736239, station: null),
  (lat: 14.5573332, lon: 121.0672545, station: null),
  (lat: 14.5603395, lon: 121.0662997, station: null),
  (lat: 14.5612524, lon: 121.0638741, station: null),
  (lat: 14.5626448, lon: 121.0611713, station: null),
  (lat: 14.5642284, lon: 121.0595030, station: null),
  (lat: 14.5667257, lon: 121.0530710, station: null),
  (lat: 14.5683560, lon: 121.0502064, station: null),
  (lat: 14.5684062, lon: 121.0486719, station: null),
  // — Guadalupe —
  (lat: 14.5681100, lon: 121.0478946, station: 'Guadalupe'),
  (lat: 14.5689783, lon: 121.0430773, station: null),
  (lat: 14.5670395, lon: 121.0364722, station: null),
  (lat: 14.5673488, lon: 121.0339603, station: null),
  // — Hulo —
  (lat: 14.5679545, lon: 121.0336782, station: 'Hulo'),
  (lat: 14.5679866, lon: 121.0336158, station: null),
  (lat: 14.5730310, lon: 121.0274336, station: null),
  // — Valenzuela —
  (lat: 14.5739778, lon: 121.0257656, station: 'Valenzuela'),
  (lat: 14.5744081, lon: 121.0253843, station: null),
  (lat: 14.5749968, lon: 121.0247592, station: null),
  (lat: 14.5760368, lon: 121.0231134, station: null),
  (lat: 14.5794938, lon: 121.0178348, station: null),
  (lat: 14.5797947, lon: 121.0174394, station: null),
  (lat: 14.5800531, lon: 121.0172198, station: null),
  (lat: 14.5804296, lon: 121.0171431, station: null),
  (lat: 14.5808805, lon: 121.0171961, station: null),
  (lat: 14.5811553, lon: 121.0172874, station: null),
  (lat: 14.5814038, lon: 121.0174699, station: null),
  (lat: 14.5824962, lon: 121.0185242, station: null),
  (lat: 14.5836962, lon: 121.0195418, station: null),
  (lat: 14.5847201, lon: 121.0201531, station: null),
  (lat: 14.5850930, lon: 121.0202545, station: null),
  (lat: 14.5855947, lon: 121.0202579, station: null),
  (lat: 14.5859956, lon: 121.0201903, station: null),
  (lat: 14.5863259, lon: 121.0200111, station: null),
  (lat: 14.5868590, lon: 121.0195042, station: null),
  (lat: 14.5870520, lon: 121.0190582, station: null),
  // — Lambingan —
  (lat: 14.5872813, lon: 121.0184560, station: 'Lambingan'),
  (lat: 14.5870618, lon: 121.0183654, station: null),
  (lat: 14.5867589, lon: 121.0180509, station: null),
  (lat: 14.5866530, lon: 121.0177301, station: null),
  (lat: 14.5865581, lon: 121.0173279, station: null),
  (lat: 14.5864044, lon: 121.0165946, station: null),
  (lat: 14.5862278, lon: 121.0157937, station: null),
  (lat: 14.5857792, lon: 121.0144361, station: null),
  (lat: 14.5854298, lon: 121.0138269, station: null),
  (lat: 14.5850449, lon: 121.0133851, station: null),
  (lat: 14.5845076, lon: 121.0129908, station: null),
  (lat: 14.5836094, lon: 121.0123068, station: null),
  (lat: 14.5832226, lon: 121.0120869, station: null),
  (lat: 14.5829319, lon: 121.0119554, station: null),
  // — Sta Ana —
  (lat: 14.5827238, lon: 121.0119451, station: 'Sta Ana'),
  (lat: 14.5827009, lon: 121.0117194, station: null),
  (lat: 14.5826386, lon: 121.0114914, station: null),
  (lat: 14.5823427, lon: 121.0109496, station: null),
  (lat: 14.5821363, lon: 121.0103770, station: null),
  (lat: 14.5820844, lon: 121.0100162, station: null),
  (lat: 14.5820850, lon: 121.0096693, station: null),
  (lat: 14.5821661, lon: 121.0091016, station: null),
  (lat: 14.5823647, lon: 121.0085839, station: null),
  (lat: 14.5828141, lon: 121.0080478, station: null),
  (lat: 14.5832655, lon: 121.0077593, station: null),
  (lat: 14.5837825, lon: 121.0074774, station: null),
  (lat: 14.5845401, lon: 121.0072023, station: null),
  (lat: 14.5850616, lon: 121.0070779, station: null),
  (lat: 14.5854322, lon: 121.0070675, station: null),
  (lat: 14.5859946, lon: 121.0071307, station: null),
  (lat: 14.5864162, lon: 121.0072377, station: null),
  (lat: 14.5869669, lon: 121.0075987, station: null),
  (lat: 14.5874215, lon: 121.0081191, station: null),
  (lat: 14.5876744, lon: 121.0086966, station: null),
  (lat: 14.5877486, lon: 121.0090417, station: null),
  (lat: 14.5879709, lon: 121.0101468, station: null),
  (lat: 14.5881018, lon: 121.0105624, station: null),
  (lat: 14.5883634, lon: 121.0112755, station: null),
  (lat: 14.5889021, lon: 121.0123242, station: null),
  (lat: 14.5893347, lon: 121.0130767, station: null),
  (lat: 14.5899076, lon: 121.0138971, station: null),
  (lat: 14.5900024, lon: 121.0140105, station: null),
  (lat: 14.5909293, lon: 121.0154007, station: null),
  (lat: 14.5913994, lon: 121.0159120, station: null),
  (lat: 14.5917221, lon: 121.0160505, station: null),
  (lat: 14.5920852, lon: 121.0160768, station: null),
  (lat: 14.5923830, lon: 121.0160056, station: null),
  (lat: 14.5926934, lon: 121.0158038, station: null),
  (lat: 14.5928554, lon: 121.0156006, station: null),
  (lat: 14.5933486, lon: 121.0147584, station: null),
  (lat: 14.5939300, lon: 121.0132295, station: null),
  (lat: 14.5946724, lon: 121.0117971, station: null),
  (lat: 14.5952125, lon: 121.0111276, station: null),
  (lat: 14.5956302, lon: 121.0108497, station: null),
  // — PUP —
  (lat: 14.5960355, lon: 121.0107013, station: 'PUP'),
  (lat: 14.5960455, lon: 121.0100521, station: null),
  (lat: 14.5961436, lon: 121.0093864, station: null),
  (lat: 14.5965003, lon: 121.0080680, station: null),
  (lat: 14.5971576, lon: 121.0060760, station: null),
  (lat: 14.5972317, lon: 121.0054457, station: null),
  (lat: 14.5971202, lon: 121.0046192, station: null),
  (lat: 14.5969115, lon: 121.0039119, station: null),
  (lat: 14.5965958, lon: 121.0032329, station: null),
  (lat: 14.5959877, lon: 121.0022691, station: null),
  (lat: 14.5958586, lon: 121.0019401, station: null),
  (lat: 14.5958411, lon: 121.0016260, station: null),
  (lat: 14.5958903, lon: 121.0010451, station: null),
  (lat: 14.5961213, lon: 121.0003572, station: null),
  (lat: 14.5964385, lon: 120.9996164, station: null),
  (lat: 14.5965576, lon: 120.9993010, station: null),
  (lat: 14.5966309, lon: 120.9988259, station: null),
  (lat: 14.5966381, lon: 120.9986337, station: null),
  (lat: 14.5965727, lon: 120.9982134, station: null),
  (lat: 14.5964412, lon: 120.9979303, station: null),
  (lat: 14.5962782, lon: 120.9976409, station: null),
  (lat: 14.5951241, lon: 120.9962527, station: null),
  (lat: 14.5947245, lon: 120.9958781, station: null),
  (lat: 14.5935381, lon: 120.9951407, station: null),
  (lat: 14.5927475, lon: 120.9946203, station: null),
  (lat: 14.5922974, lon: 120.9942234, station: null),
  (lat: 14.5919592, lon: 120.9938664, station: null),
  (lat: 14.5915576, lon: 120.9932739, station: null),
  (lat: 14.5913396, lon: 120.9926677, station: null),
  (lat: 14.5912357, lon: 120.9921446, station: null),
  (lat: 14.5912150, lon: 120.9916458, station: null),
  (lat: 14.5912917, lon: 120.9905392, station: null),
  (lat: 14.5913581, lon: 120.9896298, station: null),
  (lat: 14.5913896, lon: 120.9887017, station: null),
  (lat: 14.5913891, lon: 120.9876640, station: null),
  (lat: 14.5914236, lon: 120.9870050, station: null),
  (lat: 14.5915954, lon: 120.9862286, station: null),
  (lat: 14.5918431, lon: 120.9855545, station: null),
  (lat: 14.5924012, lon: 120.9847069, station: null),
  (lat: 14.5931649, lon: 120.9838223, station: null),
  (lat: 14.5937273, lon: 120.9833497, station: null),
  (lat: 14.5945288, lon: 120.9827962, station: null),
  (lat: 14.5952189, lon: 120.9822895, station: null),
  (lat: 14.5952869, lon: 120.9822490, station: null),
  (lat: 14.5954166, lon: 120.9822001, station: null),
  (lat: 14.5959362, lon: 120.9822120, station: null),
  // — Quinta —
  (lat: 14.5957803, lon: 120.9814485, station: 'Quinta'),
  (lat: 14.5959182, lon: 120.9815919, station: null),
  (lat: 14.5960520, lon: 120.9816156, station: null),
  (lat: 14.5961707, lon: 120.9815969, station: null),
  (lat: 14.5962570, lon: 120.9815352, station: null),
  (lat: 14.5963157, lon: 120.9814643, station: null),
  (lat: 14.5968008, lon: 120.9806299, station: null),
  (lat: 14.5969237, lon: 120.9802064, station: null),
  (lat: 14.5969391, lon: 120.9798966, station: null),
  (lat: 14.5969000, lon: 120.9795901, station: null),
  (lat: 14.5967929, lon: 120.9792729, station: null),
  (lat: 14.5964359, lon: 120.9783990, station: null),
  (lat: 14.5963561, lon: 120.9781467, station: null),
  (lat: 14.5963212, lon: 120.9779113, station: null),
  // — Escolta —
  (lat: 14.5963832, lon: 120.9775262, station: 'Escolta'),
];

// ==================== APP ROOT ====================
class DalarayApp extends StatelessWidget {
  const DalarayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'M/B Dalaray Voyage Assistant',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFFE47400)),
        useMaterial3: true,
      ),
      home: const VoyageDashboard(),
    );
  }
}

// ==================== MAIN DASHBOARD ====================
class VoyageDashboard extends StatefulWidget {
  const VoyageDashboard({super.key});

  @override
  State<VoyageDashboard> createState() => _VoyageDashboardState();
}

enum DashboardView { map, speedTable, routeSelect }

class _VoyageDashboardState extends State<VoyageDashboard>
    with TickerProviderStateMixin {
  // Stations currently out of service
  static const _closedStations = {'Sta Ana', 'Valenzuela'};

  DashboardView _currentView = DashboardView.map;
  int _dockedRouteIndex = 0;
  String? _speedTableDeparture;
  String? _speedTableDestination;
  bool _cameFromRouteSelect = false; // tracks if speed table was opened from route select
  int _selectedDestinationIndex = -1; // index in sorted stations for route select
  bool _tripDirectionForward = true; // for N/B key auto-reverse navigation
  bool _showDebugPanel = false; // toggle floating debug controls
  bool _preCaching = false; // tile pre-cache in progress
  String _preCacheStatus = ''; // progress text
  final ScrollController _routeScrollController = ScrollController();
  final MapController _mapController = MapController();
  final GlobalKey _overlayKeyStatusBox = GlobalKey();
  String? _lastFitKey; // tracks last fitted station set to avoid redundant calls
  bool _userOverrideMap = false; // true when user has manually panned/zoomed
  bool _terrainMap = false; // default to cached satellite (offline-capable)
  Timer? _overrideResetTimer;
  static const _mapOverrideResetDuration = Duration(seconds: 15);
  final FocusNode _focusNode = FocusNode();
  String? _lastNavState; // for auto-detecting movement
  late final AnimationController _bobController;
  late final Animation<double> _bobAnimation;
  late final AnimationController _pulseController;
  late final Animation<double> _pulseAnimation;
  late final AnimationController _waveController;

  @override
  void initState() {
    super.initState();
    _bobController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2000),
    )..repeat(reverse: true);
    _bobAnimation = Tween<double>(begin: -6, end: 6).animate(
      CurvedAnimation(parent: _bobController, curve: Curves.easeInOut),
    );
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1500),
    )..repeat(reverse: true);
    _pulseAnimation = Tween<double>(begin: 0.25, end: 0.7).animate(
      CurvedAnimation(parent: _pulseController, curve: Curves.easeInOut),
    );
    _waveController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 3000),
    )..repeat();
    // Start with only map-relevant animations running
    _syncAnimationsToView();
  }

  /// Pause/resume animations based on which view is active to reduce GPU load
  void _syncAnimationsToView() {
    if (_currentView == DashboardView.map) {
      // Map: pulse needed (ferry marker), wave+bob not visible
      if (!_pulseController.isAnimating) _pulseController.repeat(reverse: true);
      if (_waveController.isAnimating) _waveController.stop();
      if (_bobController.isAnimating) _bobController.stop();
    } else {
      // Speed table / route select: wave+bob visible, pulse not needed
      if (_pulseController.isAnimating) _pulseController.stop();
      if (!_waveController.isAnimating) _waveController.repeat();
      if (!_bobController.isAnimating) _bobController.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    _overrideResetTimer?.cancel();
    _bobController.dispose();
    _pulseController.dispose();
    _waveController.dispose();
    _focusNode.dispose();
    _routeScrollController.dispose();
    super.dispose();
  }

  // DEBUG: handle key press 1-9 to simulate docking at that station
  void _handleKey(KeyEvent event) {
    if (event is! KeyDownEvent) return;
    final key = event.logicalKey;
    final keyMap = {
      LogicalKeyboardKey.digit1: 0,
      LogicalKeyboardKey.digit2: 1,
      LogicalKeyboardKey.digit3: 2,
      LogicalKeyboardKey.digit4: 3,
      LogicalKeyboardKey.digit5: 4,
      LogicalKeyboardKey.digit6: 5,
      LogicalKeyboardKey.digit7: 6,
      LogicalKeyboardKey.digit8: 7,
      LogicalKeyboardKey.digit9: 8,
    };
    final idx = keyMap[key];
    if (idx != null) {
      _lastFitKey = null; // force re-fit
      context.read<DashboardProvider>().simulateDock(idx);
      // Auto-open route select when docking via debug key
      final data = context.read<DashboardProvider>().data;
      _initRouteSelectForStation(data);
      setState(() => _currentView = DashboardView.routeSelect);
    }
    // Press 'R' to toggle route select view manually
    if (key == LogicalKeyboardKey.keyR) {
      final data = context.read<DashboardProvider>().data;
      if (data.isDocked) {
        _initRouteSelectForStation(data);
        setState(() => _currentView = DashboardView.routeSelect);
      }
    }
    // Press 'T' to simulate trip from current station to selected destination
    if (key == LogicalKeyboardKey.keyT) {
      final provider = context.read<DashboardProvider>();
      final data = provider.data;
      if (data.isDocked && data.stations.isNotEmpty) {
        final sorted = List<StationInfo>.from(data.stations)
          ..sort((a, b) => a.order.compareTo(b.order));
        final currentIdx = sorted.indexWhere((s) => s.name == data.currentStation);
        if (currentIdx >= 0 && _selectedDestinationIndex >= 0 && _selectedDestinationIndex < sorted.length) {
          final fromOrder = sorted[currentIdx].order;
          final toOrder = sorted[_selectedDestinationIndex].order;
          _lastFitKey = null;
          provider.simulateTrip(
            fromStationIndex: fromOrder,
            toStationIndex: toOrder,
            waypoints: _riverPath,
          );
        }
      }
    }
    // Press 'S' to stop trip simulation
    if (key == LogicalKeyboardKey.keyS) {
      context.read<DashboardProvider>().stopTripSimulation();
    }
    // N = trip to next station in sequence (auto-reverses at endpoints)
    if (key == LogicalKeyboardKey.keyN) {
      final provider = context.read<DashboardProvider>();
      final data = provider.data;
      if (data.isDocked && data.stations.isNotEmpty) {
        final sorted = List<StationInfo>.from(data.stations)
          ..sort((a, b) => a.order.compareTo(b.order));
        final currentIdx = sorted.indexWhere((s) => s.name == data.currentStation);
        if (currentIdx >= 0) {
          int nextIdx;
          if (_tripDirectionForward) {
            nextIdx = currentIdx + 1;
            if (nextIdx >= sorted.length) {
              _tripDirectionForward = false;
              nextIdx = currentIdx - 1;
            }
          } else {
            nextIdx = currentIdx - 1;
            if (nextIdx < 0) {
              _tripDirectionForward = true;
              nextIdx = currentIdx + 1;
            }
          }
          nextIdx = nextIdx.clamp(0, sorted.length - 1);
          _lastFitKey = null;
          provider.simulateTrip(
            fromStationIndex: sorted[currentIdx].order,
            toStationIndex: sorted[nextIdx].order,
            waypoints: _riverPath,
          );
        }
      }
    }
    // B = trip to previous station in sequence
    if (key == LogicalKeyboardKey.keyB) {
      final provider = context.read<DashboardProvider>();
      final data = provider.data;
      if (data.isDocked && data.stations.isNotEmpty) {
        final sorted = List<StationInfo>.from(data.stations)
          ..sort((a, b) => a.order.compareTo(b.order));
        final currentIdx = sorted.indexWhere((s) => s.name == data.currentStation);
        if (currentIdx >= 0) {
          int prevIdx;
          if (!_tripDirectionForward) {
            prevIdx = currentIdx + 1;
            if (prevIdx >= sorted.length) {
              _tripDirectionForward = true;
              prevIdx = currentIdx - 1;
            }
          } else {
            prevIdx = currentIdx - 1;
            if (prevIdx < 0) {
              _tripDirectionForward = false;
              prevIdx = currentIdx + 1;
            }
          }
          prevIdx = prevIdx.clamp(0, sorted.length - 1);
          _lastFitKey = null;
          provider.simulateTrip(
            fromStationIndex: sorted[currentIdx].order,
            toStationIndex: sorted[prevIdx].order,
            waypoints: _riverPath,
          );
        }
      }
    }
  }

  void _showSpeedTable(String departure, String destination) {
    _speedTableDeparture = departure;
    _speedTableDestination = destination;
    _cameFromRouteSelect = false;
    final d = context.read<DashboardProvider>().data;
    // During transit, reuse cached predictions — no re-inference needed
    final hasCached = d.speedPredictions.isNotEmpty &&
        d.speedPredDeparture == departure &&
        d.speedPredDestination == destination;
    if (!hasCached || d.isDocked) {
      context.read<DashboardProvider>().requestSpeedPrediction(
            departure: departure,
            destination: destination,
          );
    }
    setState(() { _currentView = DashboardView.speedTable; _syncAnimationsToView(); });
  }

  void _showSpeedTableFromRouteSelect(String departure, String destination) {
    _speedTableDeparture = departure;
    _speedTableDestination = destination;
    _cameFromRouteSelect = true;
    // Route select is only available when docked — always request fresh predictions
    context.read<DashboardProvider>().requestSpeedPrediction(
          departure: departure,
          destination: destination,
        );
    setState(() { _currentView = DashboardView.speedTable; _syncAnimationsToView(); });
  }

  void _backToMap() {
    setState(() { _currentView = DashboardView.map; _syncAnimationsToView(); });
  }

  void _backToRouteSelect() {
    setState(() { _currentView = DashboardView.routeSelect; _syncAnimationsToView(); });
  }

  @override
  Widget build(BuildContext context) {
    final d = context.watch<DashboardProvider>().data;

    // Auto-detect movement: if ferry starts moving while on route select, switch to map
    if (_lastNavState != d.navState) {
      if (d.isMoving && _currentView == DashboardView.routeSelect) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          setState(() => _currentView = DashboardView.map);
        });
      }
      // Auto-show route select when docked (if currently on map and just docked)
      if (d.isDocked && _lastNavState != null && _lastNavState != 'DOCKED' && _currentView == DashboardView.map) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          _initRouteSelectForStation(d);
          setState(() => _currentView = DashboardView.routeSelect);
        });
      }
      _lastNavState = d.navState;
    }

    Widget mainContent;
    switch (_currentView) {
      case DashboardView.map:
        mainContent = _buildFullScreenMap(context);
        break;
      case DashboardView.speedTable:
        mainContent = _buildSpeedTableView(context);
        break;
      case DashboardView.routeSelect:
        mainContent = _buildRouteSelectView(context);
        break;
    }

    return KeyboardListener(
      focusNode: _focusNode,
      autofocus: true,
      onKeyEvent: _handleKey,
      child: Scaffold(
        body: Stack(
          children: [
            mainContent,
            if (d.isCharging)
              Positioned(
                bottom: 80,
                left: 16,
                child: const ChargingPanel(),
              ),
            if (_currentView == DashboardView.map) _buildFloatingMicButton(),
            Positioned(
              bottom: 12,
              right: 12,
              child: GestureDetector(
                onTap: () => _showSettingsDialog(),
                child: Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: const Icon(Icons.settings, color: Colors.white, size: 20),
                ),
              ),
            ),
            if (_isDevMode) _buildDebugToggle(),
            if (_isDevMode && _showDebugPanel) _buildDebugPanel(d),
          ],
        ),
      ),
    );
  }

  /// Debug/settings controls only show in dev mode (localhost/127.0.0.1)
  /// or when launched with --debug-panel flag.
  bool get _isDevMode {
    const forceDebug = bool.fromEnvironment('SHOW_DEBUG');
    if (forceDebug) return true;
    final url = context.read<DashboardProvider>().currentServerUrl;
    return url.contains('localhost') || url.contains('127.0.0.1');
  }

  // ── Floating PTT mic button (always visible) ──
  Widget _buildFloatingMicButton() {
    final voice = context.read<VoiceService>();
    return Positioned(
      bottom: 20,
      right: 140,
      child: ListenableBuilder(
        listenable: voice,
        builder: (context, _) {
          final isListening = voice.state == VoiceState.listening;
          final isProcessing = voice.state == VoiceState.processing;
          final isSpeaking = voice.state == VoiceState.speaking;

          final Color micColor;
          final IconData micIcon;
          final String label;
          if (isListening) {
            micColor = const Color(0xFFEF4444); // red
            micIcon = Icons.mic;
            label = 'Listening...';
          } else if (isProcessing) {
            micColor = const Color(0xFFF59E0B); // amber
            micIcon = Icons.hourglass_top;
            label = 'Processing...';
          } else if (isSpeaking) {
            micColor = const Color(0xFF34D399); // green
            micIcon = Icons.volume_up;
            label = 'Speaking...';
          } else {
            micColor = const Color(0xFF3B82F6); // blue
            micIcon = Icons.mic;
            label = 'Tap to speak';
          }

          return GestureDetector(
            onTap: () {
              if (isListening) {
                voice.stopListening();
              } else if (!isProcessing && !isSpeaking) {
                voice.startListening();
              }
            },
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 96,
                  height: 96,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    gradient: LinearGradient(
                      begin: Alignment.topLeft,
                      end: Alignment.bottomRight,
                      colors: [micColor, micColor.withValues(alpha: 0.7)],
                    ),
                    border: Border.all(
                      color: Colors.white.withValues(alpha: 0.3),
                      width: 3,
                    ),
                    boxShadow: [
                      BoxShadow(
                        color: micColor.withValues(alpha: 0.5),
                        blurRadius: 16,
                        spreadRadius: 3,
                      ),
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.3),
                        blurRadius: 8,
                        offset: const Offset(0, 4),
                      ),
                    ],
                  ),
                  child: Icon(micIcon, color: Colors.white, size: 44),
                ),
                const SizedBox(height: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.6),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Text(label, style: const TextStyle(
                    color: Colors.white, fontSize: 11, fontWeight: FontWeight.w500,
                  )),
                ),
              ],
            ),
          );
        },
      ),
    );
  }

  // ── Debug toolbar (dev mode only, stacked vertically on right side) ──
  Widget _buildDebugToggle() {
    return Positioned(
      bottom: 12,
      right: 12,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Map style toggle — only visible on map view
          if (_currentView == DashboardView.map) ...[
            GestureDetector(
              onTap: () => setState(() => _terrainMap = !_terrainMap),
              child: Container(
                width: 36,
                height: 36,
                decoration: BoxDecoration(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Icon(
                  _terrainMap ? Icons.map : Icons.satellite_alt,
                  color: Colors.white,
                  size: 20,
                ),
              ),
            ),
            const SizedBox(height: 8),
          ],
          GestureDetector(
            onTap: () => _showSettingsDialog(),
            child: Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: Colors.black54,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.settings, color: Colors.white, size: 20),
            ),
          ),
          const SizedBox(height: 8),
          GestureDetector(
            onTap: () => setState(() => _showDebugPanel = !_showDebugPanel),
            child: Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: _showDebugPanel ? Colors.orange : Colors.black54,
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.bug_report, color: Colors.white, size: 20),
            ),
          ),
        ],
      ),
    );
  }

  void _showSettingsDialog() {
    final provider = context.read<DashboardProvider>();
    final controller = TextEditingController(text: provider.currentServerUrl);

    // Compute the built-in default (--dart-define or localhost)
    const envUrl = String.fromEnvironment('SERVER_URL');
    final defaultUrl = envUrl.isNotEmpty ? envUrl : 'http://localhost:5000';

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Settings'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Backend URL:', style: TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                hintText: 'http://CONFIGURE_SERVER_HOST:5000',
                border: OutlineInputBorder(),
                isDense: true,
              ),
            ),
            const SizedBox(height: 4),
            Text('Default: $defaultUrl',
                style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                icon: const Icon(Icons.usb),
                label: const Text('Switch to USB (ADB Backup)'),
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.blue.shade800,
                  side: BorderSide(color: Colors.blue.shade300),
                  padding: const EdgeInsets.symmetric(vertical: 12),
                ),
                onPressed: () {
                  const adbUrl = 'http://127.0.0.1:5000';
                  provider.changeServerUrl(adbUrl);
                  controller.text = adbUrl;
                  if (ctx.mounted) Navigator.of(ctx).pop();
                },
              ),
            ),
            const SizedBox(height: 4),
            Text('Use when tablet is connected via USB but WiFi is unavailable',
                style: TextStyle(fontSize: 11, color: Colors.grey.shade600)),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () async {
              final prefs = await SharedPreferences.getInstance();
              await prefs.remove('server_url');
              provider.changeServerUrl(defaultUrl);
              controller.text = defaultUrl;
              if (ctx.mounted) Navigator.of(ctx).pop();
            },
            child: const Text('Reset to Default'),
          ),
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final newUrl = controller.text.trim();
              if (newUrl.isNotEmpty) {
                provider.changeServerUrl(newUrl);
              }
              Navigator.of(ctx).pop();
            },
            child: const Text('Save & Reconnect'),
          ),
        ],
      ),
    );
  }

  // ── Floating debug panel with simulation controls ──
  Widget _buildDebugPanel(DashboardData d) {
    final provider = context.read<DashboardProvider>();
    final sorted = d.stations.isNotEmpty
        ? (List<StationInfo>.from(d.stations)..sort((a, b) => a.order.compareTo(b.order)))
        : <StationInfo>[];
    final currentIdx = sorted.indexWhere((s) => s.name == d.currentStation);

    Widget btn(String label, IconData icon, VoidCallback? onTap, {Color? color}) {
      return GestureDetector(
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
          decoration: BoxDecoration(
            color: (onTap != null ? (color ?? Colors.blueGrey.shade700) : Colors.grey.shade600),
            borderRadius: BorderRadius.circular(6),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, color: Colors.white, size: 16),
              const SizedBox(width: 4),
              Text(label, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.bold)),
            ],
          ),
        ),
      );
    }

    return Positioned(
      bottom: 54,
      right: 12,
      child: Container(
        width: 240,
        constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height - 80),
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: Colors.black87,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: Colors.orange, width: 1.5),
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // ── SOC COMPARISON ──
              _buildSocComparison(d),
              const Divider(color: Colors.grey, height: 12),

              // ── REPLAY CONTROLS ──
              _buildReplayControls(d, provider, btn),
              const Divider(color: Colors.grey, height: 12),

              // ── SIM CONTROLS ──
              const Text('SIM CONTROLS', style: TextStyle(color: Colors.orange, fontSize: 11, fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  btn('Next', Icons.skip_next, d.isDocked && sorted.isNotEmpty ? () {
                    if (currentIdx < 0) return;
                    int nextIdx;
                    if (_tripDirectionForward) {
                      nextIdx = currentIdx + 1;
                      if (nextIdx >= sorted.length) { _tripDirectionForward = false; nextIdx = currentIdx - 1; }
                    } else {
                      nextIdx = currentIdx - 1;
                      if (nextIdx < 0) { _tripDirectionForward = true; nextIdx = currentIdx + 1; }
                    }
                    nextIdx = nextIdx.clamp(0, sorted.length - 1);
                    _lastFitKey = null;
                    provider.simulateTrip(
                      fromStationIndex: sorted[currentIdx].order,
                      toStationIndex: sorted[nextIdx].order,
                      waypoints: _riverPath,
                    );
                  } : null, color: Colors.green.shade700),
                  btn('Prev', Icons.skip_previous, d.isDocked && sorted.isNotEmpty ? () {
                    if (currentIdx < 0) return;
                    int prevIdx;
                    if (!_tripDirectionForward) {
                      prevIdx = currentIdx + 1;
                      if (prevIdx >= sorted.length) { _tripDirectionForward = true; prevIdx = currentIdx - 1; }
                    } else {
                      prevIdx = currentIdx - 1;
                      if (prevIdx < 0) { _tripDirectionForward = false; prevIdx = currentIdx + 1; }
                    }
                    prevIdx = prevIdx.clamp(0, sorted.length - 1);
                    _lastFitKey = null;
                    provider.simulateTrip(
                      fromStationIndex: sorted[currentIdx].order,
                      toStationIndex: sorted[prevIdx].order,
                      waypoints: _riverPath,
                    );
                  } : null, color: Colors.green.shade700),
                  btn('Stop', Icons.stop, d.isMoving ? () {
                    provider.stopTripSimulation();
                  } : null, color: Colors.red.shade700),
                ],
              ),
              const SizedBox(height: 6),
              btn('Route Select', Icons.route, d.isDocked ? () {
                _initRouteSelectForStation(provider.data);
                setState(() => _currentView = DashboardView.routeSelect);
              } : null, color: Colors.purple.shade700),
              const Divider(color: Colors.grey, height: 12),

              // ── TILE PRE-CACHE ──
              const Text('OFFLINE TILES', style: TextStyle(color: Colors.orange, fontSize: 11, fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              if (_preCacheStatus.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(_preCacheStatus, style: const TextStyle(color: Colors.white70, fontSize: 10)),
                ),
              btn(
                _preCaching ? 'Caching...' : 'Pre-cache Map',
                _preCaching ? Icons.hourglass_top : Icons.download,
                _preCaching ? null : () => _startPreCache(),
                color: Colors.teal.shade700,
              ),
              const Divider(color: Colors.grey, height: 12),

              // ── CONNECTION STATUS ──
              _buildDebugConnectionStatus(),
              const Divider(color: Colors.grey, height: 12),

              // ── CONVERSATION LOG ──
              _buildDebugConversationLog(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildDebugConnectionStatus() {
    final voice = context.read<VoiceService>();
    return ListenableBuilder(
      listenable: voice,
      builder: (context, _) {
        Widget statusRow(String label, bool available) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 2),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(label, style: const TextStyle(color: Colors.white70, fontSize: 10)),
                Text(
                  available ? 'OK' : '—',
                  style: TextStyle(
                    color: available ? const Color(0xFF34D399) : const Color(0xFFEF4444),
                    fontSize: 10,
                  ),
                ),
              ],
            ),
          );
        }

        final tierLabel = switch (voice.activeSttTier) {
          SttTier.cloud => 'Cloud',
          SttTier.rpi5 => 'Vosk',
          SttTier.platform => 'Platform',
          SttTier.none => 'None',
        };

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('STT STATUS', style: TextStyle(color: Colors.orange, fontSize: 11, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            statusRow('Cloud STT', voice.cloudAvailable),
            statusRow('Backend Vosk', voice.rpi5Available),
            statusRow('Platform STT', voice.platformAvailable),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                const Text('Active', style: TextStyle(color: Colors.white70, fontSize: 10)),
                Text(tierLabel, style: const TextStyle(color: Color(0xFF60A5FA), fontSize: 10)),
              ],
            ),
          ],
        );
      },
    );
  }

  Widget _buildDebugConversationLog() {
    final voice = context.read<VoiceService>();
    return ListenableBuilder(
      listenable: voice,
      builder: (context, _) {
        final entries = voice.log.reversed.take(10).toList();
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('VOICE LOG', style: TextStyle(color: Colors.orange, fontSize: 11, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            if (entries.isEmpty)
              const Text('No conversations yet.', style: TextStyle(color: Colors.white54, fontSize: 10))
            else
              ...entries.map((e) => Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      e.speaker == Speaker.crew ? 'C: ' : 'D: ',
                      style: TextStyle(
                        color: e.speaker == Speaker.crew
                            ? const Color(0xFF94A3B8)
                            : const Color(0xFF60A5FA),
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    Expanded(
                      child: Text(
                        e.text,
                        style: const TextStyle(color: Colors.white70, fontSize: 10),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              )),
          ],
        );
      },
    );
  }

  // ── Tile pre-cache action ──
  Future<void> _startPreCache() async {
    setState(() { _preCaching = true; _preCacheStatus = 'Checking cache...'; });

    final (cached, total) = await CachedTileProvider.getCacheStats();
    if (cached == total) {
      setState(() { _preCaching = false; _preCacheStatus = 'All $total tiles already cached!'; });
      return;
    }

    setState(() => _preCacheStatus = 'Downloading ${total - cached} tiles...');

    final downloaded = await CachedTileProvider.preCachePasigCorridor(
      onProgress: (completed, total) {
        if (completed % 20 == 0 || completed == total) {
          setState(() => _preCacheStatus = 'Caching: $completed / $total tiles');
        }
      },
    );

    final (newCached, newTotal) = await CachedTileProvider.getCacheStats();
    setState(() {
      _preCaching = false;
      _preCacheStatus = 'Done! $downloaded new tiles downloaded ($newCached/$newTotal cached)';
    });
  }

  // ── SOC Comparison Widget ──
  Widget _buildSocComparison(DashboardData d) {
    final actualSoc = d.soc;
    final pred1b = d.realtimePredictedSoc;
    // Find 1A prediction for current route if available
    String? pred1a;
    if (d.autoPredictions.isNotEmpty && d.nextStation != null) {
      final match = d.autoPredictions.where((p) => p.destination == d.nextStation);
      if (match.isNotEmpty) {
        pred1a = match.first.predictedSoc;
      }
    }
    final delta1b = pred1b != null && actualSoc != null
        ? (pred1b - actualSoc).toStringAsFixed(1)
        : null;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('SOC COMPARISON', style: TextStyle(color: Colors.cyan, fontSize: 11, fontWeight: FontWeight.bold)),
        const SizedBox(height: 4),
        _socRow('Actual SOC', actualSoc != null ? '$actualSoc%' : '--', Colors.white),
        if (d.isMoving || d.isArriving) ...[
          _socRow('1B Pred Arrival',
            pred1b != null ? '${pred1b.toStringAsFixed(1)}%' : 'Calculating...',
            pred1b != null ? Colors.lightBlueAccent : Colors.grey.shade500),
          _socRow('\u0394 1B',
            delta1b != null ? '${delta1b}%' : 'Calculating...',
            delta1b != null
              ? (double.parse(delta1b).abs() > 2 ? Colors.redAccent : Colors.greenAccent)
              : Colors.grey.shade500),
        ],
        if (pred1a != null)
          _socRow('1A Pred', '$pred1a%', Colors.amberAccent),
        if (!d.isMoving && !d.isArriving && pred1b == null && pred1a == null)
          Text('Docked — no active predictions', style: TextStyle(color: Colors.grey.shade500, fontSize: 9)),
      ],
    );
  }

  Widget _socRow(String label, String value, Color valueColor) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: TextStyle(color: Colors.grey.shade300, fontSize: 10)),
          Text(value, style: TextStyle(color: valueColor, fontSize: 11, fontWeight: FontWeight.bold)),
        ],
      ),
    );
  }

  // ── Replay Controls Widget ──
  Widget _buildReplayControls(DashboardData d, DashboardProvider provider,
      Widget Function(String, IconData, VoidCallback?, {Color? color}) btn) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text('REPLAY', style: TextStyle(color: Colors.orange, fontSize: 11, fontWeight: FontWeight.bold)),
            // Fetch dates + segments
            GestureDetector(
              onTap: () {
                provider.fetchReplayDates();
                provider.fetchReplaySegments();
              },
              child: Icon(Icons.refresh, color: Colors.grey.shade400, size: 16),
            ),
          ],
        ),
        const SizedBox(height: 4),

        // Date picker dropdown
        Row(
          children: [
            Text('Date: ', style: TextStyle(color: Colors.grey.shade300, fontSize: 10)),
            const SizedBox(width: 4),
            Expanded(
              child: Container(
                height: 24,
                padding: const EdgeInsets.symmetric(horizontal: 6),
                decoration: BoxDecoration(
                  color: Colors.blueGrey.shade700,
                  borderRadius: BorderRadius.circular(4),
                ),
                child: d.replayAvailableDates.isEmpty
                    ? GestureDetector(
                        onTap: () => provider.fetchReplayDates(),
                        child: Center(
                          child: Text(
                            d.replayCurrentDate.isNotEmpty ? d.replayCurrentDate : 'Load dates...',
                            style: const TextStyle(color: Colors.white, fontSize: 10),
                          ),
                        ),
                      )
                    : DropdownButtonHideUnderline(
                        child: DropdownButton<String>(
                          value: d.replayAvailableDates.contains(d.replayCurrentDate)
                              ? d.replayCurrentDate
                              : d.replayAvailableDates.first,
                          isExpanded: true,
                          isDense: true,
                          dropdownColor: const Color(0xFF263238),
                          style: const TextStyle(color: Colors.white, fontSize: 10),
                          icon: const Icon(Icons.arrow_drop_down, color: Colors.orange, size: 16),
                          menuMaxHeight: 250,
                          items: d.replayAvailableDates.map((date) {
                            return DropdownMenuItem<String>(
                              value: date,
                              child: Text(date, style: const TextStyle(fontSize: 10)),
                            );
                          }).toList(),
                          onChanged: d.replayPlaying
                              ? null
                              : (date) {
                                  if (date != null && date != d.replayCurrentDate) {
                                    provider.changeReplayDate(date);
                                  }
                                },
                        ),
                      ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 4),

        // Speed buttons
        Row(
          children: [
            Text('Speed: ', style: TextStyle(color: Colors.grey.shade300, fontSize: 10)),
            const SizedBox(width: 4),
            for (final spd in [1, 5, 10])
              Padding(
                padding: const EdgeInsets.only(right: 4),
                child: GestureDetector(
                  onTap: () => provider.setReplaySpeed(spd),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                    decoration: BoxDecoration(
                      color: d.replaySpeedMultiplier == spd ? Colors.orange : Colors.blueGrey.shade700,
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text('${spd}x',
                      style: TextStyle(
                        color: Colors.white, fontSize: 10,
                        fontWeight: d.replaySpeedMultiplier == spd ? FontWeight.bold : FontWeight.normal,
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
        const SizedBox(height: 4),

        // Play/Stop + Full Day
        Wrap(
          spacing: 4,
          runSpacing: 4,
          children: [
            btn(d.replayPlaying ? 'Stop' : 'Play', d.replayPlaying ? Icons.stop : Icons.play_arrow,
              d.replayPlaying
                ? () => provider.stopReplay()
                : null,
              color: d.replayPlaying ? Colors.red.shade700 : Colors.grey.shade600,
            ),
            btn('Full Day', Icons.calendar_today, !d.replayPlaying ? () => provider.startReplayFullDay() : null,
              color: Colors.teal.shade700),
          ],
        ),

        // Progress bar
        if (d.replayPlaying || d.replayProgressPct > 0) ...[
          const SizedBox(height: 4),
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: d.replayProgressPct / 100,
                    minHeight: 6,
                    backgroundColor: Colors.grey.shade800,
                    valueColor: AlwaysStoppedAnimation(Colors.orange.shade400),
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Text('${d.replayProgressPct.toStringAsFixed(0)}%',
                style: const TextStyle(color: Colors.white, fontSize: 9)),
            ],
          ),
          if (d.replayCurrentSegment != null)
            Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                '${d.replayCurrentSegment!['departure_station']} \u2192 ${d.replayCurrentSegment!['arrival_station']}',
                style: TextStyle(color: Colors.grey.shade400, fontSize: 9),
                overflow: TextOverflow.ellipsis,
              ),
            ),
        ],
        const SizedBox(height: 4),

        // Segment list
        if (d.replaySegments.isNotEmpty) ...[
          const Text('SEGMENTS', style: TextStyle(color: Colors.orange, fontSize: 10, fontWeight: FontWeight.bold)),
          const SizedBox(height: 3),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 120),
            child: ListView.builder(
              shrinkWrap: true,
              itemCount: d.replaySegments.length,
              itemBuilder: (ctx, i) {
                final seg = d.replaySegments[i];
                final segId = seg['segment_id'] ?? '';
                final dep = seg['departure_station'] ?? '?';
                final arr = seg['arrival_station'] ?? '?';
                final dir = seg['direction'] ?? '';
                final isActive = d.replayCurrentSegment != null &&
                    d.replayCurrentSegment!['segment_id'] == segId;
                return GestureDetector(
                  onTap: d.replayPlaying ? null : () => provider.startReplaySegment(segId),
                  child: Container(
                    margin: const EdgeInsets.only(bottom: 2),
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
                    decoration: BoxDecoration(
                      color: isActive ? Colors.orange.withValues(alpha: 0.3) : Colors.transparent,
                      borderRadius: BorderRadius.circular(3),
                    ),
                    child: Text(
                      '${dep.length > 5 ? dep.substring(0, 5) : dep} \u2192 ${arr.length > 5 ? arr.substring(0, 5) : arr} (${dir.length > 2 ? dir.substring(0, 2) : dir})',
                      style: TextStyle(
                        color: isActive ? Colors.orange : (d.replayPlaying ? Colors.grey.shade600 : Colors.grey.shade300),
                        fontSize: 9,
                        fontWeight: isActive ? FontWeight.bold : FontWeight.normal,
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
        ] else
          GestureDetector(
            onTap: () => provider.fetchReplaySegments(),
            child: Text('Tap refresh to load segments',
              style: TextStyle(color: Colors.grey.shade500, fontSize: 9)),
          ),
      ],
    );
  }

  /// Initialize route select destination index based on current station
  void _initRouteSelectForStation(DashboardData d) {
    if (d.stations.isEmpty || d.currentStation == null) return;
    final sorted = List<StationInfo>.from(d.stations)
      ..sort((a, b) => a.order.compareTo(b.order));
    final currentIdx = sorted.indexWhere((s) => s.name == d.currentStation);
    if (currentIdx < 0) return;

    final isUpstream = d.direction == 'upstream';

    if (isUpstream) {
      // Upstream: towards Napindan (lower order)
      _selectedDestinationIndex = currentIdx - 1;
      while (_selectedDestinationIndex >= 0 &&
          _closedStations.contains(sorted[_selectedDestinationIndex].name)) {
        _selectedDestinationIndex--;
      }
      // Fallback to downstream if no open station upstream
      if (_selectedDestinationIndex < 0) {
        _selectedDestinationIndex = currentIdx + 1;
        while (_selectedDestinationIndex < sorted.length &&
            _closedStations.contains(sorted[_selectedDestinationIndex].name)) {
          _selectedDestinationIndex++;
        }
      }
    } else {
      // Downstream (default): towards Escolta (higher order)
      _selectedDestinationIndex = currentIdx + 1;
      while (_selectedDestinationIndex < sorted.length &&
          _closedStations.contains(sorted[_selectedDestinationIndex].name)) {
        _selectedDestinationIndex++;
      }
      // Fallback to upstream if no open station downstream
      if (_selectedDestinationIndex >= sorted.length) {
        _selectedDestinationIndex = currentIdx - 1;
        while (_selectedDestinationIndex >= 0 &&
            _closedStations.contains(sorted[_selectedDestinationIndex].name)) {
          _selectedDestinationIndex--;
        }
      }
    }
    _selectedDestinationIndex = _selectedDestinationIndex.clamp(0, sorted.length - 1);
  }

  // ==================== TOP BAR ====================
  Widget _buildTopBar(BuildContext context) {
    final d = context.watch<DashboardProvider>().data;

    return Container(
      color: const Color(0xFFFF6D00),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: SafeArea(
        bottom: false,
        child: Row(
          children: [
            const Text(
              'M/B Dalaray Voyage Assistant',
              style: TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontWeight: FontWeight.bold,
              ),
            ),
            const Spacer(),
            if (d.isMoving && d.departureStation != null && d.nextStation != null)
              _routeChip('ROUTE: ${d.departureStation} - ${d.nextStation}')
            else if (d.isDocked && d.currentStation != null) ...[
              _routeChip('DOCKED: ${d.currentStation}'),
              if (_currentView == DashboardView.map) ...[
                const SizedBox(width: 8),
                GestureDetector(
                  onTap: () {
                    _initRouteSelectForStation(d);
                    setState(() => _currentView = DashboardView.routeSelect);
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1A237E),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Text(
                      'SELECT ROUTE',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ),
              ],
            ] else
              _routeChip('CONNECTING...'),
          ],
        ),
      ),
    );
  }

  Widget _routeChip(String text) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        text,
        style: const TextStyle(
          color: Color(0xFF1A237E),
          fontWeight: FontWeight.bold,
          fontSize: 12,
        ),
      ),
    );
  }

  // ==================== FULL SCREEN MAP VIEW ====================
  Widget _buildFullScreenMap(BuildContext context) {
    final d = context.watch<DashboardProvider>().data;

    return Stack(
      children: [
        // Full-screen map
        _buildMap(d),

        // Current ferry speed banner (top-left)
        Positioned(
          top: 8,
          left: 8,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
            decoration: BoxDecoration(
              color: Colors.black87,
              borderRadius: BorderRadius.circular(8),
            ),
            child: Text(
              'CURRENT FERRY SPEED: ${d.speed != null ? "${d.speed!.toStringAsFixed(1)} KN" : "-- KN"}',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.bold,
                fontSize: 18,
              ),
            ),
          ),
        ),

        // Top-right: weather + passengers floating cards (below route indicator)
        Positioned(
          top: 8,
          right: 8,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              const SizedBox(height: 4), // just below orange bar
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  color: Colors.black87,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(_weatherIcon(d.weatherDescription), color: Colors.white, size: 26),
                    const SizedBox(width: 6),
                    Text(
                      '${d.temperatureC.toStringAsFixed(0)}°C  ${d.weatherDescription.toUpperCase()}',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 20),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 4),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
                decoration: BoxDecoration(
                  color: Colors.black87,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.people, color: Colors.white, size: 26),
                    const SizedBox(width: 6),
                    Text(
                      'PASSENGERS: ${d.passengerCount}',
                      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 20),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),

        // Bottom-left: status overlay (SOC, speed target, anomalies)
        Positioned(
          key: _overlayKeyStatusBox,
          bottom: 8,
          left: 8,
          width: 540,
          child: _buildStatusOverlay(d),
        ),

        // "Back to Default" button — dead center of screen, on top of everything
        if (_userOverrideMap)
          Positioned.fill(
            child: Center(
              child: GestureDetector(
                onTap: _resetMapToDefault,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  decoration: BoxDecoration(
                    color: Colors.black.withValues(alpha: 0.85),
                    borderRadius: BorderRadius.circular(20),
                    border: Border.all(color: Colors.white.withValues(alpha: 0.3)),
                    boxShadow: [
                      BoxShadow(
                        color: Colors.black.withValues(alpha: 0.5),
                        blurRadius: 8,
                        offset: const Offset(0, 2),
                      ),
                    ],
                  ),
                  child: const Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.my_location, color: Colors.white, size: 18),
                      SizedBox(width: 6),
                      Text(
                        'Back to Default',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),

      ],
    );
  }

  /// Get weather icon based on description
  IconData _weatherIcon(String desc) {
    final d = desc.toLowerCase();
    if (d.contains('thunder') || d.contains('storm')) return Icons.thunderstorm;
    if (d.contains('rain') || d.contains('drizzle')) return Icons.water_drop;
    if (d.contains('partly') || d.contains('partial')) return Icons.cloud_queue;
    if (d.contains('cloud') || d.contains('overcast')) return Icons.cloud;
    if (d.contains('clear') || d.contains('sunny') || d.contains('fair')) return Icons.wb_sunny;
    if (d.contains('fog') || d.contains('mist') || d.contains('haze')) return Icons.foggy;
    return Icons.cloud;
  }

  /// Get SOC color based on threshold: green >50%, orange 20-50%, red <20%
  Color _socColor(String? socText) {
    if (socText == null || socText == '--') return Colors.greenAccent;
    final numStr = socText.replaceAll(RegExp(r'[^0-9.]'), '');
    final val = double.tryParse(numStr);
    if (val == null) return Colors.greenAccent;
    if (val >= 50) return Colors.greenAccent;
    if (val >= 20) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  /// Same threshold color for SOC range display
  Color _socRangeColor(String socText) {
    final numStr = socText.replaceAll(RegExp(r'[^0-9.]'), '');
    final val = double.tryParse(numStr);
    if (val == null) return Colors.greenAccent;
    if (val >= 50) return Colors.greenAccent;
    if (val >= 20) return Colors.orangeAccent;
    return Colors.redAccent;
  }

  // ==================== STATUS OVERLAY (bottom-left, on top of map) ====================
  Widget _buildStatusOverlay(DashboardData d) {
    // Current SOC
    final currentSocText = d.soc != null ? '${d.soc}%' : '--%';

    // Predicted SOC at destination — use Model 1B during movement, 1A when docked
    final bool useModel1bLayout = d.isMoving || d.isArriving;
    String bestSocText = '--';
    String worstSocText = '--';
    String? model1bSocText; // Model 1B point estimate (no conformal bounds)
    if (useModel1bLayout && d.realtimePredictedSoc != null) {
      // Model 1B real-time point estimate
      var pointSoc = d.realtimePredictedSoc!;
      if (d.soc != null && pointSoc > d.soc!) {
        pointSoc = d.soc!.toDouble();
      }
      model1bSocText = '${pointSoc.toStringAsFixed(1)}%';
      bestSocText = model1bSocText;
      worstSocText = model1bSocText;
    } else if (d.autoPredictions.isNotEmpty) {
      // Model 1A pre-departure prediction — returns "best-worst" range
      int idx;
      if (d.isDocked) {
        idx = _dockedRouteIndex.clamp(0, d.autoPredictions.length - 1);
      } else if (d.nextStation != null) {
        // In transit: match by destination, not index 0
        final matchIdx = d.autoPredictions.indexWhere((p) => p.destination == d.nextStation);
        idx = matchIdx >= 0 ? matchIdx : 0;
      } else {
        idx = 0;
      }
      final predStr = d.autoPredictions[idx].predictedSoc;
      if (predStr != null && predStr != '--') {
        // Parse "XX.X-YY.Y%" range from predict_interval()
        final cleaned = predStr.replaceAll('%', '').trim();
        final parts = cleaned.split('-');
        if (parts.length == 2) {
          final best = double.tryParse(parts[0].trim());
          final worst = double.tryParse(parts[1].trim());
          if (best != null) bestSocText = '${best.toStringAsFixed(1)}%';
          if (worst != null) worstSocText = '${worst.toStringAsFixed(1)}%';
        } else {
          // Single value fallback
          final val = double.tryParse(cleaned);
          if (val != null) {
            bestSocText = '${val.toStringAsFixed(1)}%';
            worstSocText = bestSocText;
          }
        }
      }
    }

    // Cap: arrival SOC can never exceed current SOC
    if (d.soc != null && bestSocText != '--') {
      final bestVal = double.tryParse(bestSocText.replaceAll('%', ''));
      if (bestVal != null && bestVal > d.soc!) {
        bestSocText = '${d.soc!.toStringAsFixed(1)}%';
      }
    }
    if (d.soc != null && worstSocText != '--') {
      final worstVal = double.tryParse(worstSocText.replaceAll('%', ''));
      if (worstVal != null && worstVal > d.soc!) {
        worstSocText = '${d.soc!.toStringAsFixed(1)}%';
      }
    }

    // During warmup (moving but no Model 1B yet), fall back to Model 1A midpoint
    if (useModel1bLayout && model1bSocText == null && bestSocText != '--' && worstSocText != '--') {
      final bestVal = double.tryParse(bestSocText.replaceAll('%', ''));
      final worstVal = double.tryParse(worstSocText.replaceAll('%', ''));
      if (bestVal != null && worstVal != null) {
        model1bSocText = '${((bestVal + worstVal) / 2).toStringAsFixed(1)}%';
      }
    }

    final socClr = _socColor(model1bSocText ?? (worstSocText != '--' ? worstSocText : currentSocText));

    // Station label for SOC box
    final stationName = (d.nextStation ?? d.currentStation ?? '--').toUpperCase();
    final stationLabel = d.isMoving
        ? 'DEST: $stationName'
        : d.isDocked
            ? 'DOCKED AT: ${(d.currentStation ?? '--').toUpperCase()}'
            : 'CONNECTING...';

    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Navigation buttons — "Back to Table" + "Select Route" (when docked)
        Row(
          children: [
            Expanded(
              flex: d.isDocked ? 1 : 1,
              child: GestureDetector(
                onTap: () {
                  if (d.isMoving && d.departureStation != null && d.nextStation != null) {
                    _showSpeedTable(d.departureStation!, d.nextStation!);
                  } else if (d.isDocked && d.autoPredictions.isNotEmpty) {
                    final pred = d.autoPredictions[_dockedRouteIndex.clamp(0, d.autoPredictions.length - 1)];
                    _showSpeedTable(pred.departure, pred.destination);
                  } else if (d.currentStation != null && d.nextStation != null) {
                    _showSpeedTable(d.currentStation!, d.nextStation!);
                  }
                },
                child: Container(
                  padding: const EdgeInsets.symmetric(vertical: 8),
                  decoration: BoxDecoration(
                    color: const Color(0xFF1A237E),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      const Icon(Icons.table_chart, color: Colors.white, size: 20),
                      const SizedBox(width: 6),
                      Text(
                        'BACK TO SPEED TABLE',
                        style: TextStyle(
                          color: Colors.white,
                          fontSize: d.isDocked ? 15 : 18,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
            if (d.isDocked) ...[
              const SizedBox(width: 6),
              Expanded(
                child: GestureDetector(
                  onTap: () {
                    _initRouteSelectForStation(d);
                    setState(() => _currentView = DashboardView.routeSelect);
                  },
                  child: Container(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFF6D00),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(Icons.route, color: Colors.white, size: 20),
                        SizedBox(width: 6),
                        Text(
                          'SELECT ROUTE',
                          style: TextStyle(
                            color: Colors.white,
                            fontSize: 15,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
        const SizedBox(height: 6),
        // White box — SOC range + anomaly chips
        Container(
          width: 540,
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.95),
            borderRadius: BorderRadius.circular(12),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.2),
                blurRadius: 8,
                offset: const Offset(0, 2),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // SOC range — rectangular with station label
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
                decoration: BoxDecoration(
                  color: const Color(0xFF1A237E),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: socClr.withValues(alpha: 0.7), width: 2),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (useModel1bLayout) ...[
                      // Model 1B (moving/arriving): 2-line layout
                      Text(
                        'ESTIMATED ARRIVAL SOC AT $stationName',
                        style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 6),
                      Text(
                        model1bSocText ?? '...',
                        style: TextStyle(
                          color: model1bSocText != null ? _socRangeColor(model1bSocText) : Colors.grey.shade400,
                          fontSize: 56,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                    ] else ...[
                      // Station label (docked)
                      Text(
                        stationLabel,
                        style: const TextStyle(color: Colors.white70, fontSize: 16, fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 4),
                      // Model 1A (docked): current SOC → predicted range
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Column(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              const Text('SOC', style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold)),
                              Text(
                                currentSocText,
                                style: TextStyle(color: socClr, fontSize: 36, fontWeight: FontWeight.bold),
                              ),
                            ],
                          ),
                          if (bestSocText != '--') ...[
                            const SizedBox(width: 16),
                            const Icon(Icons.arrow_forward, color: Colors.white54, size: 26),
                            const SizedBox(width: 16),
                            Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Text('ESTIMATED ARRIVAL', style: TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.bold)),
                                if (bestSocText == worstSocText)
                                  Text(
                                    bestSocText,
                                    style: TextStyle(color: _socRangeColor(bestSocText), fontSize: 32, fontWeight: FontWeight.bold),
                                  )
                                else
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Text(
                                        bestSocText,
                                        style: TextStyle(color: _socRangeColor(bestSocText), fontSize: 28, fontWeight: FontWeight.bold),
                                      ),
                                      const Text(' - ', style: TextStyle(color: Colors.white54, fontSize: 28)),
                                      Text(
                                        worstSocText,
                                        style: TextStyle(color: _socRangeColor(worstSocText), fontSize: 28, fontWeight: FontWeight.bold),
                                      ),
                                    ],
                                  ),
                              ],
                            ),
                          ],
                        ],
                      ),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 10),
              // Anomaly status — full width
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceEvenly,
                children: [
                  Flexible(child: _anomalyChip('Starboard\nMotor', d.liveMotorHealth, d.motorAnomalyScore, d.motorAnomalyThreshold)),
                  const SizedBox(width: 6),
                  Flexible(child: _anomalyChip('Port\nMotor', d.liveMotorHealth, d.motorAnomalyScore, d.motorAnomalyThreshold)),
                  const SizedBox(width: 6),
                  Flexible(child: _anomalyChip('Battery\nHealth', d.liveBatteryHealth, d.batteryAnomalyScore, d.batteryAnomalyThreshold)),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _anomalyChip(String label, String health, double? score, double? threshold) {
    // Compute severity tier from score/threshold ratio
    final double? ratio = (score != null && threshold != null && threshold > 0)
        ? score / threshold
        : null;

    final String tierLabel;
    final Color bgColor;
    final Color borderColor;
    final Color textColor;
    final IconData icon;
    final Color iconColor;

    if (ratio != null) {
      if (ratio < 1.0) {
        tierLabel = 'Normal';
        bgColor = Colors.grey.shade200;
        borderColor = Colors.grey.shade400;
        textColor = Colors.black;
        icon = Icons.verified_user;
        iconColor = Colors.green;
      } else if (ratio < 1.5) {
        tierLabel = 'Watch';
        bgColor = Colors.yellow.shade100;
        borderColor = Colors.yellow.shade700;
        textColor = Colors.yellow.shade900;
        icon = Icons.visibility;
        iconColor = Colors.yellow.shade800;
      } else if (ratio < 2.0) {
        tierLabel = 'Warning';
        bgColor = Colors.orange.shade100;
        borderColor = Colors.orange.shade400;
        textColor = Colors.orange.shade900;
        icon = Icons.warning_amber;
        iconColor = Colors.orange;
      } else {
        tierLabel = 'Critical';
        bgColor = Colors.red.shade100;
        borderColor = Colors.red.shade300;
        textColor = Colors.red;
        icon = Icons.error;
        iconColor = Colors.red;
      }
    } else {
      // Fallback to binary health string when no numeric data
      final isOk = health == 'OK';
      tierLabel = isOk ? 'Normal' : 'Warning';
      bgColor = isOk ? Colors.grey.shade200 : Colors.red.shade100;
      borderColor = isOk ? Colors.grey.shade400 : Colors.red.shade300;
      textColor = isOk ? Colors.black : Colors.red;
      icon = isOk ? Icons.verified_user : Icons.warning;
      iconColor = isOk ? Colors.green : Colors.red;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: borderColor, width: 1.5),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, color: iconColor, size: 22),
              const SizedBox(width: 4),
              Flexible(
                child: Text(
                  label,
                  textAlign: TextAlign.center,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.bold,
                    color: textColor,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            tierLabel,
            style: TextStyle(
              fontSize: 11,
              fontWeight: FontWeight.w600,
              color: textColor,
            ),
          ),
        ],
      ),
    );
  }

  // ==================== MAP ====================

  /// Called whenever the user manually interacts with the map (pan/zoom).
  /// Activates override mode and starts the 15-second auto-reset timer.
  void _onUserMapInteraction() {
    if (!mounted) return;
    setState(() => _userOverrideMap = true);
    _overrideResetTimer?.cancel();
    _overrideResetTimer = Timer(_mapOverrideResetDuration, _resetMapToDefault);
  }

  /// Resets the map back to the auto-fit default behavior.
  void _resetMapToDefault() {
    if (!mounted) return;
    _overrideResetTimer?.cancel();
    _overrideResetTimer = null;
    setState(() => _userOverrideMap = false);
    _lastFitKey = null;
    final d = context.read<DashboardProvider>().data;
    _fitMapToStations(d);
  }

  List<LatLng> _getRiverSegment(String fromStation, String toStation) {
    int fromIdx = -1, toIdx = -1;
    for (int i = 0; i < _riverPath.length; i++) {
      if (_riverPath[i].station == fromStation) fromIdx = i;
      if (_riverPath[i].station == toStation) toIdx = i;
    }
    if (fromIdx < 0 || toIdx < 0) return [];
    final start = fromIdx < toIdx ? fromIdx : toIdx;
    final end = fromIdx < toIdx ? toIdx : fromIdx;
    return _riverPath
        .sublist(start, end + 1)
        .map((p) => LatLng(p.lat, p.lon))
        .toList();
  }

  /// Get the relevant stations: during transit show departure + destination + nearest;
  /// when docked show current + previous + next neighbor.
  List<StationInfo> _getRelevantStations(DashboardData d) {
    if (d.stations.isEmpty) return d.stations;

    final sorted = List<StationInfo>.from(d.stations)
      ..sort((a, b) => a.order.compareTo(b.order));

    // During transit: show departure and destination stations
    if (d.isMoving && d.departureStation != null && d.nextStation != null) {
      final depIdx = sorted.indexWhere((s) => s.name == d.departureStation);
      final destIdx = sorted.indexWhere((s) => s.name == d.nextStation);
      if (depIdx >= 0 && destIdx >= 0) {
        final indices = <int>{depIdx, destIdx};
        // Also include the current station if different (passing through)
        if (d.currentStation != null) {
          final curIdx = sorted.indexWhere((s) => s.name == d.currentStation);
          if (curIdx >= 0) indices.add(curIdx);
        }
        return indices.map((i) => sorted[i]).toList();
      }
    }

    if (d.currentStation == null) return d.stations;
    final currentIdx = sorted.indexWhere((s) => s.name == d.currentStation);
    if (currentIdx < 0) return d.stations;

    final indices = <int>{currentIdx};
    if (currentIdx > 0) indices.add(currentIdx - 1);
    if (currentIdx < sorted.length - 1) indices.add(currentIdx + 1);

    return indices.map((i) => sorted[i]).toList();
  }

  /// Fit the map camera to show only the relevant stations + ferry.
  void _fitMapToStations(DashboardData d) {
    // If the user has manually moved the map, don't override their view.
    if (_userOverrideMap) return;

    final relevant = _getRelevantStations(d);
    if (relevant.isEmpty) return;

    // Build a key from station names only — do NOT include ferry coordinates
    // or the map refits every position update causing jitter
    final fitKey = relevant.map((s) => s.name).join(',');
    if (fitKey == _lastFitKey) return;
    _lastFitKey = fitKey;

    // Collect all points: relevant stations + ferry position
    final points = <LatLng>[
      ...relevant.map((s) => LatLng(s.lat, s.lon)),
      LatLng(d.ferryLat, d.ferryLon),
    ];

    // Compute bounds
    double minLat = points.first.latitude, maxLat = points.first.latitude;
    double minLon = points.first.longitude, maxLon = points.first.longitude;
    for (final p in points) {
      if (p.latitude < minLat) minLat = p.latitude;
      if (p.latitude > maxLat) maxLat = p.latitude;
      if (p.longitude < minLon) minLon = p.longitude;
      if (p.longitude > maxLon) maxLon = p.longitude;
    }

    final bounds = LatLngBounds(
      LatLng(minLat, minLon),
      LatLng(maxLat, maxLon),
    );

    WidgetsBinding.instance.addPostFrameCallback((_) {
      _mapController.fitCamera(
        CameraFit.bounds(
          bounds: bounds,
          padding: const EdgeInsets.all(60),
        ),
      );
    });
  }

  /// Get the screen bounding rect of a widget by its GlobalKey, with padding.
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

  /// If the ferry's blue circle overlaps any UI overlay element,
  /// pan the map so the ferry is visible. Zoom level stays unchanged.
  void _ensureFerryVisible(LatLng ferryPos) {
    if (_userOverrideMap) return;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      final camera = _mapController.camera;
      final screenSize = camera.nonRotatedSize;
      final ferryScreen = camera.latLngToScreenPoint(ferryPos);

      // Blue circle collision rect (radius = 40px)
      const r = 40.0;
      final ferryRect = Rect.fromCenter(
        center: Offset(ferryScreen.x, ferryScreen.y),
        width: r * 2,
        height: r * 2,
      );

      // Collect overlay rects from GlobalKeys
      final overlayRects = <Rect>[
        if (_getOverlayRect(_overlayKeyStatusBox) case final rect?) rect,
      ];

      // Compute minimum shift to clear all overlapping elements
      var dx = 0.0;
      var dy = 0.0;
      for (final overlay in overlayRects) {
        if (!ferryRect.overlaps(overlay)) continue;

        // Horizontal: shift right past overlay's right edge, or left past left edge
        final shiftRight = overlay.right - ferryRect.left;
        final shiftLeft = ferryRect.right - overlay.left;
        if (shiftRight < shiftLeft) {
          dx = dx < shiftRight ? shiftRight : dx; // move ferry right
        } else {
          dx = dx > -shiftLeft ? -shiftLeft : dx; // move ferry left
        }

        // Vertical: shift down past overlay's bottom edge, or up past top edge
        final shiftDown = overlay.bottom - ferryRect.top;
        final shiftUp = ferryRect.bottom - overlay.top;
        if (shiftDown < shiftUp) {
          dy = dy < shiftDown ? shiftDown : dy; // move ferry down
        } else {
          dy = dy > -shiftUp ? -shiftUp : dy; // move ferry up
        }
      }

      if (dx != 0.0 || dy != 0.0) {
        // Shift map center opposite to the ferry shift direction
        final newCenterScreen = math.Point<double>(
          screenSize.x / 2 - dx,
          screenSize.y / 2 - dy,
        );
        final newCenter = camera.pointToLatLng(newCenterScreen);
        _mapController.move(newCenter, camera.zoom);
      }
    });
  }

  Widget _buildMap(DashboardData d) {
    final ferryPos = LatLng(d.ferryLat, d.ferryLon);
    // Show all stations when user has panned the map, otherwise only nearby ones
    final relevantStations = _userOverrideMap ? d.stations : _getRelevantStations(d);

    // Schedule camera fit, then nudge if ferry is behind overlay
    _fitMapToStations(d);
    _ensureFerryVisible(ferryPos);

    // Station markers — only show the 3 relevant stations
    final stationMarkers = <Marker>[];

    // Build a lookup for auto-predictions by destination name
    final predByDest = <String, AutoPrediction>{};
    for (final p in d.autoPredictions) {
      predByDest[p.destination] = p;
    }

    for (final s in relevantStations) {
      final isCurrent = s.name == d.currentStation;
      final isNext = s.name == d.nextStation;
      final isClosed = _closedStations.contains(s.name);

      // Show prediction label when user has panned the map
      final pred = _userOverrideMap ? predByDest[s.name] : null;
      // Use Model 1B for next station (if available), Model 1A for others
      final isNextStation = s.name == d.nextStation;
      final hasModel1B = isNextStation && d.realtimePredictedSoc != null;
      final showPred = _userOverrideMap && !isCurrent && !isClosed &&
          (hasModel1B || (pred != null && pred.predictedSoc != null));
      final markerHeight = (isClosed ? 78.0 : 62.0) + (showPred ? 70.0 : 0.0);

      // Build prediction display strings
      String? predText;
      String? predColorRef;
      String predLabel = '';
      String? predDirection;
      if (showPred && hasModel1B) {
        final upper = d.realtimeSocUpper ?? d.realtimePredictedSoc!;
        final lower = d.realtimeSocLower ?? d.realtimePredictedSoc!;
        predText = '${upper.toStringAsFixed(1)}-${lower.toStringAsFixed(1)}';
        predColorRef = lower.toStringAsFixed(1);
        predLabel = '(live)';
        predDirection = pred?.direction;
      } else if (showPred && pred != null) {
        predText = pred.predictedSoc;
        predColorRef = pred.predictedSoc!.split('-').last;
        predLabel = '@8kn';
        predDirection = pred.direction;
      }

      stationMarkers.add(Marker(
        point: LatLng(s.lat, s.lon),
        width: showPred ? 180 : 100,
        height: markerHeight,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // Station name label
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: isClosed ? Colors.grey.shade300.withValues(alpha: 0.9) : Colors.white.withValues(alpha: 0.9),
                borderRadius: BorderRadius.circular(4),
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: 0.3),
                    blurRadius: 3,
                  ),
                ],
              ),
              child: Text(
                s.name,
                style: TextStyle(
                  color: isClosed ? Colors.grey : isCurrent ? Colors.green.shade800 : isNext ? Colors.orange.shade800 : Colors.blue.shade800,
                  fontSize: 16,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
            if (isClosed)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 3, vertical: 0),
                decoration: BoxDecoration(
                  color: Colors.red.shade700,
                  borderRadius: BorderRadius.circular(3),
                ),
                child: const Text(
                  'CLOSED',
                  style: TextStyle(color: Colors.white, fontSize: 12, fontWeight: FontWeight.bold),
                ),
              ),
            const SizedBox(height: 2),
            // Station dot
            Container(
              width: 30,
              height: 30,
              decoration: BoxDecoration(
                color: isClosed
                    ? Colors.grey
                    : isCurrent
                        ? Colors.green
                        : isNext
                            ? Colors.orange
                            : Colors.blue.shade700,
                shape: BoxShape.circle,
                border: Border.all(color: Colors.white, width: 2),
                boxShadow: [
                  if (!isClosed && (isCurrent || isNext))
                    BoxShadow(
                      color: (isCurrent ? Colors.green : Colors.orange).withValues(alpha: 0.5),
                      blurRadius: 8,
                      spreadRadius: 2,
                    ),
                ],
              ),
              child: Center(
                child: Text(
                  '${s.order + 1}',
                  style: TextStyle(color: isClosed ? Colors.grey.shade400 : Colors.white, fontSize: 13, fontWeight: FontWeight.bold),
                ),
              ),
            ),
            // SOC prediction label (visible when map is manually panned)
            if (showPred && predText != null) ...[
              const SizedBox(height: 3),
              Builder(builder: (context) {
                // Determine SOC tint color based on the lower-bound value
                final socVal = double.tryParse(predColorRef!) ?? 50.0;
                final Color tintColor;
                if (socVal < 20) {
                  tintColor = Colors.red;
                } else if (socVal < 50) {
                  tintColor = Colors.orange;
                } else {
                  tintColor = Colors.green;
                }
                return Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                  decoration: BoxDecoration(
                    color: Color.alphaBlend(
                      tintColor.withValues(alpha: 0.2),
                      Colors.black.withValues(alpha: 0.8),
                    ),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (predDirection != null)
                        Text(
                          predDirection == 'upstream' ? 'UPSTREAM' : 'DOWNSTREAM',
                          style: TextStyle(
                            color: predDirection == 'upstream' ? Colors.orange.shade300 : Colors.lightBlue.shade300,
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            '$predText%',
                            style: TextStyle(
                              color: _socRangeColor(predColorRef!),
                              fontSize: 22,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          Text(
                            ' $predLabel',
                            style: TextStyle(
                              color: hasModel1B ? Colors.cyan.shade300 : Colors.grey.shade400,
                              fontSize: 15,
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                );
              }),
            ],
          ],
        ),
      ));
    }

    // Ferry marker — top-view sprite with pulsing blue circle
    stationMarkers.add(Marker(
      point: ferryPos,
      width: 80,
      height: 80,
      child: AnimatedBuilder(
        animation: _pulseAnimation,
        builder: (context, child) {
          return Stack(
            alignment: Alignment.center,
            children: [
              // Pulsing blue circle highlight
              Container(
                width: 80,
                height: 80,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: Colors.blue.withValues(alpha: _pulseAnimation.value * 0.3),
                  border: Border.all(
                    color: Colors.blue.withValues(alpha: _pulseAnimation.value),
                    width: 2,
                  ),
                ),
              ),
              // Ferry sprite — rotated by heading
              // Sprite has head pointing RIGHT (east = 90°), so subtract 90° from heading
              Transform.rotate(
                angle: (d.ferryHeading - 90) * math.pi / 180,
                child: Image.asset(
                  'assets/ferry_top_view.png',
                  width: 52,
                  height: 28,
                  fit: BoxFit.contain,
                ),
              ),
            ],
          );
        },
      ),
    ));

    // Route polyline — extract the river path segment between the relevant stations
    final List<LatLng> routePoints;
    if (relevantStations.length >= 2) {
      final sortedRelevant = List<StationInfo>.from(relevantStations)
        ..sort((a, b) => a.order.compareTo(b.order));
      routePoints = _getRiverSegment(
        sortedRelevant.first.name,
        sortedRelevant.last.name,
      );
    } else {
      routePoints = [];
    }

    final map = FlutterMap(
      key: ValueKey(_terrainMap ? 'map-esri' : 'map-osm'),
      mapController: _mapController,
      options: MapOptions(
        initialCenter: ferryPos,
        initialZoom: 14.5,
        interactionOptions: const InteractionOptions(
          flags: InteractiveFlag.drag |
              InteractiveFlag.pinchZoom |
              InteractiveFlag.doubleTapZoom |
              InteractiveFlag.scrollWheelZoom,
        ),
        onMapEvent: (event) {
          // Ignore programmatic camera moves; only react to user gestures.
          const programmatic = {
            MapEventSource.mapController,
            MapEventSource.fitCamera,
            MapEventSource.nonRotatedSizeChange,
            MapEventSource.interactiveFlagsChanged,
          };
          if (!programmatic.contains(event.source)) {
            _onUserMapInteraction();
          }
        },
      ),
      children: [
        TileLayer(
          key: ValueKey(_terrainMap ? 'esri' : 'osm'),
          urlTemplate: _terrainMap
              ? 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
              : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          userAgentPackageName: 'com.dalaray.voyageassistant',
          tileProvider: _terrainMap ? NetworkTileProvider() : CachedTileProvider(),
        ),
        if (routePoints.length >= 2)
          PolylineLayer(
            polylines: [
              Polyline(
                points: routePoints,
                color: Colors.blue.shade800,
                strokeWidth: 3,
                pattern: const StrokePattern.dotted(),
              ),
            ],
          ),
        MarkerLayer(markers: stationMarkers),
      ],
    );

    return map;
  }

  Widget _arrowButton(IconData icon, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(6),
        decoration: BoxDecoration(
          color: Colors.black54,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Icon(icon, color: Colors.white, size: 28),
      ),
    );
  }

  void _scrollRouteToDestination() {
    if (!_routeScrollController.hasClients) return;
    const itemHeight = 44.0; // Padding(8) + SizedBox(36)
    final targetOffset = _selectedDestinationIndex * itemHeight;
    final viewportHeight = _routeScrollController.position.viewportDimension;
    // Center the selected item in the viewport
    final scrollTo = (targetOffset - viewportHeight / 2 + itemHeight / 2)
        .clamp(0.0, _routeScrollController.position.maxScrollExtent);
    _routeScrollController.animateTo(
      scrollTo,
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeInOut,
    );
  }

  // ==================== ROUTE SELECTION VIEW (when docked) ====================
  Widget _buildRouteSelectView(BuildContext context) {
    final d = context.watch<DashboardProvider>().data;

    // Build sorted station list
    final sorted = List<StationInfo>.from(d.stations)
      ..sort((a, b) => a.order.compareTo(b.order));
    final currentIdx = sorted.indexWhere((s) => s.name == d.currentStation);

    // Ensure destination index is valid
    if (_selectedDestinationIndex < 0 || _selectedDestinationIndex >= sorted.length) {
      _initRouteSelectForStation(d);
    }
    // Clamp to valid range and prevent selecting current station
    _selectedDestinationIndex = _selectedDestinationIndex.clamp(0, sorted.length - 1);
    if (_selectedDestinationIndex == currentIdx) {
      if (currentIdx < sorted.length - 1) {
        _selectedDestinationIndex = currentIdx + 1;
      } else if (currentIdx > 0) {
        _selectedDestinationIndex = currentIdx - 1;
      }
    }

    final destStation = sorted.isNotEmpty ? sorted[_selectedDestinationIndex] : null;
    final currentStation = currentIdx >= 0 ? sorted[currentIdx] : null;

    // Determine which directions are available
    final canGoUp = _selectedDestinationIndex > 0 &&
        !(_selectedDestinationIndex - 1 == currentIdx && currentIdx == 0);
    final canGoDown = _selectedDestinationIndex < sorted.length - 1 &&
        !(_selectedDestinationIndex + 1 == currentIdx && currentIdx == sorted.length - 1);

    return LayoutBuilder(
      builder: (context, constraints) {
        final totalWidth = constraints.maxWidth;
        final totalHeight = constraints.maxHeight;
        final rightPanelWidth = totalWidth * 0.58;
        final leftAreaWidth = totalWidth - rightPanelWidth;
        const bottomBarH = 22.0;
        final ferryAreaH = totalHeight - bottomBarH;

        return Container(
          color: Colors.white,
          child: Stack(
            children: [
              // ---- LIGHT BLUE BACKGROUND: full left panel ----
              Positioned(
                left: 0,
                top: 0,
                width: leftAreaWidth,
                bottom: bottomBarH,
                child: Container(color: const Color(0xFFB3E5FC)),
              ),

              // ---- BACK WAVES: behind ferry (layers 0-1) ----
              Positioned(
                left: 0,
                bottom: bottomBarH,
                width: leftAreaWidth,
                height: (ferryAreaH - 82) * 0.48,
                child: AnimatedBuilder(
                  animation: _waveController,
                  builder: (context, child) {
                    return CustomPaint(
                      painter: WavePainter(animationValue: _waveController.value),
                      size: Size.infinite,
                    );
                  },
                ),
              ),

              // ---- FERRY IMAGE ----
              Positioned(
                left: 0,
                top: 82,
                width: leftAreaWidth,
                bottom: bottomBarH,
                child: ClipRect(
                  child: AnimatedBuilder(
                    animation: _bobAnimation,
                    builder: (context, child) {
                      return Transform.translate(
                        offset: Offset(0, _bobAnimation.value),
                        child: child,
                      );
                    },
                    child: OverflowBox(
                      maxWidth: leftAreaWidth * 2.2,
                      maxHeight: (ferryAreaH - 82) * 1.5,
                      alignment: const Alignment(0.9, 0.65),
                      child: Image.asset(
                        'assets/ferry_sprite.png',
                        fit: BoxFit.contain,
                      ),
                    ),
                  ),
                ),
              ),

              // ---- FRONT WAVE: in front of ferry (layer 2, see-through) ----
              Positioned(
                left: 0,
                bottom: bottomBarH,
                width: leftAreaWidth,
                height: (ferryAreaH - 82) * 0.48,
                child: AnimatedBuilder(
                  animation: _waveController,
                  builder: (context, child) {
                    return CustomPaint(
                      painter: WavePainter(animationValue: _waveController.value, frontOnly: true),
                      size: Size.infinite,
                    );
                  },
                ),
              ),

              // ---- TIDE INFO BOXES: in the wave area ----
              Positioned(
                left: 0,
                bottom: bottomBarH + 12,
                width: leftAreaWidth,
                child: _buildTideInfoBoxes(d, leftAreaWidth),
              ),

              // ---- LEFT OVERLAYS: Anomaly chips + Weather/Passenger ----
              Positioned(
                left: 0,
                top: 0,
                width: leftAreaWidth,
                child: Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(left: 6, top: 4, right: 6),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Flexible(child: _anomalyChip('Starboard\nMotor', d.liveMotorHealth, d.motorAnomalyScore, d.motorAnomalyThreshold)),
                          const SizedBox(width: 6),
                          Flexible(child: _anomalyChip('Port\nMotor', d.liveMotorHealth, d.motorAnomalyScore, d.motorAnomalyThreshold)),
                          const SizedBox(width: 6),
                          Flexible(child: _anomalyChip('Battery\nHealth', d.liveBatteryHealth, d.batteryAnomalyScore, d.batteryAnomalyThreshold)),
                        ],
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(left: 8, top: 6, right: 8),
                      child: Center(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.grey.shade600, width: 1.5),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            'WEATHER:  ${d.weatherDescription.toUpperCase()}',
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(left: 8, top: 4, right: 8),
                      child: Center(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.grey.shade600, width: 1.5),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            'PASSENGERS:  ${d.passengerCount}',
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              // ---- RIGHT PANEL: Route selection ----
              Positioned(
                right: 0,
                top: 0,
                width: rightPanelWidth,
                height: ferryAreaH,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  color: const Color(0xFF1A237E),
                  child: Column(
                    children: [
                      // Title
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        decoration: BoxDecoration(
                          color: const Color(0xFF42A5F5),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: const Text(
                          'SELECT DESTINATION',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 24,
                          ),
                        ),
                      ),
                      const SizedBox(height: 4),

                      // Current station label
                      if (currentStation != null)
                        Text(
                          'DOCKED AT: ${currentStation.name.toUpperCase()}',
                          style: const TextStyle(
                            color: Colors.white70,
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      const SizedBox(height: 4),

                      // Route diagram — vertical line with station dots
                      Expanded(
                        child: _buildRouteDiagram(sorted, currentIdx, _selectedDestinationIndex),
                      ),

                      const SizedBox(height: 4),

                      // Arrow buttons for cycling destination
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          // Up arrow (towards Napindan / lower order)
                          GestureDetector(
                            onTap: canGoUp
                                ? () {
                                    setState(() {
                                      _selectedDestinationIndex--;
                                      // Skip current station and closed stations
                                      while (_selectedDestinationIndex >= 0 &&
                                          (_selectedDestinationIndex == currentIdx ||
                                           _closedStations.contains(sorted[_selectedDestinationIndex].name))) {
                                        _selectedDestinationIndex--;
                                      }
                                      _selectedDestinationIndex = _selectedDestinationIndex.clamp(0, sorted.length - 1);
                                    });
                                    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollRouteToDestination());
                                  }
                                : null,
                            child: Container(
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: canGoUp ? const Color(0xFF42A5F5) : Colors.grey.shade700,
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Icon(
                                Icons.arrow_upward,
                                color: canGoUp ? Colors.white : Colors.grey,
                                size: 32,
                              ),
                            ),
                          ),
                          const SizedBox(width: 24),
                          // Down arrow (towards Escolta / higher order)
                          GestureDetector(
                            onTap: canGoDown
                                ? () {
                                    setState(() {
                                      _selectedDestinationIndex++;
                                      // Skip current station and closed stations
                                      while (_selectedDestinationIndex < sorted.length &&
                                          (_selectedDestinationIndex == currentIdx ||
                                           _closedStations.contains(sorted[_selectedDestinationIndex].name))) {
                                        _selectedDestinationIndex++;
                                      }
                                      _selectedDestinationIndex = _selectedDestinationIndex.clamp(0, sorted.length - 1);
                                    });
                                    WidgetsBinding.instance.addPostFrameCallback((_) => _scrollRouteToDestination());
                                  }
                                : null,
                            child: Container(
                              padding: const EdgeInsets.all(8),
                              decoration: BoxDecoration(
                                color: canGoDown ? const Color(0xFF42A5F5) : Colors.grey.shade700,
                                borderRadius: BorderRadius.circular(8),
                              ),
                              child: Icon(
                                Icons.arrow_downward,
                                color: canGoDown ? Colors.white : Colors.grey,
                                size: 32,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 6),

                      // Selected destination + GO button
                      if (destStation != null)
                        GestureDetector(
                          onTap: () {
                            if (currentStation != null) {
                              _showSpeedTableFromRouteSelect(
                                currentStation.name,
                                destStation.name,
                              );
                            }
                          },
                          child: Container(
                            width: double.infinity,
                            padding: const EdgeInsets.symmetric(vertical: 10),
                            decoration: BoxDecoration(
                              color: const Color(0xFFFF6D00),
                              borderRadius: BorderRadius.circular(8),
                            ),
                            child: Text(
                              'GO TO ${destStation.name.toUpperCase()}',
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.bold,
                                fontSize: 24,
                              ),
                            ),
                          ),
                        ),
                      const SizedBox(height: 4),

                      // Back to map
                      GestureDetector(
                        onTap: _backToMap,
                        child: const Text(
                          'BACK TO MAP',
                          style: TextStyle(
                            color: Colors.white70,
                            fontWeight: FontWeight.bold,
                            fontSize: 18,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),

              // ---- BOTTOM BAR ----
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                height: bottomBarH,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  color: Colors.white,
                  child: Row(
                    children: [
                      Container(
                        width: 8, height: 8,
                        decoration: const BoxDecoration(color: Colors.grey, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 4),
                      const Text('English/ Filipino', style: TextStyle(fontSize: 11)),
                      const Spacer(),
                      Container(
                        width: 8, height: 8,
                        decoration: BoxDecoration(
                          color: d.connected ? Colors.green : Colors.red,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        d.connected ? 'Connected' : 'Disconnected',
                        style: const TextStyle(fontSize: 11),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  /// Builds a vertical route diagram showing all stations with current (green) and destination (red)
  Widget _buildRouteDiagram(List<StationInfo> sorted, int currentIdx, int destIdx) {
    return ListView.builder(
      controller: _routeScrollController,
      padding: const EdgeInsets.symmetric(vertical: 4),
      itemCount: sorted.length,
      itemBuilder: (context, i) {
        final station = sorted[i];
        final isCurrent = i == currentIdx;
        final isDest = i == destIdx;
        final isClosed = _closedStations.contains(station.name);
        final isBetween = (currentIdx < destIdx)
            ? (i > currentIdx && i < destIdx)
            : (i < currentIdx && i > destIdx);

        Color dotColor;
        if (isClosed && !isCurrent) {
          dotColor = Colors.grey.shade700;
        } else if (isCurrent) {
          dotColor = Colors.green;
        } else if (isDest) {
          dotColor = Colors.red;
        } else if (isBetween) {
          dotColor = Colors.blue.shade300;
        } else {
          dotColor = Colors.grey.shade500;
        }

        return GestureDetector(
          onTap: (isCurrent || isClosed)
              ? null
              : () {
                  setState(() => _selectedDestinationIndex = i);
                },
          child: Opacity(
            opacity: (isClosed && !isCurrent) ? 0.5 : 1.0,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 4),
              child: Row(
                children: [
                  // Vertical line + dot
                  SizedBox(
                    width: 40,
                    height: 36,
                    child: Stack(
                      alignment: Alignment.center,
                      children: [
                        // Vertical line
                        if (i > 0 || i < sorted.length - 1)
                          Positioned.fill(
                            child: Center(
                              child: Container(
                                width: 3,
                                color: (isBetween || isDest || isCurrent)
                                    ? Colors.blue.shade300
                                    : Colors.grey.shade600,
                              ),
                            ),
                          ),
                        // Station dot
                        Container(
                          width: isCurrent || isDest ? 22 : 16,
                          height: isCurrent || isDest ? 22 : 16,
                          decoration: BoxDecoration(
                            color: dotColor,
                            shape: BoxShape.circle,
                            border: Border.all(color: Colors.white, width: 2),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 8),
                  // Station name
                  Expanded(
                    child: Text(
                      station.name.toUpperCase(),
                      style: TextStyle(
                        color: isClosed && !isCurrent
                            ? Colors.grey.shade600
                            : isCurrent
                                ? Colors.greenAccent
                                : isDest
                                    ? Colors.redAccent
                                    : Colors.white70,
                        fontWeight: (isCurrent || isDest) ? FontWeight.bold : FontWeight.normal,
                        fontSize: (isCurrent || isDest) ? 22 : 18,
                      ),
                    ),
                  ),
                  // Labels
                  if (isClosed && !isCurrent)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: Colors.grey.shade700,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: const Text(
                        'CLOSED',
                        style: TextStyle(color: Colors.white60, fontSize: 12, fontWeight: FontWeight.bold),
                      ),
                    ),
                  if (isCurrent)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: Colors.green,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: const Text(
                        'YOU ARE HERE',
                        style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold),
                      ),
                    ),
                  if (isDest && !isClosed)
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                      decoration: BoxDecoration(
                        color: Colors.red,
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: const Text(
                        'DESTINATION',
                        style: TextStyle(color: Colors.white, fontSize: 14, fontWeight: FontWeight.bold),
                      ),
                    ),
              ],
            ),
          ),
          ),
        );
      },
    );
  }

  // ==================== SPEED TABLE VIEW ====================
  Widget _buildSpeedTableView(BuildContext context) {
    final d = context.watch<DashboardProvider>().data;

    return LayoutBuilder(
      builder: (context, constraints) {
        final totalWidth = constraints.maxWidth;
        final totalHeight = constraints.maxHeight;
        // Right panel 60%, left 40% — ferry fills left, table fills right
        final rightPanelWidth = totalWidth * 0.58;
        final leftAreaWidth = totalWidth - rightPanelWidth;
        const bottomBarH = 22.0;
        final ferryAreaH = totalHeight - bottomBarH;

        return Container(
          color: Colors.white,
          child: Stack(
            children: [
              // ---- LIGHT BLUE BACKGROUND: full left panel ----
              Positioned(
                left: 0,
                top: 0,
                width: leftAreaWidth,
                bottom: bottomBarH,
                child: Container(
                  color: const Color(0xFFB3E5FC),
                ),
              ),

              // ---- BACK WAVES: behind ferry (layers 0-1) ----
              Positioned(
                left: 0,
                bottom: bottomBarH,
                width: leftAreaWidth,
                height: (ferryAreaH - 82) * 0.48,
                child: AnimatedBuilder(
                  animation: _waveController,
                  builder: (context, child) {
                    return CustomPaint(
                      painter: WavePainter(animationValue: _waveController.value),
                      size: Size.infinite,
                    );
                  },
                ),
              ),

              // ---- FERRY IMAGE: zoomed in, head visible, pushed lower ----
              Positioned(
                left: 0,
                top: 82,
                width: leftAreaWidth,
                bottom: bottomBarH,
                child: ClipRect(
                  child: AnimatedBuilder(
                    animation: _bobAnimation,
                    builder: (context, child) {
                      return Transform.translate(
                        offset: Offset(0, _bobAnimation.value),
                        child: child,
                      );
                    },
                    child: OverflowBox(
                      maxWidth: leftAreaWidth * 2.2,
                      maxHeight: (ferryAreaH - 82) * 1.5,
                      alignment: const Alignment(0.9, 0.65),
                      child: Image.asset(
                        'assets/ferry_sprite.png',
                        fit: BoxFit.contain,
                      ),
                    ),
                  ),
                ),
              ),

              // ---- FRONT WAVE: in front of ferry (layer 2, see-through) ----
              Positioned(
                left: 0,
                bottom: bottomBarH,
                width: leftAreaWidth,
                height: (ferryAreaH - 82) * 0.48,
                child: AnimatedBuilder(
                  animation: _waveController,
                  builder: (context, child) {
                    return CustomPaint(
                      painter: WavePainter(animationValue: _waveController.value, frontOnly: true),
                      size: Size.infinite,
                    );
                  },
                ),
              ),

              // ---- TIDE INFO BOXES: in the wave area ----
              Positioned(
                left: 0,
                bottom: bottomBarH + 12,
                width: leftAreaWidth,
                child: _buildTideInfoBoxes(d, leftAreaWidth),
              ),

              // ---- LEFT OVERLAYS: Anomaly chips + Weather/Passenger ----
              Positioned(
                left: 0,
                top: 0,
                width: leftAreaWidth,
                child: Column(
                  children: [
                    Padding(
                      padding: const EdgeInsets.only(left: 6, top: 4, right: 6),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Flexible(child: _anomalyChip('Starboard\nMotor', d.liveMotorHealth, d.motorAnomalyScore, d.motorAnomalyThreshold)),
                          const SizedBox(width: 6),
                          Flexible(child: _anomalyChip('Port\nMotor', d.liveMotorHealth, d.motorAnomalyScore, d.motorAnomalyThreshold)),
                          const SizedBox(width: 6),
                          Flexible(child: _anomalyChip('Battery\nHealth', d.liveBatteryHealth, d.batteryAnomalyScore, d.batteryAnomalyThreshold)),
                        ],
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(left: 8, top: 6, right: 8),
                      child: Center(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.grey.shade600, width: 1.5),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            'WEATHER:  ${d.weatherDescription.toUpperCase()}',
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                        ),
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(left: 8, top: 4, right: 8),
                      child: Center(
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                          decoration: BoxDecoration(
                            border: Border.all(color: Colors.grey.shade600, width: 1.5),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            'PASSENGERS:  ${d.passengerCount}',
                            style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              // ---- RIGHT PANEL: Speed table ----
              Positioned(
                right: 0,
                top: 0,
                width: rightPanelWidth,
                height: ferryAreaH,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  color: const Color(0xFF1A237E),
                  child: Column(
                    children: [
                      // Route header
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(vertical: 8),
                        decoration: BoxDecoration(
                          color: const Color(0xFF42A5F5),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          'ROUTE: ${_speedTableDeparture?.toUpperCase() ?? ""} - ${_speedTableDestination?.toUpperCase() ?? ""}',
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 20,
                          ),
                        ),
                      ),
                      const SizedBox(height: 4),
                      // Table header — 3 columns
                      Container(
                        color: const Color(0xFF42A5F5),
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        child: const Row(
                          children: [
                            Expanded(
                              flex: 2,
                              child: Text(
                                'TARGET\nSPEED',
                                textAlign: TextAlign.center,
                                style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15),
                              ),
                            ),
                            Expanded(
                              flex: 3,
                              child: Text(
                                'BEST\nCASE',
                                textAlign: TextAlign.center,
                                style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15),
                              ),
                            ),
                            Expanded(
                              flex: 3,
                              child: Text(
                                'WORST\nCASE',
                                textAlign: TextAlign.center,
                                style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold, fontSize: 15),
                              ),
                            ),
                          ],
                        ),
                      ),
                      // Speed rows
                      Expanded(
                        child: d.speedPredictions.isEmpty
                            ? const Center(
                                child: CircularProgressIndicator(color: Colors.white),
                              )
                            : ListView(
                                children: d.speedPredictions.map((sp) => _speedRow(sp)).toList(),
                              ),
                      ),
                      // Legend
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          _legendDot(Colors.green, 'CLEAR TO GO'),
                          const SizedBox(width: 18),
                          _legendDot(Colors.orange, 'CAUTION'),
                          const SizedBox(width: 18),
                          _legendDot(Colors.red, 'CRITICAL'),
                        ],
                      ),
                      const SizedBox(height: 6),
                      // Navigation buttons
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          if (_cameFromRouteSelect) ...[
                            GestureDetector(
                              onTap: _backToRouteSelect,
                              child: const Text(
                                'CHANGE ROUTE',
                                style: TextStyle(
                                  color: Color(0xFFFF6D00),
                                  fontWeight: FontWeight.bold,
                                  fontSize: 20,
                                ),
                              ),
                            ),
                            const SizedBox(width: 24),
                          ],
                          GestureDetector(
                            onTap: _backToMap,
                            child: const Text(
                              'GO TO MAP',
                              style: TextStyle(
                                color: Color(0xFFFF6D00),
                                fontWeight: FontWeight.bold,
                                fontSize: 20,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),

              // ---- BOTTOM BAR: English/Filipino + Connected ----
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                height: bottomBarH,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  color: Colors.white,
                  child: Row(
                    children: [
                      Container(
                        width: 8, height: 8,
                        decoration: const BoxDecoration(color: Colors.grey, shape: BoxShape.circle),
                      ),
                      const SizedBox(width: 4),
                      const Text('English/ Filipino', style: TextStyle(fontSize: 11)),
                      const Spacer(),
                      Container(
                        width: 8, height: 8,
                        decoration: BoxDecoration(
                          color: d.connected ? Colors.green : Colors.red,
                          shape: BoxShape.circle,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Text(
                        d.connected ? 'Connected' : 'Disconnected',
                        style: const TextStyle(fontSize: 11),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _speedRow(SpeedPrediction sp) {
    final speedLabel = '${sp.speedKn.round()} KN';

    // Derive best/worst case from predicted SOC ± 2%
    String bestCase = '--';
    String worstCase = '--';
    Color bestColor = Colors.white;
    Color worstColor = Colors.white;

    Color socThresholdColor(double val) {
      if (val >= 50) return Colors.greenAccent;
      if (val >= 20) return Colors.orangeAccent;
      return Colors.redAccent;
    }

    final predStr = sp.predictedSoc;
    if (predStr != null && predStr != '--' && predStr != 'N/A') {
      // Backend sends "best-worst%" range from Model 1A predict_interval()
      final cleaned = predStr.replaceAll('%', '').trim();
      final parts = cleaned.split('-');
      if (parts.length == 2) {
        final best = double.tryParse(parts[0].trim());
        final worst = double.tryParse(parts[1].trim());
        if (best != null) {
          bestCase = '${best.toStringAsFixed(1)}%';
          bestColor = socThresholdColor(best);
        }
        if (worst != null) {
          worstCase = '${worst.toStringAsFixed(1)}%';
          worstColor = socThresholdColor(worst);
        }
      } else {
        // Single value fallback
        final val = double.tryParse(cleaned);
        if (val != null) {
          bestCase = '${val.toStringAsFixed(1)}%';
          worstCase = bestCase;
          bestColor = socThresholdColor(val);
          worstColor = bestColor;
        }
      }
    }

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                flex: 2,
                child: Text(
                  speedLabel,
                  textAlign: TextAlign.center,
                  style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                ),
              ),
              Expanded(
                flex: 3,
                child: Text(
                  bestCase,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: bestColor, fontSize: 22, fontWeight: FontWeight.bold),
                ),
              ),
              Expanded(
                flex: 3,
                child: Text(
                  worstCase,
                  textAlign: TextAlign.center,
                  style: TextStyle(color: worstColor, fontSize: 22, fontWeight: FontWeight.bold),
                ),
              ),
            ],
          ),
          const Divider(color: Colors.white24, height: 12),
        ],
      ),
    );
  }

  Widget _legendDot(Color color, String label) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 18,
          height: 18,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(label, style: const TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.bold)),
      ],
    );
  }

  Widget _buildTideInfoBoxes(DashboardData d, double width) {
    final tidePhaseLabel = d.tidePhase == 0 ? 'RISING' : 'FALLING';
    final tideIcon = d.tidePhase == 0 ? Icons.trending_up : Icons.trending_down;

    Widget tideBox(IconData icon, String label, String value) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: const Color(0xFF0D47A1).withValues(alpha: 0.75),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.white.withValues(alpha: 0.3), width: 1),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, color: Colors.white70, size: 20),
            const SizedBox(height: 4),
            Text(
              value,
              style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 2),
            Text(
              label,
              textAlign: TextAlign.center,
              style: const TextStyle(color: Colors.white70, fontSize: 11),
            ),
          ],
        ),
      );
    }

    return SizedBox(
      width: width,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
          children: [
            Flexible(child: tideBox(Icons.waves, 'TIDE HEIGHT', '${d.tideHeightM.toStringAsFixed(2)} m')),
            const SizedBox(width: 8),
            Flexible(child: tideBox(Icons.access_time, 'SINCE HIGH TIDE', '${d.hoursSinceHighTide.toStringAsFixed(1)} hrs')),
            const SizedBox(width: 8),
            Flexible(child: tideBox(tideIcon, 'TIDE PHASE', tidePhaseLabel)),
          ],
        ),
      ),
    );
  }
}

/// Custom painter for layered sine-wave water effect under the ferry.
class WavePainter extends CustomPainter {
  final double animationValue; // 0.0 – 1.0, loops continuously
  final bool frontOnly; // true = only the front (lightest) wave layer

  WavePainter({required this.animationValue, this.frontOnly = false});

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final phase = animationValue * 2 * math.pi;

    // Three wave layers: back (darkest, tallest), middle, front (lightest, shortest)
    // Speeds & frequencies must be integers for seamless looping
    final allLayers = [
      (color: const Color(0xFF0288D1).withValues(alpha: 0.35), amplitude: h * 0.12, frequency: 1.0, speed: 1.0, yOffset: h * 0.10),
      (color: const Color(0xFF03A9F4).withValues(alpha: 0.45), amplitude: h * 0.09, frequency: 2.0, speed: 2.0, yOffset: h * 0.25),
      (color: const Color(0xFF4FC3F7).withValues(alpha: 0.55), amplitude: h * 0.07, frequency: 3.0, speed: 3.0, yOffset: h * 0.38),
    ];

    // Back painter draws layers 0-1, front painter draws layer 2
    final layers = frontOnly ? [allLayers[2]] : [allLayers[0], allLayers[1]];

    for (final layer in layers) {
      final paint = Paint()
        ..color = layer.color
        ..style = PaintingStyle.fill;

      final path = ui.Path();
      path.moveTo(0, h); // bottom-left

      // Draw the sine curve from left to right
      for (double x = 0; x <= w; x += 2) {
        final y = layer.yOffset +
            math.sin((x / w) * layer.frequency * 2 * math.pi + phase * layer.speed) * layer.amplitude;
        path.lineTo(x, y);
      }

      path.lineTo(w, h); // bottom-right
      path.close();
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(covariant WavePainter oldDelegate) {
    return oldDelegate.animationValue != animationValue || oldDelegate.frontOnly != frontOnly;
  }
}
