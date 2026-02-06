import 'package:flutter/material.dart';
import '../../lab/data/lab_result_model.dart';

class LabResultBubble extends StatelessWidget {
  final LabAnalysisResponse result;
  final bool isMe;

  const LabResultBubble({
    super.key,
    required this.result,
    required this.isMe,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isDark = theme.brightness == Brightness.dark;

    // Determine Status Color
    final bool hasIssues = _hasAbnormalValues(result.readings);
    final Color statusColor = hasIssues ? Colors.redAccent : Colors.green;

    return Align(
      alignment: isMe ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        width: 280,
        decoration: BoxDecoration(
          color: isMe
              ? Colors.blue[50] // Lighter blue for me
              : (isDark ? const Color(0xFF2C2C2C) : Colors.white),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: statusColor.withOpacity(0.5), width: 1.5),
          boxShadow: [
            BoxShadow(
              color: Colors.black.withOpacity(0.05),
              blurRadius: 5,
              offset: const Offset(0, 2),
            )
          ],
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Header
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: statusColor.withOpacity(0.1),
                borderRadius: const BorderRadius.vertical(top: Radius.circular(15)),
              ),
              child: Row(
                children: [
                  Icon(
                    hasIssues ? Icons.warning_amber_rounded : Icons.check_circle_outline,
                    color: statusColor,
                    size: 20,
                  ),
                  const SizedBox(width: 8),
                  Text(
                    "Urinalysis Result",
                    style: TextStyle(
                      color: statusColor,
                      fontWeight: FontWeight.bold,
                      fontSize: 15,
                    ),
                  ),
                ],
              ),
            ),
            
            // Content
            Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildRow("Leukocytes", result.readings?.leukocytes?.value),
                  _buildRow("Nitrites", result.readings?.nitrites?.value),
                  _buildRow("Blood", result.readings?.blood?.value),
                  _buildRow("Protein", result.readings?.protein?.value),
                  _buildRow("Glucose", result.readings?.glucose?.value),
                  
                  if (hasIssues) ...[
                    const Divider(height: 24),
                    Text(
                      "Analysis Required",
                      style: TextStyle(
                        color: Colors.red[700],
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRow(String label, String? value) {
    if (value == null) return const SizedBox.shrink();
    
    // Highlight abnormal values
    bool isAbnormal = !['Negative', 'Normal'].contains(value);

    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(
            label,
            style: const TextStyle(fontSize: 13, color: Colors.grey),
          ),
          Text(
            value,
            style: TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w600,
              color: isAbnormal ? Colors.red : Colors.black87,
            ),
          ),
        ],
      ),
    );
  }

  bool _hasAbnormalValues(LabReading? readings) {
    if (readings == null) return false;
    final values = [
      readings.leukocytes?.value,
      readings.nitrites?.value,
      readings.blood?.value,
      readings.protein?.value,
      readings.glucose?.value,
      readings.ketones?.value,
      readings.bilirubin?.value,
    ];
    
    return values.any((v) => v != null && !['Negative', 'Normal'].contains(v));
  }
}
