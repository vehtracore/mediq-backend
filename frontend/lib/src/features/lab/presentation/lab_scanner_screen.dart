import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:permission_handler/permission_handler.dart';
import '../data/lab_result_model.dart';
import 'lab_controller.dart';

class LabScannerScreen extends ConsumerStatefulWidget {
  const LabScannerScreen({super.key});

  @override
  ConsumerState<LabScannerScreen> createState() => _LabScannerScreenState();
}

class _LabScannerScreenState extends ConsumerState<LabScannerScreen>
    with WidgetsBindingObserver {
  CameraController? _controller;
  Future<void>? _initializeControllerFuture;
  bool _isCameraInitialized = false;
  bool _isCameraMode = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // Camera is NOT initialized here — user chooses source first
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _controller?.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final CameraController? cameraController = _controller;

    // App state changed before we got the chance to initialize.
    if (cameraController == null || !cameraController.value.isInitialized) {
      return;
    }

    if (state == AppLifecycleState.inactive) {
      cameraController.dispose();
    } else if (state == AppLifecycleState.resumed) {
      if (_isCameraMode) _initCamera();
    }
  }

  Future<void> _initCamera() async {
    var status = await Permission.camera.request();
    if (status != PermissionStatus.granted) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
              content: Text('Camera permission is required to scan.')),
        );
        setState(() => _isCameraMode = false);
      }
      return;
    }

    final cameras = await availableCameras();
    if (cameras.isEmpty) return;

    final firstCamera = cameras.first;

    _controller = CameraController(
      firstCamera,
      ResolutionPreset.high,
      enableAudio: false,
    );

    _initializeControllerFuture = _controller!.initialize().then((_) {
      if (!mounted) return;
      setState(() {
        _isCameraInitialized = true;
      });
      _controller!.setFlashMode(FlashMode.off);
    }).catchError((Object e) {
      if (e is CameraException) {
        switch (e.code) {
          case 'CameraAccessDenied':
            // Access denied
            break;
          default:
            // Other errors
            break;
        }
      }
    });
  }

  Future<void> _takePicture() async {
    try {
      await _initializeControllerFuture;

      final image = await _controller!.takePicture();

      // Trigger logic
      await ref.read(labControllerProvider.notifier).analyzeImage(image);

      _checkResult();
    } catch (e) {
      debugPrint('[LabScanner] capture error: $e');
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Unable to capture the image. Please try again.'),
        ),
      );
    }
  }

  void _checkResult() {
    final state = ref.read(labControllerProvider);

    if (state.errorMessage != null) {
      _showErrorDialog(state.errorMessage!);
    } else if (state.result != null && state.result!.status == 'SUCCESS') {
      _showSuccessDialog(state.result!);
    } else if (state.result != null && state.result!.status == 'REJECTED') {
      _showErrorDialog(state.result!.reason ?? "Image rejected by AI.");
    }
  }

  void _showErrorDialog(String message) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text("Scan Issue"),
        content: Text(message),
        actions: [
          TextButton(
            onPressed: () {
              ref.read(labControllerProvider.notifier).reset();
              Navigator.pop(ctx);
            },
            child: const Text("Try Again"),
          )
        ],
      ),
    );
  }

  void _showSuccessDialog(LabAnalysisResponse result) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => Container(
        height: MediaQuery.of(context).size.height * 0.7,
        decoration: const BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
        ),
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
                child: Container(
                    width: 40,
                    height: 5,
                    decoration: BoxDecoration(
                        color: Colors.grey[300],
                        borderRadius: BorderRadius.circular(10)))),
            const SizedBox(height: 20),
            const Row(
              children: [
                Icon(Icons.check_circle, color: Colors.green, size: 28),
                SizedBox(width: 10),
                Text("Scan Successful",
                    style:
                        TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              ],
            ),
            const SizedBox(height: 10),
            Text("Lighting Score: ${result.lightingScore}",
                style: const TextStyle(color: Colors.grey)),
            const Divider(),
            Expanded(
              child: ListView(
                children: [
                  _buildResultItem(
                      "Leukocytes", result.readings?.leukocytes?.value),
                  _buildResultItem(
                      "Nitrites", result.readings?.nitrites?.value),
                  _buildResultItem("Protein", result.readings?.protein?.value),
                  _buildResultItem("pH", result.readings?.ph?.value),
                  _buildResultItem("Blood", result.readings?.blood?.value),
                  _buildResultItem("Glucose", result.readings?.glucose?.value),
                  _buildResultItem("Ketones", result.readings?.ketones?.value),
                ],
              ),
            ),
            const SizedBox(height: 20),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: () {
                      ref.read(labControllerProvider.notifier).reset();
                      Navigator.pop(context);
                    },
                    child: const Text("Retake"),
                  ),
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: ElevatedButton(
                    onPressed: () {
                      Navigator.pop(context); // Close bottom sheet

                      // Return result to previous screen (Chat)
                      context.pop(result);
                    },
                    style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFF0D47A1)),
                    child: const Text("Confirm & Save",
                        style: TextStyle(color: Colors.white)),
                  ),
                ),
              ],
            )
          ],
        ),
      ),
    );
  }

  Widget _buildResultItem(String label, String? value) {
    if (value == null) return const SizedBox.shrink();

    // Simple highlight logic
    bool isAbnormal = !['Negative', 'Normal'].contains(value) &&
        !value.startsWith('1.0') && // Specific Gravity
        !['5.0', '5.5', '6.0', '6.5', '7.0'].contains(value); // pH common range

    return ListTile(
      title: Text(label, style: const TextStyle(fontWeight: FontWeight.w500)),
      trailing: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          color: isAbnormal ? Colors.red[50] : Colors.green[50],
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: isAbnormal ? Colors.red : Colors.green),
        ),
        child: Text(
          value,
          style: TextStyle(
            color: isAbnormal ? Colors.red[900] : Colors.green[900],
            fontWeight: FontWeight.bold,
          ),
        ),
      ),
    );
  }

  Future<void> _pickAndAnalyzeImage(ImageSource source) async {
    final picker = ImagePicker();
    final pickedFile = await picker.pickImage(
      source: source,
      imageQuality: 90,
      maxWidth: 1920,
      maxHeight: 1920,
    );
    if (pickedFile != null) {
      await ref.read(labControllerProvider.notifier).analyzeImage(pickedFile);
      _checkResult();
    }
  }

  // ──────────────────────────────────────────────
  //  BUILD
  // ──────────────────────────────────────────────
  @override
  Widget build(BuildContext context) {
    final labState = ref.watch(labControllerProvider);

    // ── Source-choice screen (default) ──
    if (!_isCameraMode) {
      return Scaffold(
        backgroundColor: const Color(0xFF0A1628),
        appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          foregroundColor: Colors.white,
          title: const Text("Lab Strip Scanner"),
        ),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Icon(Icons.science_outlined,
                    size: 80, color: Colors.blueAccent),
                const SizedBox(height: 24),
                Text(
                  "How would you like to scan?",
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.bold,
                      ),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 8),
                Text(
                  "Choose a urine test strip image source",
                  style: TextStyle(color: Colors.grey[400], fontSize: 14),
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 40),

                // ── Gallery button ──
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: ElevatedButton.icon(
                    icon: const Icon(Icons.photo_library, size: 24),
                    label: const Text("Upload from Gallery",
                        style: TextStyle(fontSize: 16)),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.blueAccent,
                      foregroundColor: Colors.white,
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16)),
                    ),
                    onPressed: labState.isLoading
                        ? null
                        : () => _pickAndAnalyzeImage(ImageSource.gallery),
                  ),
                ),
                const SizedBox(height: 16),

                // ── Camera button ──
                SizedBox(
                  width: double.infinity,
                  height: 56,
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.camera_alt, size: 24),
                    label: const Text("Capture with Scanner",
                        style: TextStyle(fontSize: 16)),
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Colors.white,
                      side: const BorderSide(
                          color: Colors.blueAccent, width: 1.5),
                      shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16)),
                    ),
                    onPressed: labState.isLoading
                        ? null
                        : () {
                            setState(() => _isCameraMode = true);
                            _initCamera();
                          },
                  ),
                ),

                if (labState.isLoading) ...[
                  const SizedBox(height: 24),
                  const CircularProgressIndicator(color: Colors.blueAccent),
                  const SizedBox(height: 12),
                  Text("Analyzing strip...",
                      style: TextStyle(color: Colors.grey[400])),
                ],
              ],
            ),
          ),
        ),
      );
    }

    // ── Camera loading spinner ──
    if (!_isCameraInitialized) {
      return const Scaffold(
        backgroundColor: Colors.black,
        body: Center(child: CircularProgressIndicator(color: Colors.white)),
      );
    }

    // ── Camera mode (existing scanner UI) ──
    return Scaffold(
      backgroundColor: Colors.black,
      body: Stack(
        fit: StackFit.expand,
        children: [
          // 1. Camera Preview
          CameraPreview(_controller!),

          // 2. Overlay (Dark background with transparent cutoff)
          ColorFiltered(
            colorFilter: const ColorFilter.mode(
              Colors.black54,
              BlendMode.srcOut,
            ),
            child: Stack(
              fit: StackFit.expand,
              children: [
                // The "Hole"
                Container(
                  decoration: const BoxDecoration(
                    color: Colors.black,
                    backgroundBlendMode: BlendMode.dstOut,
                  ),
                ),
                Center(
                  child: Container(
                    width: 300,
                    height: 500,
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(20),
                    ),
                  ),
                ),
              ],
            ),
          ),

          // 3. UI Layer (Text Instructions & Green Border)
          SafeArea(
            child: Column(
              children: [
                const SizedBox(height: 60),
                const Text(
                  "Align Strip Here",
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 22,
                    fontWeight: FontWeight.bold,
                    shadows: [Shadow(color: Colors.black, blurRadius: 4)],
                  ),
                ),
                const SizedBox(height: 8),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Text(
                    "Ensure good lighting & white background",
                    style: TextStyle(color: Colors.white, fontSize: 14),
                  ),
                ),
                Expanded(
                  child: Center(
                    child: Container(
                      width: 304, // Slightly larger than hole
                      height: 504,
                      decoration: BoxDecoration(
                          border:
                              Border.all(color: Colors.greenAccent, width: 3),
                          borderRadius: BorderRadius.circular(22),
                          boxShadow: [
                            BoxShadow(
                              color: Colors.greenAccent.withValues(alpha: 0.3),
                              blurRadius: 10,
                              spreadRadius: 2,
                            )
                          ]),
                    ),
                  ),
                ),
                const SizedBox(height: 100),
              ],
            ),
          ),

          // 4. Controls
          Positioned(
            bottom: 40,
            left: 0,
            right: 0,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                // Back to source choice
                IconButton(
                  onPressed: () {
                    _controller?.dispose();
                    setState(() {
                      _isCameraMode = false;
                      _isCameraInitialized = false;
                      _controller = null;
                    });
                  },
                  icon: const Icon(Icons.arrow_back,
                      color: Colors.white, size: 32),
                ),

                // Shutter Button — captures with existing camera
                GestureDetector(
                  onTap: labState.isLoading ? null : _takePicture,
                  child: Container(
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 4),
                      color: labState.isLoading ? Colors.grey : Colors.white24,
                    ),
                    child: labState.isLoading
                        ? const Padding(
                            padding: EdgeInsets.all(16.0),
                            child: CircularProgressIndicator(
                                color: Colors.white, strokeWidth: 3),
                          )
                        : Container(
                            margin: const EdgeInsets.all(8),
                            decoration: const BoxDecoration(
                              shape: BoxShape.circle,
                              color: Colors.white,
                            ),
                          ),
                  ),
                ),

                // Flash Toggle
                IconButton(
                  onPressed: () async {
                    if (_controller!.value.flashMode == FlashMode.off) {
                      await _controller!.setFlashMode(FlashMode.torch);
                    } else {
                      await _controller!.setFlashMode(FlashMode.off);
                    }
                    setState(() {});
                  },
                  icon: Icon(
                      _controller?.value.flashMode == FlashMode.torch
                          ? Icons.flash_on
                          : Icons.flash_off,
                      color: Colors.white,
                      size: 32),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
