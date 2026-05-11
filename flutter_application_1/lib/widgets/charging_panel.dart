import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/dashboard_provider.dart';

class ChargingPanel extends StatelessWidget {
  const ChargingPanel({super.key});

  String _formatTime(double? minutes) {
    if (minutes == null) return '--';
    if (minutes <= 0) return 'Ready';
    final h = minutes ~/ 60;
    final m = (minutes % 60).round();
    if (h > 0) return '${h}h ${m}m';
    return '${m}m';
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DashboardProvider>(
      builder: (context, provider, _) {
        final data = provider.data;
        if (!data.isCharging) return const SizedBox.shrink();

        return Container(
          width: 320,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.green.shade900.withValues(alpha: 0.92),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.greenAccent, width: 1.5),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Header
              Row(
                children: [
                  const Icon(Icons.bolt, color: Colors.greenAccent, size: 28),
                  const SizedBox(width: 8),
                  const Text(
                    'CHARGING',
                    style: TextStyle(
                      color: Colors.greenAccent,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${data.chargingPowerKw?.toStringAsFixed(0) ?? "--"} kW',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // SOC progress bar
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: LinearProgressIndicator(
                  value: (data.chargingSocPercent ?? 0) / 100.0,
                  minHeight: 20,
                  backgroundColor: Colors.grey.shade800,
                  valueColor: const AlwaysStoppedAnimation<Color>(Colors.greenAccent),
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '${data.chargingSocPercent?.toStringAsFixed(1) ?? "--"}%',
                style: const TextStyle(color: Colors.white70, fontSize: 14),
              ),
              const SizedBox(height: 12),

              // Time estimates
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _TimeEstimate(
                    label: 'To ${data.chargingTargetSoc.round()}%',
                    time: _formatTime(data.estMinutesToTarget),
                  ),
                  _TimeEstimate(
                    label: 'To 100%',
                    time: _formatTime(data.estMinutesToFull),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Target SOC selector
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Text('Target: ', style: TextStyle(color: Colors.white70)),
                  for (final target in [80.0, 90.0, 100.0])
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: ChoiceChip(
                        label: Text('${target.round()}%'),
                        selected: data.chargingTargetSoc == target,
                        selectedColor: Colors.greenAccent,
                        onSelected: (_) => provider.setChargingTarget(target),
                      ),
                    ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _TimeEstimate extends StatelessWidget {
  final String label;
  final String time;

  const _TimeEstimate({required this.label, required this.time});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(color: Colors.white54, fontSize: 12)),
        const SizedBox(height: 4),
        Text(time, style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
      ],
    );
  }
}
