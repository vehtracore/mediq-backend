import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:geolocator/geolocator.dart';
import 'package:geocoding/geocoding.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../../core/api/api_constants.dart';

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

  const _ServiceEntry({
    required this.label,
    required this.number,
    required this.icon,
    required this.color,
  });
}

// ─── Widget ───────────────────────────────────────────────────────────────────

class EmergencyScreen extends StatefulWidget {
  const EmergencyScreen({super.key});

  @override
  State<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends State<EmergencyScreen> {
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

  @override
  void initState() {
    super.initState();
    _determinePosition();
  }

  // ── Precision GPS fetch ─────────────────────────────────────────────────────
  Future<void> _determinePosition() async {
    try {
      // 1. Check location services are enabled on device
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        if (mounted) {
          setState(() {
            _locationMessage = 'Location services are disabled. Enable GPS and retry.';
            _gpsLoading = false;
          });
        }
        return;
      }

      // 2. Request / check permission
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          if (mounted) {
            setState(() {
              _locationMessage = 'Location permission denied. Enable it in Settings.';
              _gpsLoading = false;
            });
          }
          return;
        }
      }
      if (permission == LocationPermission.deniedForever) {
        if (mounted) {
          setState(() {
            _locationMessage = 'Location permission permanently denied. Open Settings to enable.';
            _gpsLoading = false;
          });
        }
        await Geolocator.openAppSettings();
        return;
      }

