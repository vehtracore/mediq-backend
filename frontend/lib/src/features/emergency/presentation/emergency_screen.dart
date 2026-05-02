import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:geolocator/geolocator.dart';
import 'package:geocoding/geocoding.dart';


class EmergencyScreen extends StatefulWidget {
  const EmergencyScreen({super.key});

  @override
  State<EmergencyScreen> createState() => _EmergencyScreenState();
}

class _EmergencyScreenState extends State<EmergencyScreen> {
  String _locationMessage = "Detecting location…";
  double? _latitude;
  double? _longitude;
  final String _localEmergencyNumber = "112";
  final String _localEmergencyLabel = "Local Emergency";
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _determinePosition();
  }

  // ── Precision GPS fetch ────────────────────────────────────────────────────
  Future<void> _determinePosition() async {
    try {
      // 1. Check location services are enabled on device
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        if (mounted) setState(() {
          _locationMessage = "Location services are disabled. Enable GPS and retry.";
          _loading = false;
        });
        return;
      }

      // 2. Request / check permission
      LocationPermission permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
        if (permission == LocationPermission.denied) {
          if (mounted) setState(() {
            _locationMessage = "Location permission denied. Enable it in Settings.";
            _loading = false;
          });
          return;
        }
      }
      if (permission == LocationPermission.deniedForever) {
        if (mounted) setState(() {
          _locationMessage = "Location permission permanently denied. Open Settings to enable.";
          _loading = false;
        });
        await Geolocator.openAppSettings();
        return;
      }

      // 3. Fetch a FRESH position from the hardware GPS chipset.
      //    • bestForNavigation = highest accuracy available (equiv. kCLLocationAccuracyBestForNavigation on iOS)
      //    • forceAndroidLocationManager: false  → uses Google Fused provider which
      //      automatically selects GPS hardware when FINE permission is granted
      //    • timeLimit: 15s  → never blocks the UI thread indefinitely
      final position = await Geolocator.getCurrentPosition(
        desiredAccuracy: LocationAccuracy.bestForNavigation,
        timeLimit: const Duration(seconds: 15),
      );

      _latitude  = position.latitude;
      _longitude = position.longitude;

      // 4. Reverse-geocode to a human-readable address (best-effort)
      String addressLabel = "${position.latitude.toStringAsFixed(4)}, ${position.longitude.toStringAsFixed(4)}";
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

      if (mounted) setState(() {
        _locationMessage = addressLabel;
        _loading = false;
      });

      // 5. Fire backend SOS trigger (runs silently in background)
      _sendEmergencyAlert(lat: position.latitude, lon: position.longitude);

    } on TimeoutException {
      if (mounted) setState(() {
        _locationMessage = "GPS timed out. Check signal and retry.";
        _loading = false;
      });
    } catch (e) {
      if (mounted) setState(() {
        _locationMessage = "Could not get location: ${e.toString()}";
        _loading = false;
      });
    }
  }

  /// Fires POST /api/v1/emergency/trigger with coordinates.
  /// Runs silently — backend handles Next of Kin SMS + push notifications.
  Future<void> _sendEmergencyAlert({required double lat, required double lon}) async {
    try {
      // TODO: inject your Dio instance and call the real endpoint:
      // await dio.post('/api/v1/emergency/trigger', data: {'latitude': lat, 'longitude': lon});
      debugPrint('[SOS] Alert fired — lat=$lat, lon=$lon');
    } catch (e) {
      debugPrint('[SOS] Alert failed: $e');
    }
  }

  void _callNumber(String number) async {
    final Uri launchUri = Uri(scheme: 'tel', path: number);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: theme.scaffoldBackgroundColor, // ✅ Dynamic
      appBar: AppBar(
        title: const Text("Emergency",
            style: TextStyle(fontWeight: FontWeight.bold)),
        backgroundColor: Colors.redAccent,
        foregroundColor: Colors.white,
        leading: IconButton(
          icon: const Icon(Icons.close),
          onPressed: () => context.pop(),
        ),
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: Colors.red.withOpacity(0.1),
                borderRadius: BorderRadius.circular(16),
                border: Border.all(color: Colors.red.withOpacity(0.3)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.location_on, color: Colors.red),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text("Your Current Location",
                            style: TextStyle(
                                color: Colors.red,
                                fontSize: 12,
                                fontWeight: FontWeight.bold)),
                        const SizedBox(height: 4),
                        _loading
                            ? const SizedBox(
                                height: 10,
                                width: 10,
                                child:
                                    CircularProgressIndicator(strokeWidth: 2))
                            : Text(_locationMessage,
                                style: theme.textTheme.bodyLarge?.copyWith(
                                    fontWeight: FontWeight.bold)), // ✅ Dynamic
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 32),
            Text("Immediate Assistance",
                style: theme.textTheme.titleLarge
                    ?.copyWith(fontWeight: FontWeight.bold)), // ✅ Dynamic
            const SizedBox(height: 16),
            _buildEmergencyCard(
              context,
              icon: Icons.local_police,
              label: _localEmergencyLabel,
              subLabel: "Tap to call $_localEmergencyNumber",
              color: Colors.blue[800]!,
              onTap: () => _callNumber(_localEmergencyNumber),
            ),
            const SizedBox(height: 16),
            _buildEmergencyCard(
              context,
              icon: Icons.medical_services,
              label: "Ambulance",
              subLabel: "Tap to call 112",
              color: Colors.red,
              onTap: () => _callNumber("112"),
            ),
            const SizedBox(height: 16),
            _buildEmergencyCard(
              context,
              icon: Icons.support_agent,
              label: "Suicide Hotline",
              subLabel: "Tap to call 09080601000",
              color: Colors.purple,
              onTap: () => _callNumber("09080601000"),
            ),
          ],
        ),
      ),
    );
  }

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
          // ✅ Dynamic Card Background
          color: isDark ? theme.cardTheme.color : color.withOpacity(0.08),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: color.withOpacity(0.3)),
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
                      color: isDark ? Colors.white : color, // ✅ Dynamic Text
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subLabel,
                    style: TextStyle(
                        fontSize: 12,
                        color: isDark
                            ? Colors.grey[400]
                            : Colors.grey[600]), // ✅ Dynamic
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
