import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:geolocator/geolocator.dart';

import '../data/emergency_api.dart';
import '../data/emergency_location_service.dart';

// ─── Hardcoded fallback services ─────────────────────────────────────────────
// Shown when the API fails, times out, or returns an empty list.
// The user must NEVER be left without dialler buttons in an emergency.
const List<_ServiceEntry> _kFallbackServices = [
  _ServiceEntry(
    label: 'Local Emergency',
    number: '112',
    icon: Icons.local_police,
    color: Color(0xFF1565C0), // blue[800]
  ),
  _ServiceEntry(
    label: 'Ambulance',
    number: '112',
    icon: Icons.medical_services,
    color: Color(0xFFD32F2F), // red
  ),
  _ServiceEntry(
    label: 'Suicide Hotline',
    number: '09080601000',
    icon: Icons.support_agent,
    color: Color(0xFF6A1B9A), // purple
  ),
];

/// Lightweight model for a resolved emergency service.
class _ServiceEntry {
  final String label;
  final String number;
  final IconData icon;
  final Color color;
  final String category;

  const _ServiceEntry({
    required this.label,
    required this.number,
    required this.icon,
    required this.color,
    this.category = 'fallback',
  });
}

enum _NearbySearchState {
  waiting,
  loading,
  live,
  unavailable,
  empty,
  locationUnavailable,
}

// ─── Widget ───────────────────────────────────────────────────────────────────

class EmergencyScreen extends ConsumerStatefulWidget {
  final String? emergencyRequestId;

  const EmergencyScreen({super.key, this.emergencyRequestId});

  @override
  ConsumerState<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends ConsumerState<EmergencyScreen> {
  // ── Location state ──────────────────────────────────────────────────────────
  String _locationMessage = 'Detecting location…';
  // ignore: unused_field
  double? _latitude;
  // ignore: unused_field
  double? _longitude;

  // ── GPS loading gate — hides dialler buttons until position is known ────────
  bool _gpsLoading = true;

  // ── Dynamic services state ──────────────────────────────────────────────────
  /// null  = not yet fetched (GPS still resolving)
  /// []    = fetch returned empty / failed → show fallback
  /// [...]  = real data from Google Places proxy
  List<_ServiceEntry>? _dynamicServices;

  /// True while the /local-services HTTP call is in-flight.
  bool _servicesLoading = false;
  _NearbySearchState _searchState = _NearbySearchState.waiting;
  bool _alertAttempted = false;

  @override
  void initState() {
    super.initState();
    _determinePosition(triggerAlert: widget.emergencyRequestId != null);
  }

  // ── Precision GPS fetch ─────────────────────────────────────────────────────
  Future<void> _determinePosition({required bool triggerAlert}) async {
    if (mounted) {
      setState(() {
        _gpsLoading = true;
        _servicesLoading = false;
        _dynamicServices = null;
        _searchState = _NearbySearchState.waiting;
        _locationMessage = 'Detecting location…';
      });
    }
    try {
      final locationService = ref.read(emergencyLocationProvider);
      // 1. Check location services are enabled on device
      final serviceEnabled = await locationService.isServiceEnabled();
      if (!serviceEnabled) {
        _setLocationUnavailable(
            'Location services are disabled. Enable GPS and retry.');
        return;
      }

      // 2. Request / check permission
      LocationPermission permission = await locationService.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await locationService.requestPermission();
        if (permission == LocationPermission.denied) {
          _setLocationUnavailable(
              'Location permission denied. Enable it in Settings.');
          return;
        }
      }
      if (permission == LocationPermission.deniedForever) {
        _setLocationUnavailable(
          'Location permission permanently denied. Open Settings to enable.',
        );
        await locationService.openAppSettings();
        return;
      }

      // 3. Fetch a FRESH position from the hardware GPS chipset.
      //    • bestForNavigation = highest accuracy available
      //    • timeLimit: 15 s  → never blocks the UI indefinitely
      final position = await locationService.currentPosition(
        accuracy: LocationAccuracy.bestForNavigation,
        timeLimit: const Duration(seconds: 15),
      );

      _onPositionResolved(
        position,
        approximate: false,
        triggerAlert: triggerAlert,
      );
    } on TimeoutException {
      // ── GPS Fallback Tier ────────────────────────────────────────────────
      // bestForNavigation timed out (common indoors). Retry with high accuracy
      // using Wi-Fi / cell towers for an approximate fix.
      debugPrint(
          '[GPS] bestForNavigation timed out — falling back to high accuracy');
      try {
        final fallbackPosition =
            await ref.read(emergencyLocationProvider).currentPosition(
                  accuracy: LocationAccuracy.high,
                  timeLimit: const Duration(seconds: 10),
                );
        _onPositionResolved(
          fallbackPosition,
          approximate: true,
          triggerAlert: triggerAlert,
        );
      } catch (fallbackError) {
        _setLocationUnavailable(
            'Location unavailable. Emergency contacts are shown.');
      }
    } catch (e) {
      _setLocationUnavailable(
          'Location unavailable. Emergency contacts are shown.');
    }
  }