      // 3. Fetch a FRESH position from the hardware GPS chipset.
      //    • bestForNavigation = highest accuracy available
      //    • timeLimit: 15 s  → never blocks the UI indefinitely
      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.bestForNavigation,
        timeLimit: const Duration(seconds: 15),
      );

      _latitude  = position.latitude;
      _longitude = position.longitude;

      // 4. Reverse-geocode to a human-readable address (best-effort)
      String addressLabel =
          '${position.latitude.toStringAsFixed(4)}, ${position.longitude.toStringAsFixed(4)}';
      try {
        final placemarks = await placemarkFromCoordinates(
          position.latitude, position.longitude,
        );
        if (placemarks.isNotEmpty) {
          final p = placemarks.first;
          final parts = [p.subLocality, p.locality, p.administrativeArea]
              .where((s) => s != null && s.isNotEmpty)
              .toList();
          if (parts.isNotEmpty) addressLabel = parts.join(', ');
        }
      } catch (_) {
        // Geocoding failure is non-fatal — coordinates are still captured
      }

      if (mounted) {
        setState(() {
          _locationMessage = addressLabel;
          _gpsLoading = false;
        });
      }

      // 5. Fire backend SOS trigger silently (Next of Kin SMS / push)
      _sendEmergencyAlert(lat: position.latitude, lon: position.longitude);

      // 6. Fetch dynamic local services now that we have coordinates
      await _fetchLocalServices(
        lat: position.latitude,
        lon: position.longitude,
      );

    } on TimeoutException {
      // ── GPS Fallback Tier ────────────────────────────────────────────────
      // bestForNavigation timed out (common indoors). Retry with high accuracy
      // using Wi-Fi / cell towers for an approximate fix.
      debugPrint('[GPS] bestForNavigation timed out — falling back to high accuracy');
      try {
        final fallbackPosition = await Geolocator.getCurrentPosition(
          desiredAccuracy: LocationAccuracy.high,
        );
        _latitude  = fallbackPosition.latitude;
        _longitude = fallbackPosition.longitude;

        String addressLabel =
            '${fallbackPosition.latitude.toStringAsFixed(4)}, '
            '${fallbackPosition.longitude.toStringAsFixed(4)}';
        try {
          final placemarks = await placemarkFromCoordinates(
            fallbackPosition.latitude, fallbackPosition.longitude,
          );
          if (placemarks.isNotEmpty) {
            final p = placemarks.first;
            final parts = [p.subLocality, p.locality, p.administrativeArea]
                .where((s) => s != null && s.isNotEmpty)
                .toList();
            if (parts.isNotEmpty) addressLabel = parts.join(', ');
          }
        } catch (_) {}

        if (mounted) {
          setState(() {
            _locationMessage = '$addressLabel (approx.)';
            _gpsLoading = false;
          });
        }

        _sendEmergencyAlert(
            lat: fallbackPosition.latitude, lon: fallbackPosition.longitude);

        await _fetchLocalServices(
          lat: fallbackPosition.latitude,
          lon: fallbackPosition.longitude,
        );
      } catch (fallbackError) {
        if (mounted) {
          setState(() {
            _locationMessage = 'Location unavailable. Emergency buttons still work.';
            _gpsLoading = false;
            // No coordinates → show fallback buttons immediately
            _dynamicServices = [];
          });
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _locationMessage = 'Could not get location: ${e.toString()}';
          _gpsLoading = false;
          _dynamicServices = [];
        });
      }
    }
  }

  // ── Dynamic local-services fetch ────────────────────────────────────────────
  /// Calls GET /api/v1/emergency/local-services?lat=&lon= via a bare Dio
  /// instance (no auth interceptor — this is a public key-proxy endpoint).
  ///
  /// On ANY failure the method sets [_dynamicServices] to [] which causes
  /// the UI to render the hardcoded fallback buttons.
  Future<void> _fetchLocalServices({
    required double lat,
    required double lon,
  }) async {
    if (!mounted) return;
    setState(() => _servicesLoading = true);

    try {
      final dio = Dio(
        BaseOptions(
          baseUrl: ApiConstants.baseUrl,
          connectTimeout: const Duration(seconds: 8),
          receiveTimeout: const Duration(seconds: 10),
        ),
      );

      final response = await dio.get(
        '/api/v1/emergency/local-services',
        queryParameters: {'lat': lat, 'lon': lon},
      );

      // Backend always returns 200 with a list (possibly empty)
      final raw = response.data;
      if (raw is List && raw.isNotEmpty) {
        // Map the JSON objects to _ServiceEntry, cycling through icon/color
        // variants so buttons look visually distinct.
        final icons  = [Icons.local_hospital, Icons.local_police, Icons.medical_services, Icons.healing];
        final colors = [
          const Color(0xFFD32F2F), // red
          const Color(0xFF1565C0), // blue
          const Color(0xFF2E7D32), // green
          const Color(0xFF6A1B9A), // purple
          const Color(0xFFE65100), // orange
        ];

        final services = raw.asMap().entries.map((entry) {
          final i    = entry.key;
          final item = entry.value as Map<String, dynamic>;
          return _ServiceEntry(
            label:  (item['name'] as String? ?? 'Emergency Service').trim(),
            number: (item['phone_number'] as String? ?? '112').trim(),
            icon:   icons[i % icons.length],
            color:  colors[i % colors.length],
          );
        }).toList();

        if (mounted) {
          setState(() {
            _dynamicServices = services;
            _servicesLoading = false;
          });
        }
        debugPrint('[LOCAL-SERVICES] ✅ ${services.length} services loaded from API.');
        return;
      }

      // Empty list from API → fall through to fallback
      debugPrint('[LOCAL-SERVICES] ℹ️ API returned empty list — using fallback buttons.');
    } on DioException catch (e) {
      debugPrint('[LOCAL-SERVICES] ❌ Dio error: ${e.message} — using fallback buttons.');
    } catch (e) {
      debugPrint('[LOCAL-SERVICES] ❌ Unexpected error: $e — using fallback buttons.');
    }

    // Any failure path lands here
    if (mounted) {
      setState(() {
        _dynamicServices = []; // empty → _resolvedServices returns _kFallbackServices
        _servicesLoading = false;
      });
    }
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
  /// Backend handles Next of Kin SMS + push; we never block on the result.
  Future<void> _sendEmergencyAlert({
    required double lat,
    required double lon,
  }) async {
    try {
      final dio = Dio(BaseOptions(baseUrl: ApiConstants.baseUrl));

      const storage = FlutterSecureStorage();
      final token = await storage.read(
          key: 'auth_token',
          aOptions: const AndroidOptions(encryptedSharedPreferences: true));

      if (token != null) {
        dio.options.headers['Authorization'] = 'Bearer $token';
      }

      // Only forward a human-readable address — skip the loading placeholder
      // and generic error strings that are not meaningful to the backend.
      const _nonAddressStrings = {
        'Detecting location…',
        'Location unavailable. Emergency buttons still work.',
      };
      final String? addressToSend =
          (!_gpsLoading && !_nonAddressStrings.contains(_locationMessage))
              ? _locationMessage
              : null;

      await dio.post(
        '/api/v1/emergency/trigger',
        data: {
          'latitude': lat,
          'longitude': lon,
          if (addressToSend != null) 'address': addressToSend,
        },
      );
      debugPrint('[SOS] ✅ Alert fired — lat=$lat, lon=$lon, address=$addressToSend');
    } catch (e) {
      debugPrint('[SOS] ❌ Alert failed (non-fatal): $e');
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
            content: Text('Could not open dialler for $number. Please dial manually.'),
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
    final isDynamic = _dynamicServices != null && _dynamicServices!.isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (isDynamic)
          const Padding(
            padding: EdgeInsets.only(bottom: 12),
            child: _NearbyFoundBadge(),
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
