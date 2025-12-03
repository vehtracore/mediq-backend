import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  // Brand Colors
  static const Color medicalBlue = Color(0xFF4A90E2);
  static const Color softTeal = Color(0xFF50E3C2);
  static const Color bgWhite = Color(0xFFFFFFFF);
  static const Color surfaceGray = Color(0xFFF4F6F8);
  static const Color textDark = Color(0xFF2D3436);

  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: surfaceGray,
      primaryColor: medicalBlue,

      // Color Scheme
      colorScheme: const ColorScheme.light(
        primary: medicalBlue,
        secondary: softTeal,
        surface: bgWhite,
        onSurface: textDark,
        error: Color(0xFFE57373),
      ),

      // Typography (Poppins for Headers, Lato for Body)
      textTheme: TextTheme(
        displayLarge: GoogleFonts.poppins(
          fontSize: 32,
          fontWeight: FontWeight.bold,
          color: textDark,
        ),
        displayMedium: GoogleFonts.poppins(
          fontSize: 28,
          fontWeight: FontWeight.w600,
          color: textDark,
        ),
        titleLarge: GoogleFonts.poppins(
          fontSize: 22,
          fontWeight: FontWeight.w600,
          color: textDark,
        ),
        bodyLarge: GoogleFonts.lato(fontSize: 16, color: textDark),
        bodyMedium: GoogleFonts.lato(
          fontSize: 14,
          color: textDark.withOpacity(0.8),
        ),
        labelLarge: GoogleFonts.lato(
          fontSize: 14,
          fontWeight: FontWeight.bold,
          color: Colors.white,
        ),
      ),

      // Card Style (Glassmorphism hints with soft shadows)
      cardTheme: CardThemeData(
        color: bgWhite,
        elevation: 4,
        shadowColor: medicalBlue.withOpacity(0.15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        margin: const EdgeInsets.all(8),
      ),

      // Input Fields (Rounded & Soft)
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: bgWhite,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 20,
          vertical: 16,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: Colors.grey.withOpacity(0.2)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(16),
          borderSide: const BorderSide(color: medicalBlue, width: 1.5),
        ),
      ),

      // Buttons
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: medicalBlue,
          foregroundColor: Colors.white,
          elevation: 2,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
          textStyle: GoogleFonts.lato(fontWeight: FontWeight.bold),
        ),
      ),
    );
  }
}
