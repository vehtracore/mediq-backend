import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  // --- BRAND COLORS (Kept from your original file) ---
  static const Color medicalBlue = Color(0xFF4A90E2);
  static const Color softTeal = Color(0xFF50E3C2);
  static const Color bgWhite = Color(0xFFFFFFFF);
  static const Color surfaceGray = Color(0xFFF4F6F8);
  static const Color textDark = Color(0xFF2D3436);

  // --- DARK MODE COLORS ---
  static const Color bgDark = Color(0xFF121212); // Deep background
  static const Color surfaceDark = Color(0xFF1E1E1E); // Cards/AppBar
  static const Color textLight = Color(0xFFE0E0E0);

  // --- ☀️ LIGHT THEME (Your Original Design) ---
  static ThemeData get lightTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
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
            fontSize: 32, fontWeight: FontWeight.bold, color: textDark),
        displayMedium: GoogleFonts.poppins(
            fontSize: 28, fontWeight: FontWeight.w600, color: textDark),
        titleLarge: GoogleFonts.poppins(
            fontSize: 22, fontWeight: FontWeight.w600, color: textDark),
        bodyLarge: GoogleFonts.lato(fontSize: 16, color: textDark),
        bodyMedium:
            GoogleFonts.lato(fontSize: 14, color: textDark.withOpacity(0.8)),
        labelLarge: GoogleFonts.lato(
            fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white),
      ),

      // Card Style
      cardTheme: CardThemeData(
        color: bgWhite,
        elevation: 4,
        shadowColor: medicalBlue.withOpacity(0.15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        margin: const EdgeInsets.all(8),
      ),

      // AppBar
      appBarTheme: AppBarTheme(
        backgroundColor: bgWhite,
        foregroundColor: textDark,
        elevation: 0,
        titleTextStyle: GoogleFonts.poppins(
            fontSize: 20, fontWeight: FontWeight.bold, color: textDark),
      ),

      // Input Fields
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: bgWhite,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none),
        enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide(color: Colors.grey.withOpacity(0.2))),
        focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: medicalBlue, width: 1.5)),
        hintStyle: GoogleFonts.lato(color: Colors.grey[400]),
      ),

      // Buttons
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: medicalBlue,
          foregroundColor: Colors.white,
          elevation: 2,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: GoogleFonts.lato(fontWeight: FontWeight.bold),
        ),
      ),
    );
  }

  // --- 🌙 DARK THEME (New, matching your style) ---
  static ThemeData get darkTheme {
    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: bgDark,
      primaryColor: medicalBlue,

      // Color Scheme
      colorScheme: const ColorScheme.dark(
        primary: medicalBlue,
        secondary: softTeal,
        surface: surfaceDark,
        onSurface: textLight,
        error: Color(0xFFE57373),
      ),

      // Typography (White Text)
      textTheme: TextTheme(
        displayLarge: GoogleFonts.poppins(
            fontSize: 32, fontWeight: FontWeight.bold, color: textLight),
        displayMedium: GoogleFonts.poppins(
            fontSize: 28, fontWeight: FontWeight.w600, color: textLight),
        titleLarge: GoogleFonts.poppins(
            fontSize: 22, fontWeight: FontWeight.w600, color: textLight),
        bodyLarge: GoogleFonts.lato(fontSize: 16, color: textLight),
        bodyMedium:
            GoogleFonts.lato(fontSize: 14, color: textLight.withOpacity(0.8)),
        labelLarge: GoogleFonts.lato(
            fontSize: 14, fontWeight: FontWeight.bold, color: Colors.white),
      ),

      // Card Style
      cardTheme: CardThemeData(
        color: surfaceDark,
        elevation: 2,
        shadowColor: Colors.black.withOpacity(0.3),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
        margin: const EdgeInsets.all(8),
      ),

      // AppBar
      appBarTheme: AppBarTheme(
        backgroundColor: surfaceDark,
        foregroundColor: textLight,
        elevation: 0,
        titleTextStyle: GoogleFonts.poppins(
            fontSize: 20, fontWeight: FontWeight.bold, color: textLight),
      ),

      // Input Fields
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF2C2C2C), // Slightly lighter than background
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none),
        enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide(color: Colors.white.withOpacity(0.1))),
        focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: const BorderSide(color: medicalBlue, width: 1.5)),
        hintStyle: GoogleFonts.lato(color: Colors.grey[600]),
      ),

      // Buttons
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: medicalBlue,
          foregroundColor: Colors.white,
          elevation: 2,
          padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 12),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
          textStyle: GoogleFonts.lato(fontWeight: FontWeight.bold),
        ),
      ),
    );
  }
}
