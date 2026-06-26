import 'dart:async';

import 'package:flutter/material.dart';

class ConsultationCountdownBadge extends StatefulWidget {
  final DateTime? videoEndsAt;
  final DateTime? messagesEndAt;
  final bool consultationStarted;
  final bool isClosed;
  final bool compact;

  const ConsultationCountdownBadge({
    super.key,
    required this.videoEndsAt,
    required this.messagesEndAt,
    required this.consultationStarted,
    required this.isClosed,
    this.compact = false,
  });

  @override
  State<ConsultationCountdownBadge> createState() =>
      _ConsultationCountdownBadgeState();
}

class _ConsultationCountdownBadgeState
    extends State<ConsultationCountdownBadge> {
  Timer? _timer;
  DateTime _now = DateTime.now();

  @override
  void initState() {
    super.initState();
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) {
        setState(() => _now = DateTime.now());
      }
    });
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = _countdownState();
    final theme = Theme.of(context);

    return AnimatedContainer(
      duration: const Duration(milliseconds: 200),
      padding: EdgeInsets.symmetric(
        horizontal: widget.compact ? 10 : 12,
        vertical: widget.compact ? 6 : 7,
      ),
      decoration: BoxDecoration(
        color: state.backgroundColor,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: state.borderColor),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.12),
            blurRadius: 12,
            offset: const Offset(0, 4),
          ),
        ],
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            state.icon,
            size: widget.compact ? 15 : 16,
            color: state.foregroundColor,
          ),
          const SizedBox(width: 6),
          Text(
            widget.compact ? state.compactLabel : state.label,
            style: theme.textTheme.labelMedium?.copyWith(
              color: state.foregroundColor,
              fontWeight: FontWeight.w800,
              letterSpacing: 0,
            ),
          ),
        ],
      ),
    );
  }

  _CountdownState _countdownState() {
    if (widget.isClosed) {
      return _CountdownState.ended();
    }

    final videoEndsAt = widget.videoEndsAt;
    final messagesEndAt = widget.messagesEndAt;

    if (!widget.consultationStarted || videoEndsAt == null) {
      return _CountdownState.waiting();
    }

    if (_now.isBefore(videoEndsAt)) {
      final remaining = videoEndsAt.difference(_now);
      return _CountdownState.video(remaining);
    }

    if (messagesEndAt != null && _now.isBefore(messagesEndAt)) {
      final remaining = messagesEndAt.difference(_now);
      return _CountdownState.grace(remaining);
    }

    return _CountdownState.ended();
  }
}

class _CountdownState {
  final String label;
  final String compactLabel;
  final IconData icon;
  final Color foregroundColor;
  final Color backgroundColor;
  final Color borderColor;

  const _CountdownState({
    required this.label,
    required this.compactLabel,
    required this.icon,
    required this.foregroundColor,
    required this.backgroundColor,
    required this.borderColor,
  });

  factory _CountdownState.waiting() {
    return const _CountdownState(
      label: 'Waiting',
      compactLabel: 'Waiting',
      icon: Icons.hourglass_empty,
      foregroundColor: Color(0xFF334155),
      backgroundColor: Color(0xFFF8FAFC),
      borderColor: Color(0xFFE2E8F0),
    );
  }

  factory _CountdownState.video(Duration remaining) {
    final warning = remaining <= const Duration(minutes: 5);
    final formatted = _formatDuration(remaining);
    return _CountdownState(
      label: 'Video $formatted',
      compactLabel: formatted,
      icon: warning ? Icons.timer : Icons.timer_outlined,
      foregroundColor:
          warning ? const Color(0xFF991B1B) : const Color(0xFF14532D),
      backgroundColor:
          warning ? const Color(0xFFFEE2E2) : const Color(0xFFDCFCE7),
      borderColor: warning ? const Color(0xFFFCA5A5) : const Color(0xFF86EFAC),
    );
  }

  factory _CountdownState.grace(Duration remaining) {
    final formatted = _formatDuration(remaining);
    return _CountdownState(
      label: 'Messaging $formatted',
      compactLabel: formatted,
      icon: Icons.chat_bubble_outline,
      foregroundColor: const Color(0xFF1D4ED8),
      backgroundColor: const Color(0xFFDBEAFE),
      borderColor: const Color(0xFF93C5FD),
    );
  }

  factory _CountdownState.ended() {
    return const _CountdownState(
      label: 'Ended',
      compactLabel: 'Ended',
      icon: Icons.lock_clock,
      foregroundColor: Color(0xFF64748B),
      backgroundColor: Color(0xFFF1F5F9),
      borderColor: Color(0xFFCBD5E1),
    );
  }

  static String _formatDuration(Duration duration) {
    final safeDuration = duration.isNegative ? Duration.zero : duration;
    final minutes = safeDuration.inMinutes;
    final seconds = safeDuration.inSeconds.remainder(60);
    return '${minutes.toString().padLeft(2, '0')}:'
        '${seconds.toString().padLeft(2, '0')}';
  }
}
