import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../../content/data/content_repository.dart';
import 'package:mediq_app/src/features/chat/data/image_upload_service.dart';

class AdminContentEditorScreen extends ConsumerStatefulWidget {
  final HealthTip? healthTip; // If null, we are creating. If exists, editing.

  const AdminContentEditorScreen({super.key, this.healthTip});

  @override
  ConsumerState<AdminContentEditorScreen> createState() =>
      _AdminContentEditorScreenState();
}

class _AdminContentEditorScreenState
    extends ConsumerState<AdminContentEditorScreen> {
  final _formKey = GlobalKey<FormState>();

  late TextEditingController _titleCtrl;
  late TextEditingController _catCtrl;
  late TextEditingController _timeCtrl;
  late TextEditingController _contentCtrl;
  late TextEditingController _externalLinkCtrl;
  String? _imgUrl;
  bool _isLoading = false;
  bool _isUploadingImage = false;

  @override
  void initState() {
    super.initState();
    final tip = widget.healthTip;
    _titleCtrl = TextEditingController(text: tip?.title ?? "");
    _catCtrl = TextEditingController(text: tip?.category ?? "");
    _timeCtrl = TextEditingController(text: tip?.readTime ?? "");
    _contentCtrl = TextEditingController(text: tip?.content ?? "");
    _externalLinkCtrl = TextEditingController(text: tip?.externalLink ?? "");
    _imgUrl = tip?.imageUrl;
  }

  @override
  void dispose() {
    _titleCtrl.dispose();
    _catCtrl.dispose();
    _timeCtrl.dispose();
    _contentCtrl.dispose();
    _externalLinkCtrl.dispose();
    super.dispose();
  }

  Future<void> _pickAndUploadImage() async {
    setState(() => _isUploadingImage = true);
    try {
      final url =
          await ref.read(imageUploadServiceProvider).pickAndUploadImage();
      if (url != null) {
        setState(() => _imgUrl = url);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error uploading image: $e"), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isUploadingImage = false);
    }
  }

  Future<void> _handleSave() async {
    if (!_formKey.currentState!.validate()) return;

    setState(() => _isLoading = true);
    final repo = ref.read(contentRepositoryProvider);

    try {
      if (widget.healthTip == null) {
        // Create
        await repo.createHealthTip(
          title: _titleCtrl.text.trim(),
          category: _catCtrl.text.trim(),
          readTime: _timeCtrl.text.trim(),
          content: _contentCtrl.text.trim(),
          imageUrl: _imgUrl,
          externalLink: _externalLinkCtrl.text.trim().isEmpty ? null : _externalLinkCtrl.text.trim(),
        );
      } else {
        // Update
        await repo.updateHealthTip(
          id: widget.healthTip!.id,
          title: _titleCtrl.text.trim(),
          category: _catCtrl.text.trim(),
          readTime: _timeCtrl.text.trim(),
          content: _contentCtrl.text.trim(),
          imageUrl: _imgUrl,
          externalLink: _externalLinkCtrl.text.trim().isEmpty ? null : _externalLinkCtrl.text.trim(),
        );
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text("Content Saved Successfully"),
            backgroundColor: Colors.green,
          ),
        );
        context.pop(true); // Return true to indicate refresh needed
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text("Error: $e"), backgroundColor: Colors.red),
        );
      }
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final isEditing = widget.healthTip != null;

    return Scaffold(
      appBar: AppBar(
        title: Text(isEditing ? "Edit Health Tip" : "New Health Tip"),
        backgroundColor: Colors.white,
        foregroundColor: Colors.black,
        elevation: 1,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: Form(
          key: _formKey,
          child: Column(
            children: [
              _buildField("Title", _titleCtrl),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(child: _buildField("Category", _catCtrl)),
                  const SizedBox(width: 12),
                  Expanded(
                    child: _buildField("Read Time (e.g., 5 min)", _timeCtrl),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              GestureDetector(
                onTap: _isUploadingImage ? null : _pickAndUploadImage,
                child: Container(
                  height: 150,
                  width: double.infinity,
                  decoration: BoxDecoration(
                    color: Colors.grey[200],
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: Colors.grey[400]!, style: BorderStyle.solid),
                  ),
                  child: _isUploadingImage
                      ? const Center(child: CircularProgressIndicator())
                      : (_imgUrl != null && _imgUrl!.isNotEmpty)
                          ? ClipRRect(
                              borderRadius: BorderRadius.circular(12),
                              child: Image.network(_imgUrl!, fit: BoxFit.cover),
                            )
                          : Column(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(Icons.add_a_photo, size: 40, color: Colors.grey[600]),
                                const SizedBox(height: 8),
                                Text("Add Thumbnail Image", style: TextStyle(color: Colors.grey[700])),
                              ],
                            ),
                ),
              ),
              if (_imgUrl != null && _imgUrl!.isNotEmpty)
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    onPressed: () => setState(() => _imgUrl = null),
                    icon: const Icon(Icons.delete, color: Colors.red, size: 16),
                    label: const Text("Remove Image", style: TextStyle(color: Colors.red)),
                  ),
                ),
              const SizedBox(height: 16),
              _buildField("External Article URL (Optional)", _externalLinkCtrl, required: false),
              const SizedBox(height: 16),
              _buildField("Content / Body", _contentCtrl, maxLines: 10),

              const SizedBox(height: 32),

              SizedBox(
                width: double.infinity,
                height: 50,
                child: ElevatedButton(
                  onPressed: _isLoading ? null : _handleSave,
                  style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFF4A90E2),
                    foregroundColor: Colors.white,
                  ),
                  child: _isLoading
                      ? const CircularProgressIndicator(color: Colors.white)
                      : Text(isEditing ? "Update Content" : "Publish Content"),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildField(
    String label,
    TextEditingController ctrl, {
    int maxLines = 1,
    bool required = true,
  }) {
    return TextFormField(
      controller: ctrl,
      maxLines: maxLines,
      decoration: InputDecoration(
        labelText: label,
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        alignLabelWithHint: true,
      ),
      validator: (v) {
        if (required && (v == null || v.isEmpty)) return "Required";
        return null;
      },
    );
  }
}