  void _setLocationUnavailable(String message) {
    if (!mounted) return;
    setState(() {
      _locationMessage = message;
      _gpsLoading = false;
      _servicesLoading = false;
      _dynamicServices = [];
      _searchState = _NearbySearchState.locationUnavailable;
    });
  }

  void _onPositionResolved(
    Position position, {
    required bool approximate,
    required bool triggerAlert,
  }) {
    _latitude = position.latitude;
    _longitude = position.longitude;
    final coordinateLabel =
        '${position.latitude.toStringAsFixed(4)}, ${position.longitude.toStringAsFixed(4)}';
    if (mounted) {
      setState(() {
        _locationMessage =
            approximate ? '$coordinateLabel (approx.)' : coordinateLabel;
        _gpsLoading = false;
      });
    }

    final addressFuture = _resolveAddress(position).timeout(
      const Duration(seconds: 5),
      onTimeout: () => null,
    );
    unawaited(_applyResolvedAddress(addressFuture, approximate: approximate));
    unawaited(
        _fetchLocalServices(lat: position.latitude, lon: position.longitude));

    if (triggerAlert && !_alertAttempted && widget.emergencyRequestId != null) {
      _alertAttempted = true;
      unawaited(_sendEmergencyAlert(
        lat: position.latitude,
        lon: position.longitude,
        addressFuture: addressFuture,
        requestId: widget.emergencyRequestId!,
      ));
    }
  }

  Future<String?> _resolveAddress(Position position) async {
    return ref.read(emergencyLocationProvider).resolveAddress(position);
  }

  Future<void> _applyResolvedAddress(
    Future<String?> addressFuture, {
    required bool approximate,
  }) async {
    final address = await addressFuture;
    if (!mounted || address == null) return;
    setState(() {
      _locationMessage = approximate ? '$address (approx.)' : address;
    });
  }

  // ── Dynamic local-services fetch ────────────────────────────────────────────
  /// Calls the authenticated backend proxy and keeps failure states distinct.
  Future<void> _fetchLocalServices({
    required double lat,
    required double lon,
  }) async {
    if (!mounted) return;
    setState(() {
      _servicesLoading = true;
      _searchState = _NearbySearchState.loading;
    });

    final result = await ref.read(emergencyApiProvider).searchNearby(
          latitude: lat,
          longitude: lon,
        );
    if (!mounted) return;

    final services = result.services.map((item) {
      final isHospital = item.category == 'hospital';
      return _ServiceEntry(
        label: item.name,
        number: item.phoneNumber,
        category: item.category,
        icon: isHospital ? Icons.local_hospital : Icons.local_police,
        color: isHospital ? const Color(0xFFD32F2F) : const Color(0xFF1565C0),
      );
    }).toList(growable: false);

    setState(() {
      _dynamicServices = services;
      _servicesLoading = false;
      _searchState = switch (result.status) {
        NearbySearchStatus.success when services.isNotEmpty =>
          _NearbySearchState.live,
        NearbySearchStatus.empty => _NearbySearchState.empty,
        _ => _NearbySearchState.unavailable,
      };
    });
  }

