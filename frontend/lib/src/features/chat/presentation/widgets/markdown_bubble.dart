
import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

class MarkdownBubble extends StatelessWidget {
  final String data;
  final bool isMe;
  final bool isDark;

  const MarkdownBubble({
    super.key,
    required this.data,
    required this.isMe,
    required this.isDark,
  });

  @override
  Widget build(BuildContext context) {
    // 1. Establish Base Text Color
    final textColor = isMe
        ? Colors.white
        : (isDark ? Colors.white : Colors.black87);

    // 2. Define Styles
    final styleSheet = MarkdownStyleSheet(
      p: TextStyle(color: textColor, fontSize: 16),
      h1: TextStyle(
          color: textColor, fontSize: 24, fontWeight: FontWeight.bold),
      h2: TextStyle(
          color: textColor, fontSize: 20, fontWeight: FontWeight.bold),
      h3: TextStyle(
          color: textColor, fontSize: 18, fontWeight: FontWeight.w600),
      strong: TextStyle(color: textColor, fontWeight: FontWeight.bold),
      em: TextStyle(color: textColor, fontStyle: FontStyle.italic),
      code: TextStyle(
        backgroundColor:
            isMe ? Colors.blue[700] : (isDark ? Colors.grey[800] : Colors.grey[300]),
        color: textColor,
        fontFamily: 'monospace',
      ),
      blockquote: TextStyle(
          color: textColor.withOpacity(0.8), fontStyle: FontStyle.italic),
      blockquoteDecoration: BoxDecoration(
        color: isMe ? Colors.blue[600] : (isDark ? Colors.grey[800] : Colors.grey[300]),
        borderRadius: BorderRadius.circular(4),
      ),
      listBullet: TextStyle(color: textColor),
    );

    return MarkdownBody(
      data: data,
      styleSheet: styleSheet,
      imageBuilder: (uri, title, alt) {
        // 3. IMAGE SWAPPER LOGIC
        // If image source is 'shutterstock', render placeholder
        if (uri.toString() == 'shutterstock') {
          return _buildAnalysisPlaceholder(context, alt ?? "Medical Topic");
        }

        // Fallback to standard network image (if any real URLs are sent)
        return Image.network(uri.toString());
      },
      onTapLink: (text, href, title) {
        // Handle links if needed
      },
    );
  }

  Widget _buildAnalysisPlaceholder(BuildContext context, String topic) {
    final theme = Theme.of(context);
    final isDarkTheme = theme.brightness == Brightness.dark;
    
    // Light Blue / Grey Accent
    final bgColor = isDarkTheme ? Colors.blueGrey[900] : Colors.blue[50];
    final iconColor = isDarkTheme ? Colors.blue[200] : Colors.blue[700];
    final textColor = isDarkTheme ? Colors.white70 : Colors.blueGrey[800];

    return Container(
      margin: const EdgeInsets.symmetric(vertical: 8),
      width: double.infinity,
      child: AspectRatio(
        aspectRatio: 16 / 9,
        child: Container(
          decoration: BoxDecoration(
            color: bgColor,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(
              color: iconColor!.withOpacity(0.3),
              width: 1,
            ),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.image_search, size: 48, color: iconColor),
              const SizedBox(height: 8),
              Text(
                "Medical Illustration",
                style: TextStyle(
                  color: iconColor,
                  fontWeight: FontWeight.bold,
                  fontSize: 14,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                topic,
                style: TextStyle(
                  color: textColor,
                  fontSize: 12,
                ),
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      ),
    );
  }
}
