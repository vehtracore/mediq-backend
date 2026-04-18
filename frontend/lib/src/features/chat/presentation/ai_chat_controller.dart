import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:mediq_app/src/core/api/dio_client.dart';
import 'package:mediq_app/src/features/auth/presentation/user_controller.dart';
import 'package:mediq_app/src/features/lab/data/lab_result_model.dart';
import 'package:mediq_app/src/features/chat/data/pdf_service.dart';
import 'package:open_file/open_file.dart';
import 'package:printing/printing.dart';
import 'package:path_provider/path_provider.dart';
import 'dart:io';

// 1. STATE
class AiChatState {
  final List<Map<String, dynamic>> messages;
  final bool isLoading;

  AiChatState({this.messages = const [], this.isLoading = false});

  AiChatState copyWith(
      {List<Map<String, dynamic>>? messages, bool? isLoading}) {
    return AiChatState(
      messages: messages ?? this.messages,
      isLoading: isLoading ?? this.isLoading,
    );
  }
}

// 2. CONTROLLER
class AiChatController extends StateNotifier<AiChatState> {
  final Dio _dio;
  final String subscriptionTier; // "free" or "premium"

  AiChatController(this._dio, this.subscriptionTier) : super(AiChatState());

  Future<void> sendMessage(String text, {String? imageUrl, String language = 'English'}) async {
    if (text.trim().isEmpty && imageUrl == null) return;

    final userMsg = {'role': 'user', 'message': text, 'image': imageUrl};
    state =
        state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    try {
      // --- PREPARE HISTORY (Premium Only) ---
      List<Map<String, dynamic>> history = [];
      
      if (subscriptionTier == 'premium') {
        // Convert local chat state to Gemini History Format
        // Exclude the very last message we just added (that's the current query)
        // And exclude any system/error messages
        
        for (var msg in state.messages) {
             if (msg == userMsg) continue; // Skip current
             if (msg['role'] == 'system') continue; // Skip errors

             // Map roles: 'user'->'user', 'ai'->'model'
             String role = (msg['role'] == 'user') ? 'user' : 'model';
             
             // Gemini expects: {'role': '...', 'parts': ['...']}
             // Note: We are only sending text history for now to keep it simple/cheap
             history.add({
               'role': role, 
               'parts': [ msg['message'] ] 
             });
        }
      }

      // Connects to your backend
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {
            "message": text, 
            "image_url": imageUrl,
            "history": history, // Send history (empty if free)
            "language": language, // Send selected language
          });

      final aiMsg = {'role': 'ai', 'message': response.data['response']};
      state = state
          .copyWith(messages: [...state.messages, aiMsg], isLoading: false);
    } on DioException catch (e) {
      String errorMessage = "Connection error. Please try again.";
      
      // Extract specific error from backend (e.g. Free Tier Limit)
      if (e.response != null && e.response?.data != null) {
         final data = e.response?.data;
         if (data is Map && data.containsKey('detail')) {
           errorMessage = data['detail'];
         }
      }

      final errorMsg = {
        'role': 'system',
        'message': errorMessage
      };
      state = state.copyWith(messages: [...state.messages, errorMsg], isLoading: false);
    } catch (e) {
      final errorMsg = {
        'role': 'system',
        'message': "System Error: ${e.toString()}"
      };
      state = state.copyWith(messages: [...state.messages, errorMsg], isLoading: false);
    }

  }

  Future<void> sendLabResult(LabAnalysisResponse result) async {
    // 1. Create a "Medical Card" message for the user's UI
    final userMsg = {
      'role': 'user',
      'message': 'Lab Result Scanned',
      'type': 'lab_result',
      'lab_data': result, // Store full object for bubble rendering
    };
    
    // Add to local state immediately
    state = state.copyWith(messages: [...state.messages, userMsg], isLoading: true);

    // 2. Construct the Hidden System Prompt for Gemini
    final hiddenPrompt = _buildSystemPrompt(result);

    try {
      // Connects to your backend
      final response = await _dio.post('/api/v1/chat/analyze',
          data: {
            "message": hiddenPrompt, 
            "history": [] // TODO: Add history if needed
          });

      final aiMsg = {'role': 'ai', 'message': response.data['response']};
      state = state.copyWith(messages: [...state.messages, aiMsg], isLoading: false);
      
    } catch (e) {
      final errorMsg = {'role': 'system', 'message': "AI Analysis Failed: $e"};
      state = state.copyWith(messages: [...state.messages, errorMsg], isLoading: false);
    }
  }

  String _buildSystemPrompt(LabAnalysisResponse result) {
    if (result.readings == null) return "User scanned a test strip but no readings were found.";
    
    final r = result.readings!;
    // Build a concise summary for the AI
    return """
[SYSTEM NOTIFICATION: User performed a urinalysis scan.]
RESULTS:
- Leukocytes: ${r.leukocytes?.value}
- Nitrites: ${r.nitrites?.value}
- Protein: ${r.protein?.value}
- pH: ${r.ph?.value}
- Blood: ${r.blood?.value}
- Glucose: ${r.glucose?.value}
- Ketones: ${r.ketones?.value}
- Billirubin: ${r.bilirubin?.value}

INSTRUCTION: Analyze these results. If any values are abnormal (Positive/High), explain what they might indicate in simple terms. Ask if they have specific symptoms related to these findings.
""";
  }

  Future<void> summarizeSession() async {
    state = state.copyWith(isLoading: true);
    
    // 1. Identify if we have Lab Results in the chat
    LabAnalysisResponse? lastLabResult;
    try {
      final labMsg = state.messages.lastWhere((m) => m['type'] == 'lab_result', orElse: () => {});
      if (labMsg.isNotEmpty) {
        lastLabResult = labMsg['lab_data'] as LabAnalysisResponse;
      }
    } catch (_) {}

    // 2. Ask AI to Summarize the text conversation
    String summaryText = "Consultation Summary unavailable.";
    try {
      final response = await _dio.post('/api/v1/chat/analyze', data: {
        "message": "Summarize this entire conversation into a structured medical note. Sections: 1. Patient Symptoms, 2. Lab Results (if any), 3. Recommended Actions. Keep it professional.",
        "history": state.messages.map((m) => {
          'role': m['role'] == 'user' ? 'user' : 'model',
          'parts': [m['message']]
        }).toList()
      });
      summaryText = response.data['response'];
    } catch (e) {
      summaryText = "Could not generate AI summary due to error: $e";
    }

    // 3. Generate PDF
    try {
      final pdfBytes = await PdfService().generateMedicalNote(
        messages: state.messages,
        labResult: lastLabResult,
        summary: summaryText,
      );

      // 4. Save & Open
      final output = await getApplicationDocumentsDirectory();
      final file = File("${output.path}/mediq_summary_${DateTime.now().millisecondsSinceEpoch}.pdf");
      await file.writeAsBytes(pdfBytes);
      
      state = state.copyWith(isLoading: false);
      
      // Open the file
      await OpenFile.open(file.path);
      
    } catch (e) {
      state = state.copyWith(isLoading: false);
      print("PDF Error: $e");
      // Ideally show a snackbar here, but controller shouldn't handle UI. 
      // We can rely on OpenFile throwing if it fails.
    }
  }
}


// 3. PROVIDER
// autoDispose ensures the session is wiped when user leaves the screen
final aiChatControllerProvider =
    StateNotifierProvider.autoDispose<AiChatController, AiChatState>((ref) {
  final dio = ref.watch(dioProvider);
  
  // Get User Tier (default to 'free' if loading)
  final userAsync = ref.watch(userProvider);
  final tier = userAsync.value?.subscriptionTier ?? 'free';
  
  return AiChatController(dio, tier);
});