  /// Returns the list that the UI should render.
  /// Null means GPS hasn't resolved yet (show skeleton).
  /// Empty list means use fallback constants.
  List<_ServiceEntry>? get _resolvedServices {
    if (_dynamicServices == null) return null;
    if (_dynamicServices!.isEmpty) return _kFallbackServices;
    return _dynamicServices;
  }

  // ── SOS backend trigger ─────────────────────────────────────────────────────
  /// Fires POST /api/v1/emergency/trigger.
  /// Backend handles the Next of Kin SMS; nearby search never awaits it.
  Future<void> _sendEmergencyAlert({
    required double lat,
    required double lon,
    required Future<String?> addressFuture,
    required String requestId,
  }) async {
    try {
      final address = await addressFuture;
      await ref.read(emergencyApiProvider).requestNextOfKinAlert(
            latitude: lat,
            longitude: lon,
            address: address,
            requestId: requestId,
          );
      debugPrint('[SOS] Next-of-kin alert request accepted.');
    } catch (_) {
      debugPrint('[SOS] Next-of-kin alert request failed (non-fatal).');
    }
  }

  void _retryNearbySearch() {
    if (_servicesLoading) return;
    final lat = _latitude;
    final lon = _longitude;
    if (lat != null && lon != null) {
      unawaited(_fetchLocalServices(lat: lat, lon: lon));
    } else {
      unawaited(_determinePosition(triggerAlert: false));
    }
  }

  // ── Dialler ─────────────────────────────────────────────────────────────────
  /// Opens the native phone dialler. Uses externalApplication so Android
  /// routes to the dialler activity rather than an in-app handler.
  Future<void> _callNumber(String number) async {
    final Uri dialUri = Uri(scheme: 'tel', path: number);
    if (await canLaunchUrl(dialUri)) {
      await launchUrl(dialUri, mode: LaunchMode.externalApplication);
    } else {
      debugPrint('[DIALER] ❌ Could not launch $dialUri');
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
                'Could not open dialler for $number. Please dial manually.'),
            backgroundColor: Colors.red[700],
            behavior: SnackBarBehavior.floating,
          ),
        );
      }
    }
  }

  // ── Build ────────────────────────────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor,
      appBar: AppBar(
        title: const Text('Emergency',
            style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.redAccent,
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () => context.pop(),
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // ── Location card ──────────────────────────────────────────────
            _LocationCard(
              loading: _gpsLoading,
              message: _locationMessage,
            ),

            const SizedBox(height: 28),

            Text(
              'Immediate Assistance',
              style: theme.textTheme.titleLarge
                  ?.copyWith(fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 14),

            // ── Services list ──────────────────────────────────────────────
            _buildServicesList(theme),

            // Bottom breathing room
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  /// Renders the dynamic or fallback service buttons.
  Widget _buildServicesList(ThemeData theme) {
    // Still waiting for GPS → show a subtle loading skeleton
    if (_gpsLoading || (_resolvedServices == null && _servicesLoading)) {
      return _ServicesLoadingSkeleton();
    }

    // Services loading indicator (GPS done, API in-flight)
    if (_servicesLoading) {
      return Column(
        children: [
          const Align(
            alignment: Alignment.centerLeft,
            child: _NearbyLoadingBadge(),
          ),
          const SizedBox(height: 12),
          _ServicesLoadingSkeleton(),
        ],
      );
    }

    final services = _resolvedServices ?? _kFallbackServices;
    final isDynamic = _searchState == _NearbySearchState.live;
    final fallbackMessage = switch (_searchState) {
      _NearbySearchState.empty =>
        'No nearby services found within 5 km. Showing emergency contacts.',
      _NearbySearchState.locationUnavailable =>
        'Location unavailable. Showing emergency contacts.',
      _ => 'Nearby search unavailable. Showing emergency contacts.',
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (isDynamic)
          const Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: _NearbyFoundBadge(),
          ),
        if (!isDynamic)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _FallbackNotice(
              message: fallbackMessage,
              onRetry: _retryNearbySearch,
            ),
          ),
        ...services.asMap().entries.map((entry) {
          final service = entry.value;
          return Padding(
            padding: EdgeInsets.only(
              bottom: entry.key < services.length - 1 ? 14 : 0,
            ),
            child: _buildEmergencyCard(
              context,
              icon: service.icon,
              label: service.label,
              subLabel: 'Tap to call ${service.number}',
              color: service.color,
              onTap: () => _callNumber(service.number),
            ),
          );
        }),
      ],
    );
  }

  // ── Card widget ──────────────────────────────────────────────────────────────
  Widget _buildEmergencyCard(
    BuildContext context, {
    required IconData icon,
    required String label,
    required String subLabel,
    required Color color,
    required VoidCallback onTap,
  }) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: isDark ? theme.cardTheme.color : color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: color.withValues(alpha: 0.3)),
        ),
        child: Row(
          children: [
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: color, shape: BoxShape.circle),
              child: Icon(icon, color: Colors.white, size: 24),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    label,
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                      color: isDark ? Colors.white : color,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subLabel,
                    style: TextStyle(
                      fontSize: 12,
                      color: isDark ? Colors.grey[400] : Colors.grey[600],
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.arrow_forward_ios, size: 16, color: color),
          ],
        ),
      ),
    );
  }
}

