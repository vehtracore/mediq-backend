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
  String _locationMessage = "Detecting location...";
  String _localEmergencyNumber = "112"; // Default National
  String _localEmergencyLabel = "Local Emergency";
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _determinePosition();
  }

  Future<void> _determinePosition() async {
    bool serviceEnabled;
    LocationPermission permission;

    // 1. Check Services
    serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      if (mounted)
        setState(() {
          _locationMessage = "Location services disabled.";
          _loading = false;
        });
      return;
    }

    permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        if (mounted)
          setState(() {
            _locationMessage = "Location permission denied.";
            _loading = false;
          });
        return;
      }
    }

    if (permission == LocationPermission.deniedForever) {
      if (mounted)
        setState(() {
          _locationMessage = "Location permission permanently denied.";
          _loading = false;
        });
      return;
    }

    // 2. Get Position
    try {
      Position position = await Geolocator.getCurrentPosition();

      // 3. Reverse Geocode (Get State)
      List<Placemark> placemarks = await placemarkFromCoordinates(
        position.latitude,
        position.longitude,
      );
      if (placemarks.isNotEmpty) {
        Placemark place = placemarks[0];
        String state = place.administrativeArea ?? "Unknown";

        if (mounted) {
          setState(() {
            _locationMessage = "📍 Detected: $state";
            _updateEmergencyNumber(state);
            _loading = false;
          });
        }
      }
    } catch (e) {
      if (mounted)
        setState(() {
          _locationMessage = "Could not determine location.";
          _loading = false;
        });
    }
  }

  void _updateEmergencyNumber(String state) {
    if (state.contains("Lagos")) {
      _localEmergencyNumber = "767";
      _localEmergencyLabel = "Lagos Emergency (767)";
    } else if (state.contains("FCT") || state.contains("Abuja")) {
      _localEmergencyNumber = "112";
      _localEmergencyLabel = "FCT Emergency (112)";
    } else if (state.contains("Rivers")) {
      _localEmergencyNumber = "112";
      _localEmergencyLabel = "Rivers Emergency (112)";
    } else {
      _localEmergencyNumber = "112";
      _localEmergencyLabel = "National Emergency (112)";
    }
  }

  Future<void> _makeCall(String number) async {
    final Uri launchUri = Uri(scheme: 'tel', path: number);
    if (await canLaunchUrl(launchUri)) {
      await launchUrl(launchUri);
    } else {
      debugPrint("Could not launch dialer");
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.white,
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.close, color: Colors.black),
          onPressed: () => context.pop(),
        ),
        backgroundColor: Colors.white,
        elevation: 0,
        title: const Text(
          "Emergency Support",
          style: TextStyle(color: Colors.black, fontWeight: FontWeight.bold),
        ),
        centerTitle: true,
      ),
      body: Padding(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Container(
              padding: const EdgeInsets.all(30),
              decoration: BoxDecoration(
                color: const Color(0xFF4A90E2).withOpacity(0.1),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.support_agent_rounded,
                size: 80,
                color: Color(0xFF4A90E2),
              ),
            ),
            const SizedBox(height: 32),

            const Text(
              "We are here to help",
              style: TextStyle(
                fontSize: 24,
                fontWeight: FontWeight.bold,
                color: Color(0xFF2D3436),
              ),
            ),
            const SizedBox(height: 12),
            Text(
              _locationMessage,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 16,
                color: Colors.grey[600],
                height: 1.5,
              ),
            ),

            if (_loading) ...[
              const SizedBox(height: 16),
              const CircularProgressIndicator(),
            ],

            const SizedBox(height: 48),

            // Local Button
            _buildEmergencyButton(
              label: _localEmergencyLabel,
              subLabel: "Dispatch for your current location",
              icon: Icons.location_on_outlined,
              color: const Color(0xFF00CEC9),
              onTap: () => _makeCall(_localEmergencyNumber),
            ),
            const SizedBox(height: 16),

            // National Button
            _buildEmergencyButton(
              label: "Call National (112)",
              subLabel: "Police, Fire, Ambulance",
              // FIXED ICON
              icon: Icons.medical_services_outlined,
              color: const Color(0xFF4A90E2),
              onTap: () => _makeCall("112"),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmergencyButton({
    required String label,
    required String subLabel,
    required IconData icon,
    required Color color,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(20),
        decoration: BoxDecoration(
          color: color.withOpacity(0.08),
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
                      color: color,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subLabel,
                    style: TextStyle(fontSize: 12, color: Colors.grey[600]),
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