// ─── Sub-widgets ──────────────────────────────────────────────────────────────

class _LocationCard extends StatelessWidget {
  final bool loading;
  final String message;

  const _LocationCard({required this.loading, required this.message});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.red.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: Colors.red.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.location_on, color: Colors.red),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Your Current Location',
                  style: TextStyle(
                    color: Colors.red,
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(height: 4),
                loading
                    ? const SizedBox(
                        height: 14,
                        width: 14,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.red,
                        ),
                      )
                    : Text(
                        message,
                        style: theme.textTheme.bodyMedium
                            ?.copyWith(fontWeight: FontWeight.bold),
                      ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// Pulsing shimmer placeholder shown while services are loading.
class _ServicesLoadingSkeleton extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Column(
      children: List.generate(3, (i) {
        return Padding(
          padding: EdgeInsets.only(bottom: i < 2 ? 14 : 0),
          child: Container(
            height: 80,
            decoration: BoxDecoration(
              color: Colors.grey.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.grey.withValues(alpha: 0.15)),
            ),
          ),
        );
      }),
    );
  }
}

/// Small badge shown while the API call is in-flight.
class _NearbyLoadingBadge extends StatelessWidget {
  const _NearbyLoadingBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.orange.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 10,
            height: 10,
            child: CircularProgressIndicator(
              strokeWidth: 1.5,
              color: Colors.orange,
            ),
          ),
          const SizedBox(width: 6),
          Text(
            'Finding nearby services…',
            style: TextStyle(
              fontSize: 11,
              color: Colors.orange[800],
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

/// Badge shown once dynamic results arrive.
class _NearbyFoundBadge extends StatelessWidget {
  const _NearbyFoundBadge();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: Colors.green.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: Colors.green.withValues(alpha: 0.3)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.location_searching, size: 12, color: Colors.green),
          const SizedBox(width: 6),
          Text(
            'Nearby services found',
            style: TextStyle(
              fontSize: 11,
              color: Colors.green[800],
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _FallbackNotice extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _FallbackNotice({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.orange.withValues(alpha: 0.3)),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline, size: 18, color: Colors.orange),
          const SizedBox(width: 8),
          Expanded(
            child: Text(message, style: theme.textTheme.bodySmall),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
